"""Bounded repository issue selection and reuse of single-issue evidence."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from .core import API, inspect, parse_target
from .github import GitHubError

MAX_ISSUES = 10
MAX_PAGES = 2
PAGE_SIZE = 100


class _SharedAPI:
    """Reuse successful shared policy and identity requests only for this batch."""

    def __init__(self, api: API, requested: str, repository: str, metadata: dict):
        self.api = api
        self.repository = repository
        self.cache = {f"repos/{requested}": metadata, f"repos/{repository}": metadata}

    def get(self, endpoint: str):
        if endpoint in self.cache:
            return self.cache[endpoint]
        value = self.api.get(endpoint)
        if endpoint == "user" or endpoint.startswith(
            (f"repos/{self.repository}/commits/", f"repos/{self.repository}/contents/")
        ):
            self.cache[endpoint] = value
        return value


def summary(results: list[dict]) -> dict:
    counts = Counter(
        result["report"]["decision"] if result["status"] == "inspected" else "errors"
        for result in results
    )
    return {key: counts[key] for key in ("hold", "review", "no_obvious_blockers", "errors")}


def scan(
    api: API,
    repository: str,
    actor: str | None = None,
    limit: int = 5,
    max_prs: int = 8,
) -> dict:
    """Select current open issues, excluding PRs, without writing to GitHub.

    Selection stops after an extra issue proves the requested limit truncates
    the list. Exhaustion, page caps and API failures remain separate states.
    Required per-issue failures preserve successful reports from other issues.
    """
    requested, _ = parse_target(f"{repository}#1")
    if not 1 <= limit <= MAX_ISSUES:
        raise ValueError(f"limit must be between 1 and {MAX_ISSUES}.")
    if not 1 <= max_prs <= 20:
        raise ValueError("max_prs must be between 1 and 20.")
    metadata = api.get(f"repos/{requested}")
    if not isinstance(metadata, dict) or not isinstance(metadata.get("full_name"), str):
        raise GitHubError("GitHub returned invalid repository metadata.")
    repository, _ = parse_target(f"{metadata['full_name']}#1")
    shared = _SharedAPI(api, requested, repository, metadata)
    selected = []
    seen = set()
    listing_gaps = []
    listing_status = "page_limit"
    selection_truncated = None
    pages_fetched = 0
    entries_fetched = 0
    for page in range(1, MAX_PAGES + 1):
        endpoint = (
            f"repos/{repository}/issues?state=open&sort=updated&direction=desc"
            f"&per_page={PAGE_SIZE}&page={page}"
        )
        try:
            items = api.get(endpoint)
            if not isinstance(items, list):
                raise GitHubError("GitHub returned an invalid issue list.")
            pages_fetched += 1
            entries_fetched += len(items)
            for item in items:
                if not isinstance(item, dict):
                    raise GitHubError("GitHub returned an invalid issue list entry.")
                if "pull_request" in item:
                    continue
                number = item.get("number")
                if (
                    not isinstance(number, int)
                    or isinstance(number, bool)
                    or number < 1
                    or not isinstance(item.get("title"), str)
                ):
                    raise GitHubError("GitHub returned an invalid issue list entry.")
                if number in seen:
                    continue
                seen.add(number)
                if len(selected) == limit:
                    listing_status = "selection_limit"
                    selection_truncated = True
                    break
                selected.append(
                    dict(
                        number=number,
                        title=item["title"],
                        url=f"https://github.com/{repository}/issues/{number}",
                    )
                )
        except GitHubError as exc:
            listing_status = "error"
            listing_gaps.append(f"Could not collect a valid open-issue listing page {page}: {exc}")
            break
        if listing_status == "selection_limit":
            break
        if len(items) < PAGE_SIZE:
            listing_status = "exhausted"
            selection_truncated = False
            break
    if listing_status == "page_limit":
        listing_gaps.append(
            f"Issue listing capped at {MAX_PAGES * PAGE_SIZE} entries, including pull requests; "
            "additional open issues may remain outside the collected pages."
        )
    results = []
    for item in selected:
        try:
            report = inspect(shared, f"{repository}#{item['number']}", actor, max_prs)
        except (GitHubError, ValueError) as exc:
            results.append(
                dict(
                    status="error",
                    issue=item,
                    error=f"Could not inspect this issue: {exc} "
                    "Run the single-issue command to investigate.",
                )
            )
        else:
            results.append(dict(status="inspected", issue=item, report=report))
    return dict(
        schema="issue-preflight-scan/1",
        fetched_at=datetime.now(timezone.utc).isoformat(),
        repository=repository,
        actor=actor,
        limit=limit,
        max_prs=max_prs,
        order="updated descending (GitHub REST order)",
        pages_fetched=pages_fetched,
        entries_fetched=entries_fetched,
        listing_status=listing_status,
        selection_truncated=selection_truncated,
        listing_gaps=listing_gaps,
        identity_gaps=[],
        results=results,
        summary=summary(results),
        interpretation=(
            "Bounded issue selection and heuristic evidence review, not maintainer approval "
            "or a guarantee of complete discovery. Selection does not rank issue value."
        ),
    )
