"""Collect evidence, preserving uncertainty and distinguishing links from fixes."""

from __future__ import annotations

import base64
import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.parse import quote, urlencode

from .github import GitHubError, NotFound
from .policy_links import (
    DOCUMENT_SUFFIXES,
    EXTENSIONLESS_GUIDES,
    policy_links,
)
from .policy_links import (
    _destination as _link_destination,
)
from .policy_links import (
    _tail as _link_tail,
)
from .text import prose, without_emphasis

REPOSITORY = r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"
TARGET = re.compile(rf"(?P<repo>{REPOSITORY})#(?P<number>[1-9][0-9]*)\Z")
URL_TARGET = re.compile(
    rf"https://github\.com/(?P<repo>{REPOSITORY})/issues/(?P<number>[1-9][0-9]*)/?\Z"
)
MAINTAINERS = {"OWNER", "MEMBER", "COLLABORATOR"}
POLICY_PATHS = ("CONTRIBUTING.md", ".github/CONTRIBUTING.md", "AGENTS.md")
POLICY_FALLBACK_PATHS = ("docs/contributing.md", "docs/contributing.rst")


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


def _has_policy_text(text: str) -> bool:
    return bool(text.removeprefix("\ufeff").strip())


def _contribution_guide_path(path: str) -> bool:
    basename = path.rsplit("/", 1)[-1].casefold()
    if "." in basename:
        name, suffix = basename.rsplit(".", 1)
        return name in EXTENSIONLESS_GUIDES and suffix in DOCUMENT_SUFFIXES
    return basename in EXTENSIONLESS_GUIDES


def _blob_sha(raw: bytes) -> str:
    header = b"blob " + str(len(raw)).encode() + b"\0"
    return hashlib.sha1(header + raw, usedforsecurity=False).hexdigest()


def _policy_bytes(result: dict, limit: int) -> bytes:
    size = result.get("size")
    if (
        result.get("encoding") != "base64"
        or not isinstance(size, int)
        or isinstance(size, bool)
        or not 0 <= size <= limit
        or not isinstance(result.get("content"), str)
    ):
        raise ValueError("Unsupported policy payload.")
    raw = base64.b64decode("".join(result["content"].split()), validate=True)
    if len(raw) != size:
        raise ValueError("Policy size does not match its bytes.")
    return raw


def _policy_target(path: str, raw: bytes) -> str | None:
    # Git link targets are literal filesystem paths, not Markdown destinations.
    target = raw.decode("utf-8")
    if (
        not target
        or target.startswith("/")
        or ":" in target
        or "\\" in target
        or any(ord(char) < 32 or ord(char) == 127 for char in target)
    ):
        return None
    parts = path.split("/")[:-1]
    for part in target.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(part)
    if not parts or target.endswith("/"):
        return None
    name = parts[-1].casefold()
    if name.rsplit(".", 1)[-1] not in DOCUMENT_SUFFIXES and name not in EXTENSIONLESS_GUIDES:
        return None
    return "/".join(parts)


