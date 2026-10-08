"""Collect evidence, preserving uncertainty and distinguishing links from fixes."""

from __future__ import annotations

import base64
import re
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.parse import quote, urlencode

from .github import GitHubError, NotFound
from .policy_links import policy_links
from .text import prose

REPOSITORY = r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"
TARGET = re.compile(rf"(?P<repo>{REPOSITORY})#(?P<number>[1-9][0-9]*)\Z")
URL_TARGET = re.compile(
    rf"https://github\.com/(?P<repo>{REPOSITORY})/issues/(?P<number>[1-9][0-9]*)/?\Z"
)
MAINTAINERS = {"OWNER", "MEMBER", "COLLABORATOR"}
POLICY_PATHS = ("CONTRIBUTING.md", ".github/CONTRIBUTING.md", "AGENTS.md")


class API(Protocol):
    def get(self, endpoint: str) -> Any: ...


def parse_target(value: str) -> tuple[str, int]:
    """Accept OWNER/REPO#NUMBER or a github.com issue URL."""
    match = TARGET.fullmatch(value) or URL_TARGET.fullmatch(value)
    if match is None:
        raise ValueError("Use OWNER/REPO#NUMBER or https://github.com/OWNER/REPO/issues/NUMBER.")
    repo = match["repo"]
    if any(part in {".", ".."} for part in repo.split("/")):
        raise ValueError("Invalid repository name.")
    return repo, int(match["number"])


def _reference_pattern(repo: str, number: int) -> re.Pattern[str]:
    return re.compile(
        rf"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?[ \t]+"
        rf"(?:#{number}(?![0-9])\b|{re.escape(repo)}#{number}(?![0-9])\b|"
        rf"https://github\.com/{re.escape(repo)}/issues/{number}(?![0-9])(?:\b|/))",
        re.IGNORECASE,
    )


def closes_issue(pr: dict[str, Any], repo: str, number: int) -> bool:
    """Match closing references, avoiding #12/#123 and cross-repo ambiguity."""
    return _closing_reference(pr, repo, number) is not None


def _closing_reference(pr: dict[str, Any], repo: str, number: int) -> re.Match | None:
    body = prose(str(pr.get("body") or ""))
    # Unqualified # references only apply to the PR's base repository.
    base_repo = pr.get("base", {}).get("repo", {}).get("full_name", repo)
    if base_repo.lower() != repo.lower():
        body = re.sub(r"(?<![\w/])#[0-9]+", lambda m: " " * len(m[0]), body)
    return _reference_pattern(repo, number).search(body)


def _finding(code: str, severity: str, message: str, url: str, excerpt: str = "") -> dict:
    return dict(code=code, severity=severity, message=message, url=url, excerpt=excerpt)


def _source_finding(
    code: str,
    severity: str,
    message: str,
    url: str,
    text: str,
    match: re.Match,
    path: str | None = None,
) -> dict:
    """Cite the original lines matched in offset-preserving classifier text."""
    line_start = text.count("\n", 0, match.start()) + 1
    line_end = text.count("\n", 0, match.end() - 1) + 1
    start = text.rfind("\n", 0, match.start()) + 1
    end = text.find("\n", match.end())
    if end < 0:
        end = len(text)
    # Keep context bounded even when a source puts its whole document on one line.
    excerpt_start = max(start, match.start() - 160)
    excerpt_end = min(end, match.end() + 160)
    if path:
        url += f"#L{line_start}"
        if line_start != line_end:
            url += f"-L{line_end}"
    finding = _finding(code, severity, message, url, text[excerpt_start:excerpt_end].rstrip("\r"))
    finding.update(
        line_start=line_start,
        line_end=line_end,
        excerpt_truncated=excerpt_start != start or excerpt_end != end,
    )
    if path:
        finding["path"] = path
    return finding


