"""Command-line interface and Markdown reports."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from .core import inspect
from .github import GitHub, GitHubError
from .scan import scan, summary

IDENTITY_GAP = (
    "Could not identify the authenticated GitHub user; assignment eligibility is "
    "unknown. Use --actor YOUR_GITHUB_LOGIN to evaluate a specific contributor."
)


def _plain(value: str) -> str:
    value = re.sub(r"[\x00-\x1f\x7f]", " ", value)
    return re.sub(r"([\\`*_{}\[\]<>|])", r"\\\1", value)


def _excerpt_line(value: str) -> str:
    return re.sub(r"([!#()+.=\-])", r"\\\1", _plain(value)).rstrip()


def markdown(report: dict) -> str:
    issue = report["issue"]
    actor = report.get("actor")
    actor_description = (
        _plain(actor) if actor else "unknown; assignment eligibility could not be evaluated"
    )
    lines = [
        f"# {_plain(report['repository'])}#{issue['number']}",
        "",
        _plain(issue["title"]),
        "",
        f"Decision: **{report['decision']}**",
        "",
        f"Contributor evaluated: {actor_description}",
        "",
        f"[Issue]({issue['url']}) · Evidence collected: {report['fetched_at']}",
        "",
        report["interpretation"],
        "",
        "## Findings",
        "",
    ]
    for finding in report["findings"]:
        lines.append(
            f"- **{finding['severity']}**: {_plain(finding['message'])} "
            f"([source]({finding['url']}))"
        )
        if finding.get("excerpt"):
            lines.append("")
            lines.extend(
                f"  > {_excerpt_line(line)}".rstrip() for line in finding["excerpt"].split("\n")
            )
            if finding.get("excerpt_truncated"):
                lines.extend(["", "  Excerpt truncated; read the source for the full context."])
            lines.append("")
    if not report["findings"]:
        lines.append(
            "No obvious blockers in the collected evidence. Read the linked policies before acting."
        )
    lines.extend(["", "## Pull requests", ""])
    for pr in report["pull_requests"]:
        relationship = "closing reference" if pr["closes_issue"] else "candidate reference"
        lines.append(
            f"- [{_plain(pr['repository'])}#{pr['number']}]({pr['url']}): "
            f"{_plain(pr['title'])} ({pr['state']}; {relationship})"
        )
    if not report["pull_requests"]:
        lines.append(
            "No candidates discovered by this bounded scan. "
            "This does not prove no competing work exists."
        )
    lines.extend(
        ["", "## Contribution policies", "", f"Pinned commit: `{report['policy_ref']}`", ""]
    )
    for doc in report["policy_sources"]:
        lines.append(f"- [{_plain(doc['path'])}]({doc['url']})")
    if report["collection_gaps"]:
        lines.extend(["", "## Collection gaps", ""])
        lines.extend(f"- {_plain(gap)}" for gap in report["collection_gaps"])
    return "\n".join(lines) + "\n"


def scan_markdown(report: dict) -> str:
    actor = report.get("actor")
    actor_description = (
        _plain(actor) if actor else "unknown; assignment eligibility could not be evaluated"
    )
    lines = [
        f"# {_plain(report['repository'])} issue scan",
        "",
        report["interpretation"],
        "",
        f"Contributor evaluated: {actor_description}",
        "",
        f"Selected {len(report['results'])} issues; limit {report['limit']}; "
        f"order: {report['order']}.",
        f"Listing status: `{report['listing_status']}`; "
        f"{report['pages_fetched']} pages / {report['entries_fetched']} entries collected "
        "(including PRs).",
        "",
    ]
    if report["selection_truncated"] is True:
        lines.extend(
            [
                f"Selected the first {report['limit']} open issues. "
                "Additional open issues were not inspected.",
                "",
            ]
        )
    elif report["selection_truncated"] is None:
        lines.extend(["Whether more open issues remain is unknown. Read listing gaps.", ""])
    if report["listing_gaps"]:
        lines.extend(["## Listing gaps", ""])
        lines.extend(f"- {_plain(gap)}" for gap in report["listing_gaps"])
        lines.append("")
    if report["identity_gaps"]:
        lines.extend(["## Contributor lookup gaps", ""])
        lines.extend(f"- {_plain(gap)}" for gap in report["identity_gaps"])
        lines.append("")
    lines.extend(["| Issue | Result |", "| --- | --- |"])
    for result in report["results"]:
        item = result["issue"]
        decision = result["report"]["decision"] if result["status"] == "inspected" else "error"
        lines.append(f"| [#{item['number']}]({item['url']}) {_plain(item['title'])} | {decision} |")
    if not report["results"]:
        lines.extend(["", "No issues selected; this is not an approval result."])
    for result in report["results"]:
        lines.append("")
        if result["status"] == "inspected":
            lines.append(markdown(result["report"]).rstrip())
        else:
            lines.extend(
                [f"## Issue #{result['issue']['number']}: error", "", _plain(result["error"])]
            )
    return "\n".join(lines) + "\n"


def _actor(api, requested: str | None, *, blank_unknown: bool = False) -> tuple[str | None, bool]:
    if requested is not None:
        if blank_unknown and not requested.strip():
            return None, True
        return requested, False
    try:
        user = api.get("user")
        login = user.get("login") if isinstance(user, dict) else None
        if isinstance(login, str) and login.strip():
            return login, False
    except GitHubError:
        pass
    return None, True


def _identity_gap(report: dict) -> None:
    report["collection_gaps"].append(IDENTITY_GAP)
    if not any(f["code"] == "incomplete_evidence" for f in report["findings"]):
        report["findings"].append(
            dict(
                code="incomplete_evidence",
                severity="review",
                message="Some evidence was not collected. Review collection gaps.",
                url=report["issue"]["url"],
                excerpt="",
                excerpt_truncated=False,
            )
        )
    if report["decision"] != "hold":
        report["decision"] = "review"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    batch = bool(argv and argv[0] == "scan")
    parser = argparse.ArgumentParser(
        description="Check contribution evidence before implementing a GitHub issue.",
        epilog="Scan a repository: issue-preflight scan OWNER/REPO --limit 5",
    )
    if batch:
        parser.prog += " scan"
        parser.add_argument("target", help="OWNER/REPO whose open issues to inspect")
        parser.add_argument("--limit", type=int, default=5, help="Issue limit (1–10; default: 5)")
        argv = argv[1:]
    else:
        parser.add_argument("target", help="OWNER/REPO#NUMBER or a GitHub issue URL")
    parser.add_argument("--actor", help="GitHub login to evaluate (default: authenticated gh user)")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", type=Path, help="Write the report to a file")
    parser.add_argument("--max-prs", type=int, default=8, help="PR detail limit (1–20; default: 8)")
    parser.add_argument(
        "--fail-on-hold", action="store_true", help="Exit 2 when blockers are found"
    )
    parser.add_argument(
        "--fail-on-review",
        action="store_true",
        help=(
            "Exit 2 for hold, review, or incomplete selection"
            if batch
            else "Exit 2 for hold or review decisions"
        ),
    )
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        if batch and exc.code == 2:
            return 1  # Scan input errors are distinct from evidence-gate exit 2.
        raise
    try:
        api = GitHub()
        actor, identity_unknown = _actor(api, args.actor, blank_unknown=batch)
        if batch:
            report = scan(api, args.target, actor=actor, limit=args.limit, max_prs=args.max_prs)
            if identity_unknown:
                report["identity_gaps"].append(IDENTITY_GAP)
                for result in report["results"]:
                    if result["status"] == "inspected":
                        _identity_gap(result["report"])
                report["summary"] = summary(report["results"])
        else:
            report = inspect(api, args.target, actor=actor, max_prs=args.max_prs)
            if identity_unknown:
                _identity_gap(report)
        text = (
            json.dumps(report, ensure_ascii=False, indent=2) + "\n"
            if args.format == "json"
            else (scan_markdown(report) if batch else markdown(report))
        )
        if args.output:
            args.output.write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text)
    except (ValueError, GitHubError, OSError) as exc:
        print(f"issue-preflight: {exc}", file=sys.stderr)
        return 1
    if batch:
        if report["listing_status"] == "error" or report["summary"]["errors"]:
            return 1
        should_fail = (args.fail_on_hold and report["summary"]["hold"]) or (
            args.fail_on_review
            and (
                report["summary"]["hold"]
                or report["summary"]["review"]
                or report["selection_truncated"] is not False
                or report["listing_gaps"]
                or identity_unknown
            )
        )
        return 2 if should_fail else 0
    should_fail = (args.fail_on_hold and report["decision"] == "hold") or (
        args.fail_on_review and report["decision"] in {"hold", "review"}
    )
    return 2 if should_fail else 0
