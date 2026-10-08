"""Contributor lookup and visible identity uncertainty shared by interfaces."""

from __future__ import annotations

from .github import GitHubError

IDENTITY_GAP = (
    "Could not identify the authenticated GitHub user; assignment eligibility is "
    "unknown. Use --actor YOUR_GITHUB_LOGIN to evaluate a specific contributor."
)


def resolve_actor(
    api, requested: str | None, *, blank_unknown: bool = False
) -> tuple[str | None, bool]:
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


def add_identity_gap(report: dict) -> None:
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