def _pages(api: API, endpoint: str, omissions: list[str], limit: int = 2) -> list[dict]:
    items: list[dict] = []
    for page in range(1, limit + 1):
        try:
            result = api.get(f"{endpoint}?per_page=100&page={page}")
        except GitHubError:
            omissions.append(f"Could not read collection: {endpoint} (page {page})")
            return items
        if not isinstance(result, list):
            raise GitHubError("Expected a GitHub collection response.")
        items.extend(result)
        if len(result) < 100:
            return items
    omissions.append(f"Collection capped at {limit * 100} entries: {endpoint}")
    return items


def _policy_documents(api: API, repo: str, sha: str, omissions: list[str]) -> list[dict]:
    documents: list[dict] = []
    queue = list(POLICY_PATHS)
    states: dict[str, str] = {}
    explicit: set[str] = set()

    def missing_link(path: str) -> None:
        gap = f"Linked policy not found or inaccessible: {path}"
        if gap not in omissions:
            omissions.append(gap)

    while queue and len(states) < 6:
        path = queue.pop(0)
        if path in states:
            continue
        states[path] = "failed"  # Every actual contents request uses the same bounded budget.
        try:
            result = api.get(f"repos/{repo}/contents/{quote(path)}?ref={sha}")
        except NotFound:
            states[path] = "missing"
            if path in explicit:
                missing_link(path)
            continue
        except GitHubError:
            omissions.append(f"Could not read policy: {path}")
            continue
        if not isinstance(result, dict):
            omissions.append(f"Policy did not return a supported text file: {path}")
            continue
        if (
            result.get("encoding") != "base64"
            or not isinstance(result.get("size"), int)
            or result["size"] > 80000
            or not isinstance(result.get("content"), str)
        ):
            omissions.append(f"Policy unsupported or larger than 80 KB: {path}")
            continue
        try:
            raw = base64.b64decode("".join(result["content"].split()), validate=True)
            if len(raw) > 80000:
                omissions.append(f"Policy larger than 80 KB: {path}")
                continue
            text = raw.decode("utf-8")
        except (ValueError, KeyError, UnicodeError):
            omissions.append(f"Could not decode policy: {path}")
            continue
        states[path] = "fetched"
        documents.append(
            dict(path=path, text=text, url=f"https://github.com/{repo}/blob/{sha}/{quote(path)}")
        )
        for link in policy_links(text, repo, path):
            if link.path is None:
                gap = f"Linked policy in {path}: {link.reason}"
                if gap not in omissions:
                    omissions.append(gap)
                continue
            explicit.add(link.path)
            if states.get(link.path) == "missing":
                # Default probes may 404 before a later document explicitly links them.
                missing_link(link.path)
            if link.path not in states and link.path not in queue:
                queue.append(link.path)
    if any(path not in states for path in queue):
        omissions.append("Linked policy discovery capped at six file requests.")
    return documents