def _policy_documents(api: API, repo: str, sha: str, omissions: list[str]) -> list[dict]:
    documents: list[dict] = []
    queue: list[str] = []
    probes = list(POLICY_PATHS)
    fallbacks = list(POLICY_FALLBACK_PATHS)
    states: dict[str, str] = {}
    explicit: set[str] = set()
    loaded: dict[str, tuple[str, bytes, bool]] = {}
    blobs: dict[str, bytes | None] = {}
    published: set[str] = set()
    guide_found = False

    def missing_link(path: str) -> None:
        gap = f"Linked policy not found or inaccessible: {path}"
        if gap not in omissions:
            omissions.append(gap)

    def load(path: str, trail: tuple[str, ...] = ()) -> tuple[str, bytes, bool] | None:
        if path in trail:
            omissions.append(f"Policy source redirect cycle: {path}")
            return None
        if path in states:
            return loaded.get(path)
        if len(states) == 6:
            omissions.append(f"Policy source verification capped at six file requests: {path}")
            return None
        states[path] = "failed"  # Failed and missing contents requests also consume the budget.
        try:
            result = api.get(f"repos/{repo}/contents/{quote(path)}?ref={sha}")
        except NotFound:
            states[path] = "missing"
            if path in explicit:
                missing_link(path)
            return None
        except GitHubError:
            omissions.append(f"Could not read policy: {path}")
            return None
        if not isinstance(result, dict):
            omissions.append(f"Policy did not return a supported text file: {path}")
            return None
        identity = result.get("sha")
        if (
            result.get("path") != path
            or result.get("type") not in ("file", "symlink")
            or not isinstance(identity, str)
            or re.fullmatch(r"[0-9a-f]{40}", identity) is None
        ):
            omissions.append(f"Could not verify policy source metadata: {path}")
            return None
        raw = None
        if result["type"] == "file":
            try:
                raw = _policy_bytes(result, 80000)
                raw.decode("utf-8")
            except (ValueError, UnicodeError):
                omissions.append(f"Could not decode or verify policy bytes (80 KB limit): {path}")
                return None
            if _blob_sha(raw) == identity:
                states[path] = "fetched"
                loaded[path] = (path, raw, _contribution_guide_path(path))
                return loaded[path]
        # Contents can return a link target's body with the link's own blob SHA.
        # Verify the original blob before using any candidate target path.
        if identity not in blobs:
            blobs[identity] = None
            try:
                blob = api.get(f"repos/{repo}/git/blobs/{identity}")
                if not isinstance(blob, dict) or blob.get("sha") != identity:
                    raise ValueError("Invalid blob identity.")
                link_raw = _policy_bytes(blob, 4096)
                if _blob_sha(link_raw) != identity:
                    raise ValueError("Blob bytes do not match their identity.")
                blobs[identity] = link_raw
            except (GitHubError, ValueError):
                pass
        try:
            target = _policy_target(path, blobs[identity]) if blobs[identity] is not None else None
        except UnicodeError:
            target = None
        if target is None:
            omissions.append(f"Could not verify a same-repository policy source target: {path}")
            return None
        explicit.add(target)
        if states.get(target) == "missing":
            missing_link(target)
        document = load(target, (*trail, path))
        if document is None:
            omissions.append(f"Could not verify redirected policy source: {path}")
            return None
        canonical, canonical_raw, guide = document
        if raw is not None and raw != canonical_raw:
            omissions.append(f"Policy source contents disagree with the verified target: {path}")
            return None
        states[path] = "fetched"
        loaded[path] = (canonical, canonical_raw, guide or _contribution_guide_path(path))
        return loaded[path]

    while True:
        path = None
        # Explicit evidence precedes filename guesses, even for a queued probe.
        for candidates in (queue, probes, fallbacks if not guide_found else []):
            while (
                candidates
                and candidates[0] in states
                and (candidates[0] not in loaded or loaded[candidates[0]][0] in published)
            ):
                candidates.pop(0)
            if candidates:
                if len(states) == 6:
                    # A separately linked verified target can still be reported
                    # after an earlier alias conflicted, without another GET.
                    path = next(
                        (p for p in candidates if p in loaded and loaded[p][0] not in published),
                        None,
                    )
                    if path is None:
                        continue
                    candidates.remove(path)
                else:
                    path = candidates.pop(0)
                break
        if path is None:
            break
        document = load(path)
        if document is None:
            continue
        path, raw, guide = document
        text = raw.decode("utf-8")
        if _has_policy_text(text) and guide:
            guide_found = True
        if path in published:
            continue
        published.add(path)
        documents.append(
            dict(path=path, text=text, url=f"https://github.com/{repo}/blob/{sha}/{quote(path)}")
        )
        if path.casefold().endswith(".rst") and _has_policy_text(text):
            omissions.append(
                "RST policy formatting is not supported by automated rule detection; "
                f"review source: {path}"
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
    elif any(path not in states for path in probes) or (
        not guide_found and any(path not in states for path in fallbacks)
    ):
        omissions.append("Policy discovery capped at six file requests.")
    return documents


def _assignment_exceptions(original: str, visible: str) -> set[str]:
    """Recognize a quoted welcome label only beside a visible assignment exemption."""
    quoted = list(re.finditer(r"([`\"'])(help wanted|prs welcome)\1", original, re.I))
    masked = list(visible)
    spans = []
    for match in quoted:
        start = match.start()
        escape_start = start
        while escape_start and original[escape_start - 1] == "\\":
            escape_start -= 1
        if (start - escape_start) % 2:
            continue
        # Restore only the label token. Comments/examples retain masked context;
        # genuine inline-code labels can be matched without exposing their examples.
        masked[start : match.end()] = original[start : match.end()]
        spans.append(match)
    text = "".join(masked)
    exceptions = set()
    for index, match in enumerate(spans):
        before_start = max(0, match.start() - 240)
        if index:
            before_start = max(before_start, spans[index - 1].end())
        before = text[before_start : match.start()]
        before = re.split(r"\x00|\r?\n[ \t]*\r?\n", before)[-1]
        after_start = match.end()
        # Reuse the existing one-line link grammar within a bounded context so
        # URL dots/semicolons cannot be mistaken for prose clause boundaries.
        link_tail = original[after_start : after_start + 320]
        if link_tail.startswith("]("):
            destination = _link_destination(link_tail, 2)
            end = _link_tail(link_tail, destination[1], inline=True) if destination else None
            if end is not None:
                after_start += end
        after_end = match.end() + 320
        if index + 1 < len(spans):
            after_end = min(after_end, spans[index + 1].start())
        after = text[after_start:after_end]
        after = re.split(r"\x00|\r?\n[ \t]*\r?\n", after)[0]
        line_start = original.rfind("\n", max(0, match.start() - 240), match.start()) + 1
        table = match.start() - line_start <= 240 and re.fullmatch(
            r"[ \t]*\|[ \t]*(?:[*_]{1,2})?\[?", original[line_start : match.start()]
        )
        if table:
            after = re.split(r"[\r\n]", after)[0]  # Other table rows describe other labels.
        if re.search(
            r"\b(?:still\s+(?:needs?|requires?)\s+assignment|"
            r"does\s+not\s+(?:waive|mean)|not\s+an?\s+exception|not\s+exempt)\b",
            after,
            re.I,
        ):
            continue
        unless = re.search(
            r"(?:^|[.!?]\s*)\s*(?:the\s+)?author\s+must\s+(?:also\s+)?be\s+assigned\b"
            r"\s*,?\s*unless\s+(?:it|(?:(?:the|that|this)\s+)?issue)\s+"
            r"(?:has|carries)\s+(?:the\s+)?(?:[*_]{1,2})?\[?\s*$",
            before,
            re.I,
        )
        unless_tail = re.fullmatch(r"(?:[*_]{1,2})?(?:\s+label)?[.!]?\s*", after, re.I)
        permission = re.fullmatch(
            r"\s+(?:label\s+)?\(which\s+means\s+we['’]d\s+welcome\s+a\s+"
            r"(?:PR|pull\s+request)\s+for\s+it\s+from\s+anyone\)[.!]?\s*",
            after,
            re.I,
        )
        alternative = re.search(
            r"(?:^|[.!?]\s*)\s*(?:a|the)\s+maintainer\s+has\s+assigned\s+"
            r"(?:that|the|this)\s+issue\s+"
            r"to\s+you\s*,\s*or\s+(?:the|that|this)\s+issue\s+"
            r"(?:has|carries)\s+(?:the\s+)?(?:[*_]{1,2})?\[?\s*$",
            before,
            re.I,
        )
        no_assignment = re.fullmatch(
            r"\s+(?:label\s+)?means\s+no\s+assignment\s+(?:is\s+)?(?:needed|required)[.!]?\s*",
            after,
            re.I,
        )
        label_definition = re.search(r"(?:^|[.!?]\s*)\s*(?:the\s+)?$", before, re.I)
        cell = re.fullmatch(r"[ \t]*\|([^|\r\n]*)\|[ \t]*", after) if table else None
        table_permission = cell and re.fullmatch(
            r"\s*we['’]d\s+welcome\s+a\s+(?:PR|pull\s+request)\s+for\s+(?:this|it)\s+"
            r"from\s+anyone\s*[—–-]\s*no\s+assignment\s+(?:is\s+)?(?:needed|required)[.!]?\s*",
            cell[1],
            re.I,
        )
        direct_cell = cell and re.fullmatch(
            r"\s*no\s+assignment\s+(?:is\s+)?(?:needed|required)[.!]?\s*", cell[1], re.I
        )
        if (
            (unless and unless_tail)
            or (alternative and permission)
            or (label_definition and no_assignment)
            or table_permission
            or direct_cell
        ):
            exceptions.add(match[2].lower())
    return exceptions


def _policy_findings(documents: list[dict], assigned: bool, labels: set[str]) -> list[dict]:
    findings = []
    for doc in documents:
        if doc["path"].casefold().endswith(".rst"):
            continue  # Preserve the source and format gap rather than parse RST as Markdown.
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
            exceptions = _assignment_exceptions(doc["text"], text)
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
        # Allow soft wrapping and coordinated review actions, not unrelated clauses.
        soft_space = r"[ \t]*(?:\r?\n[ \t]*)?"
        review_action = r"(?:tested|understood|checked|approved)\b"
        human_rule = re.search(
            r"(?:\bhuman\b(?![-\u2010-\u2015]like\b)[^\x00\r\n]{0,20}(?:loop|review)|"
            r"(?:unreviewed|undisclosed) AI|"
            rf"\breview(?:ed)?\b(?:{soft_space},{soft_space}{review_action}){{0,2}}"
            rf"(?:{soft_space}(?:,{soft_space})?and\b{soft_space}{review_action})?"
            rf"{soft_space}\bby\b{soft_space}(?:a\b{soft_space})?human\b(?![-\u2010-\u2015]))",
            without_emphasis(text),
            re.I,
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


def _repository_access(
    api: API, repo: str, metadata: dict, actor: str | None, omissions: list[str]
) -> tuple[dict, list[dict]]:
    """Keep live PR settings separate from pinned guides and bind viewer permissions."""
    source = f"https://api.github.com/repos/{repo}"
    enabled = metadata.get("has_pull_requests")
    policy = metadata.get("pull_request_creation_policy")
    permissions = metadata.get("permissions")
    push = permissions.get("push") if isinstance(permissions, dict) else None
    access = dict(
        source=source,
        has_pull_requests=enabled,
        pull_request_creation_policy=policy,
        permissions_push=push,
        authenticated_user=None,
        identity_source=None,
        actor_write_access=None,
    )
    findings = []
    if enabled is False:
        findings.append(
            _finding(
                "pull_requests_disabled",
                "blocker",
                "Repository has disabled pull requests.",
                source,
                "has_pull_requests: false",
            )
        )
        return access, findings
    unknown_settings = False
    if type(enabled) is not bool:
        unknown_settings = True
        omissions.append("Repository PR-enabled setting is missing or not a boolean.")
    if policy not in ("all", "collaborators_only"):
        unknown_settings = True
        omissions.append("Repository PR creation policy is missing or unrecognized.")
    if unknown_settings:
        findings.append(
            _finding(
                "unknown_pull_request_access",
                "review",
                "Some repository PR settings are unknown. Check the reported API fields.",
                source,
            )
        )
    if policy != "collaborators_only":
        return access, findings
    if type(push) is bool and isinstance(actor, str) and actor:
        access["identity_source"] = "https://api.github.com/user"
        try:
            user = api.get("user")
        except GitHubError:
            omissions.append("Authenticated identity lookup failed for repository PR access.")
        else:
            login = user.get("login") if isinstance(user, dict) else None
            if (
                isinstance(login, str)
                and login
                and not any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in login)
            ):
                access["authenticated_user"] = login
                if login.casefold() == actor.casefold():
                    access["actor_write_access"] = push
    if access["actor_write_access"] is True:
        return access, findings
    if access["actor_write_access"] is False:
        severity = "blocker"
        message = (
            "Repository restricts PR creation to users with write access. "
            "The authenticated contributor lacks the required write access."
        )
    else:
        severity = "review"
        message = (
            "Repository restricts PR creation to users with write access; "
            "that access was not verified for the evaluated contributor."
        )
        omissions.append(
            "Required repository write access was not verified for the evaluated contributor."
        )
    findings.append(
        _finding(
            "restricted_pull_requests",
            severity,
            message,
            source,
            "pull_request_creation_policy: collaborators_only",
        )
    )
    return access, findings


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
    access, access_findings = _repository_access(api, repo, metadata, actor, omissions)
    findings.extend(access_findings)
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
    candidate_keys: dict[tuple[str, int], tuple[str, int]] = {}

    def add_candidate(pr_repo: str, pr_number: int, origin: str) -> None:
        # GitHub repository names are case-insensitive; retain the first URL spelling.
        key = candidate_keys.setdefault((pr_repo.casefold(), pr_number), (pr_repo, pr_number))
        candidates.setdefault(key, set()).add(origin)

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
                add_candidate(match[1], int(match[2]), "timeline")
    # Comments sometimes identify an earlier fix which never linked this issue directly.
    for item in [issue, *comments]:
        for match in re.finditer(
            rf"https://github\.com/({REPOSITORY})/pull/([1-9][0-9]*)(?![0-9])",
            str(item.get("body") or ""),
        ):
            add_candidate(match[1], int(match[2]), "discussion")
    query = urlencode({"q": f'repo:{repo} is:pr "#{number}"', "per_page": 100})
    try:
        search = api.get(f"search/issues?{query}")
    except GitHubError:
        omissions.append("Could not search for pull requests.")
        search = {}
    if search.get("incomplete_results") or search.get("total_count", 0) > 100:
        omissions.append("PR search returned partial results.")
    for item in search.get("items", []):
        add_candidate(repo, item["number"], "search")
    if len(candidates) > max_prs:
        omissions.append(f"PR details capped at {max_prs} of {len(candidates)} candidates.")
    # Stable priority keeps target-repository candidates within the bounded detail budget.
    ordered_candidates = sorted(
        candidates.items(), key=lambda item: item[0][0].casefold() != repo.casefold()
    )
    prs = []
    for (pr_repo, pr_number), origins in ordered_candidates[:max_prs]:
        try:
            pr = api.get(f"repos/{pr_repo}/pulls/{pr_number}")
        except GitHubError:
            omissions.append(f"Could not read PR: {pr_repo}#{pr_number}")
            continue
        closing_match = _closing_reference(pr, repo, number)
        closing = closing_match is not None
        state = "merged" if pr.get("merged") else pr["state"]
        base_repo = ((pr.get("base") or {}).get("repo") or {}).get("full_name") or pr_repo
        prs.append(
            dict(
                repository=base_repo,
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
        elif not closing and base_repo.casefold() != repo.casefold():
            findings.append(
                _finding(
                    "related_pr",
                    "review",
                    f"PR {base_repo}#{pr_number} from another repository is mentioned or linked; "
                    "its implementation relevance is not established.",
                    pr["html_url"],
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
    if not any(_has_policy_text(doc["text"]) for doc in documents):
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
        repository_access=access,
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
