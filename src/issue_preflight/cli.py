"""Command-line interface and Markdown reports."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from .core import inspect
from .github import GitHub, GitHubError


def _plain(value: str) -> str:
    value = re.sub(r"[\x00-\x1f\x7f]", " ", value)
    return re.sub(r"([\\`*_{}\[\]<>|])", r"\\\1", value)


def markdown(report: dict) -> str:
    issue = report["issue"]
    lines = [
        f"# {_plain(report['repository'])}#{issue['number']}",
        "",
        _plain(issue["title"]),
        "",
        f"Decision: **{report['decision']}**",
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check contribution evidence before implementing a GitHub issue."
    )
    parser.add_argument("target", help="OWNER/REPO#NUMBER or a GitHub issue URL")
    parser.add_argument("--actor", help="GitHub login to compare against issue assignees")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", type=Path, help="Write the report to a file")
    parser.add_argument("--max-prs", type=int, default=8, help="PR detail limit (1–20; default: 8)")
    parser.add_argument(
        "--fail-on-hold", action="store_true", help="Exit 2 when blockers are found"
    )
    args = parser.parse_args(argv)
    try:
        report = inspect(GitHub(), args.target, actor=args.actor, max_prs=args.max_prs)
        text = (
            json.dumps(report, ensure_ascii=False, indent=2) + "\n"
            if args.format == "json"
            else markdown(report)
        )
        if args.output:
            args.output.write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text)
    except (ValueError, GitHubError, OSError) as exc:
        print(f"issue-preflight: {exc}", file=sys.stderr)
        return 1
    return 2 if args.fail_on_hold and report["decision"] == "hold" else 0