def _policy_findings(documents: list[dict], assigned: bool, labels: set[str]) -> list[dict]:
    findings = []
    for doc in documents:
        # Detect only recognizable rules; all other policy text remains available to review.
        text = prose(doc["text"])
        autonomous_rule = re.search(
            r"agent[^\x00]{0,40}(?:filing|open(?:ing)?)[^\x00]{0,80}(?:PRs|pull requests)"
            r"[^\x00]{0,80}autonomously[^\x00]{0,160}(?:turn it off|not allowed|not acceptable)",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if autonomous_rule:
            findings.append(
                _source_finding(
                    "autonomous_agent_policy",
                    "blocker",
                    "Policy explicitly addresses autonomous agent PRs. Read it before proceeding.",
                    doc["url"],
                    doc["text"],
                    autonomous_rule,
                    doc["path"],
                )
            )
        assignment_rule = re.search(
            r"(?:author\s+must\s+(?:also\s+)?be\s+assigned|"
            r"pull\s+requests\s+from\s+outside[^\x00]{0,160}only[^\x00]{0,160}assigned|"
            r"external\s+PRs\s+must[^\x00]{0,160}assigned)",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if assignment_rule and "assign" in text.lower():
            exceptions = set(
                re.findall(r"[`\"'](help wanted|prs welcome)[`\"']", doc["text"], re.I)
            )
            exceptions = {label.lower() for label in exceptions}
            if not assigned and not (labels & exceptions):
                findings.append(
                    _source_finding(
                        "assignment_policy",
                        "blocker",
                        "Guide requires assignment; no matching assignment or welcome label found.",
                        doc["url"],
                        doc["text"],
                        assignment_rule,
                        doc["path"],
                    )
                )
        human_rule = re.search(
            r"(?:human[^\x00\r\n]{0,20}(?:loop|review)|(?:unreviewed|undisclosed) AI)", text, re.I
        )
        if human_rule:
            findings.append(
                _source_finding(
                    "human_review_policy",
                    "review",
                    "Contribution guide describes human review or AI disclosure expectations.",
                    doc["url"],
                    doc["text"],
                    human_rule,
                    doc["path"],
                )
            )
        approval_rule = re.search(
            r"\b(?:pull\s+requests?|PRs?)\s+must\s+link\s+to\b[^\x00]{0,160}"
            r"\b(?:issue|discussion)\b[^\x00]{0,80}\b(?:solution|proposal)\b"
            r"\s+has\s+been\s+approved\s+by\s+(?:a|the)\s+maintainer\b",
            text,
            re.IGNORECASE,
        )
        if approval_rule:
            findings.append(
                _source_finding(
                    "approval_policy",
                    "review",
                    "Policy requires a PR to link an approved issue or proposal. "
                    "Read its scope; approval was not verified by this scan.",
                    doc["url"],
                    doc["text"],
                    approval_rule,
                    doc["path"],
                )
            )
    return findings


def inspect(api: API, target: str, actor: str | None = None, max_prs: int = 8) -> dict:
    """Inspect one issue without creating issues, comments, branches, or PRs."""
    repo, number = parse_target(target)
    if not 1 <= max_prs <= 20:
        raise ValueError("max_prs must be between 1 and 20.")
    metadata = api.get(f"repos/{repo}")
    repo = metadata["full_name"]  # Follow GitHub repository redirects.
    issue = api.get(f"repos/{repo}/issues/{number}")
    if "pull_request" in issue:
        raise ValueError("The target is a pull request; supply an issue number.")
    findings = []
    omissions: list[str] = []
    issue_url = issue["html_url"]
    if metadata.get("archived"):
        findings.append(
            _finding("archived_repository", "blocker", "Repository is archived.", issue_url)
        )
    if issue.get("state") != "open":
        findings.append(_finding("closed_issue", "blocker", "Issue is closed.", issue_url))
    assignees = [item["login"] for item in issue.get("assignees", [])]
    assigned = bool(actor and actor.lower() in {name.lower() for name in assignees})
    if assignees and not assigned:
        findings.append(
            _finding(
                "claimed_issue",
                "review",
                f"Assigned to {', '.join(assignees)}; coordinate existing work.",
                issue_url,
            )
        )
    comments = _pages(api, f"repos/{repo}/issues/{number}/comments", omissions)
    timeline = _pages(api, f"repos/{repo}/issues/{number}/timeline", omissions)
    for item in [issue, *comments]:
        if item.get("author_association") not in MAINTAINERS:
            continue
        body = str(item.get("body") or "")
        stop_request = re.search(
            r"(?:do\s+not|don't|please\s+don't)\s+open\s+"
            r"(?:another\s+|a\s+|any\s+)?(?:PR\b|pull\s+request\b)",
            prose(body),
            re.I,
        )
        if stop_request:
            findings.append(
                _source_finding(
                    "maintainer_stop",
                    "blocker",
                    "A maintainer explicitly asks not to open a PR.",
                    item.get("html_url", issue_url),
                    body,
                    stop_request,
                )
            )
    candidates: dict[tuple[str, int], set[str]] = {}
    if any(item.get("event") in {"connected", "disconnected"} for item in timeline):
        omissions.append(
            "Manual issue/PR links changed in the timeline; current manual links "
            "are not resolved by this REST scan. Check the issue's Development sidebar."
        )
    for item in timeline:
        source = (item.get("source") or {}).get("issue") or {}
        if item.get("event") == "cross-referenced" and "pull_request" in source:
            match = re.fullmatch(
                rf"https://github\.com/({REPOSITORY})/pull/([1-9][0-9]*)",
                source.get("html_url", ""),
            )
            if match:
                candidates.setdefault((match[1], int(match[2])), set()).add("timeline")
    # Comments sometimes identify an earlier fix which never linked this issue directly.
    for item in [issue, *comments]:
        for match in re.finditer(
            rf"https://github\.com/({REPOSITORY})/pull/([1-9][0-9]*)(?![0-9])",
            str(item.get("body") or ""),
        ):
            candidates.setdefault((match[1], int(match[2])), set()).add("discussion")
    query = urlencode({"q": f'repo:{repo} is:pr "#{number}"', "per_page": 100})
    try:
        search = api.get(f"search/issues?{query}")
    except GitHubError:
        omissions.append("Could not search for pull requests.")
        search = {}
    if search.get("incomplete_results") or search.get("total_count", 0) > 100:
        omissions.append("PR search returned partial results.")
    for item in search.get("items", []):
        candidates.setdefault((repo, item["number"]), set()).add("search")
    if len(candidates) > max_prs:
        omissions.append(f"PR details capped at {max_prs} of {len(candidates)} candidates.")
    prs = []
    for (pr_repo, pr_number), origins in list(candidates.items())[:max_prs]:
        try:
            pr = api.get(f"repos/{pr_repo}/pulls/{pr_number}")
        except GitHubError:
            omissions.append(f"Could not read PR: {pr_repo}#{pr_number}")
            continue
        closing_match = _closing_reference(pr, repo, number)
        closing = closing_match is not None
        state = "merged" if pr.get("merged") else pr["state"]
        prs.append(
            dict(
                repository=pr_repo,
                number=pr_number,
                title=pr["title"],
                url=pr["html_url"],
                state=state,
                closes_issue=closing,
                discovered_by=sorted(origins),
            )
        )
        if closing and state in {"open", "merged"}:
            findings.append(
                _source_finding(
                    "existing_fix",
                    "blocker",
                    f"PR #{pr_number} ({state}) explicitly targets this issue.",
                    pr["html_url"],
                    str(pr.get("body") or ""),
                    closing_match,
                )
            )
        elif state == "closed" and (closing or "timeline" in origins):
            findings.append(
                _finding(
                    "closed_related_pr",
                    "review",
                    "A related PR is closed; read its discussion before reimplementing.",
                    pr["html_url"],
                )
            )
        elif "timeline" in origins or "discussion" in origins:
            findings.append(
                _finding(
                    "related_pr",
                    "review",
                    "A PR is mentioned or linked; its implementation overlap needs review.",
                    pr["html_url"],
                )
            )
    branch = metadata["default_branch"]
    commit = api.get(f"repos/{repo}/commits/{quote(branch, safe='')}")
    documents = _policy_documents(api, repo, commit["sha"], omissions)
    if not documents:
        omissions.append(
            "No contribution policy was found in the checked paths; rules may live elsewhere."
        )
    labels = {item["name"].lower() for item in issue.get("labels", [])}
    findings.extend(_policy_findings(documents, assigned, labels))
    if omissions:
        findings.append(
            _finding(
                "incomplete_evidence",
                "review",
                "Some evidence was not collected. Review collection gaps.",
                issue_url,
            )
        )
    decision = (
        "hold"
        if any(f["severity"] == "blocker" for f in findings)
        else ("review" if findings else "no_obvious_blockers")
    )
    return dict(
        schema="issue-preflight/1",
        fetched_at=datetime.now(timezone.utc).isoformat(),
        repository=repo,
        policy_ref=commit["sha"],
        actor=actor,
        issue=dict(
            number=number,
            title=issue["title"],
            url=issue_url,
            state=issue["state"],
            assignees=assignees,
            labels=sorted(labels),
        ),
        decision=decision,
        findings=findings,
        pull_requests=prs,
        policy_sources=[dict(path=doc["path"], url=doc["url"]) for doc in documents],
        collection_gaps=omissions,
        interpretation=(
            "Heuristic evidence review, not maintainer approval "
            "or a guarantee of complete discovery."
        ),
    )
