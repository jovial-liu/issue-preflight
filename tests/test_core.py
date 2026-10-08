from __future__ import annotations

import base64
from copy import deepcopy

import pytest

from issue_preflight.core import closes_issue, inspect, parse_target
from issue_preflight.github import GitHubError, NotFound

REPO = "example/project"
SHA = "a" * 40


class FixtureAPI:
    def __init__(self, policy: str = "Small bug fixes are welcome.") -> None:
        self.calls = []
        self.issue = {
            "number": 42,
            "title": "Preserve URL fragments",
            "html_url": f"https://github.com/{REPO}/issues/42",
            "state": "open",
            "assignees": [],
            "labels": [],
            "body": "",
            "author_association": "NONE",
        }
        self.policy = policy
        self.timeline = []
        self.comments = []
        self.prs = {}
        self.search = {"items": [], "total_count": 0, "incomplete_results": False}
        self.archived = False

    def get(self, endpoint: str):
        self.calls.append(endpoint)
        if endpoint == f"repos/{REPO}":
            return dict(full_name=REPO, default_branch="main", archived=self.archived)
        if endpoint == f"repos/{REPO}/issues/42":
            return deepcopy(self.issue)
        if "/comments?" in endpoint:
            return self.comments
        if "/timeline?" in endpoint:
            return self.timeline
        if endpoint.startswith("search/issues?"):
            return self.search
        if endpoint == f"repos/{REPO}/commits/main":
            return {"sha": SHA}
        if endpoint == f"repos/{REPO}/contents/CONTRIBUTING.md?ref={SHA}" and self.policy:
            return dict(
                encoding="base64",
                size=len(self.policy),
                content=base64.b64encode(self.policy.encode()).decode(),
            )
        if "/contents/" in endpoint:
            raise NotFound()
        if "/pulls/" in endpoint:
            return self.prs[int(endpoint.rsplit("/", 1)[1])]
        raise AssertionError(f"Unexpected request: {endpoint}")


def pr(number=51, state="open", body="Fixes #42", merged=False):
    return dict(
        number=number,
        state=state,
        body=body,
        merged=merged,
        title="Fix URL fragments",
        html_url=f"https://github.com/{REPO}/pull/{number}",
        base={"repo": {"full_name": REPO}},
    )


def link(number=51):
    return {
        "event": "cross-referenced",
        "source": {
            "issue": {
                "number": number,
                "html_url": f"https://github.com/{REPO}/pull/{number}",
                "pull_request": {},
            }
        },
    }


def codes(report):
    return {finding["code"] for finding in report["findings"]}


@pytest.mark.parametrize(
    "target", ["example/project#42", "https://github.com/example/project/issues/42/"]
)
def test_parse_target(target):
    assert parse_target(target) == (REPO, 42)


@pytest.mark.parametrize(
    "target",
    [
        "x/y#0",
        "x/y#42;echo boom",
        "../x#4",
        "x/..#4",
        "https://evil.test/x/y/issues/42",
        "x/y#42#43",
    ],
)
def test_reject_invalid_target(target):
    with pytest.raises(ValueError):
        parse_target(target)


@pytest.mark.parametrize(
    "body",
    [
        "Fixes #42",
        "Closes example/project#42",
        "Resolves https://github.com/example/project/issues/42",
    ],
)
def test_explicit_closing_reference(body):
    assert closes_issue(pr(body=body), REPO, 42)


@pytest.mark.parametrize(
    "body",
    [
        "Fixes #420",
        "Related to #42",
        "Fixes different/project#42",
        "```\nFixes #42\n```",
        "Example: `Fixes #42`",
    ],
)
def test_mentions_are_not_closing_references(body):
    assert not closes_issue(pr(body=body), REPO, 42)


def test_cross_repository_short_reference_does_not_close_target():
    candidate = pr()
    candidate["base"]["repo"]["full_name"] = "another/project"
    assert not closes_issue(candidate, REPO, 42)
    candidate["body"] = f"Fixes {REPO}#42"
    assert closes_issue(candidate, REPO, 42)


def test_no_obvious_blockers_is_a_bounded_snapshot():
    api = FixtureAPI()
    result = inspect(api, "example/project#42")
    assert result["decision"] == "no_obvious_blockers"
    assert result["policy_ref"] == SHA
    assert result["collection_gaps"] == []
    assert all(f"ref={SHA}" in call for call in api.calls if "/contents/" in call)


@pytest.mark.parametrize(("state", "merged"), [("open", False), ("closed", True)])
def test_existing_fix_blocks_duplicate_work(state, merged):
    api = FixtureAPI()
    api.timeline = [link()]
    api.prs = {51: pr(state=state, merged=merged)}
    result = inspect(api, "example/project#42")
    assert result["decision"] == "hold"
    assert "existing_fix" in codes(result)


def test_closed_unmerged_pr_requires_discussion_review():
    api = FixtureAPI()
    api.timeline = [link()]
    api.prs = {51: pr(state="closed")}
    result = inspect(api, "example/project#42")
    assert result["decision"] == "review"
    assert "closed_related_pr" in codes(result)


def test_search_number_collision_does_not_claim_duplicate_fix():
    api = FixtureAPI()
    api.search["items"] = [{"number": 51}]
    api.prs = {51: pr(body="Fixes #420")}
    result = inspect(api, "example/project#42")
    assert "existing_fix" not in codes(result)
    assert not result["pull_requests"][0]["closes_issue"]


def test_discussion_finds_fix_for_a_different_issue_without_claiming_equivalence():
    api = FixtureAPI()
    api.comments = [{"body": "Earlier fix: https://github.com/example/project/pull/51"}]
    api.prs = {51: pr(body="Fixes #41")}
    result = inspect(api, "example/project#42")
    assert result["decision"] == "review"
    assert "related_pr" in codes(result)
    assert "existing_fix" not in codes(result)


def test_assignment_requirement_has_label_exception():
    api = FixtureAPI(
        "External PRs must link an issue. The author must be assigned, unless it has `prs welcome`."
    )
    assert inspect(api, "example/project#42")["decision"] == "hold"
    api.issue["labels"] = [{"name": "prs welcome"}]
    assert inspect(api, "example/project#42")["decision"] == "no_obvious_blockers"


def test_assignment_comparison_is_case_insensitive():
    api = FixtureAPI("The author must be assigned.")
    api.issue["assignees"] = [{"login": "Contributor"}]
    assert (
        inspect(api, "example/project#42", actor="CONTRIBUTOR")["decision"] == "no_obvious_blockers"
    )


def test_policy_that_welcomes_agents_is_not_a_prohibition():
    api = FixtureAPI("We welcome agents filing PRs autonomously.")
    assert "autonomous_agent_policy" not in codes(inspect(api, "example/project#42"))


def test_wrapped_policy_that_prohibits_autonomous_prs_is_detected():
    api = FixtureAPI(
        "If you have an agent filing PRs against open issues\nautonomously, please turn it off."
    )
    assert "autonomous_agent_policy" in codes(inspect(api, "example/project#42"))


def test_optional_assignment_is_not_a_requirement():
    api = FixtureAPI("The author must not be assigned. Anyone can open a PR.")
    assert "assignment_policy" not in codes(inspect(api, "example/project#42"))


def test_only_maintainer_stop_requests_are_blockers():
    api = FixtureAPI()
    api.comments = [{"body": "Please do not open another PR.", "author_association": "NONE"}]
    assert inspect(api, "example/project#42")["decision"] == "no_obvious_blockers"
    api.comments[0]["author_association"] = "MEMBER"
    assert "maintainer_stop" in codes(inspect(api, "example/project#42"))


def test_missing_policy_prevents_confident_result():
    assert inspect(FixtureAPI(policy=""), "example/project#42")["decision"] == "review"


def test_collection_cap_is_reported():
    api = FixtureAPI()
    api.comments = [{}] * 100
    result = inspect(api, "example/project#42")
    assert result["decision"] == "review"
    assert any("capped at 200" in gap for gap in result["collection_gaps"])


def test_pr_budget_gap_is_reported():
    api = FixtureAPI()
    api.timeline = [link(51), link(52)]
    api.prs = {51: pr(body="Related to #42")}
    result = inspect(api, "example/project#42", max_prs=1)
    assert any("1 of 2" in gap for gap in result["collection_gaps"])


def test_collection_permission_failure_is_partial_evidence():
    class DeniedAPI(FixtureAPI):
        def get(self, endpoint):
            if "/timeline?" in endpoint:
                raise GitHubError("denied")
            return super().get(endpoint)

    result = inspect(DeniedAPI(), "example/project#42")
    assert result["decision"] == "review"
    assert any("timeline" in gap for gap in result["collection_gaps"])


def test_closed_issue_and_archived_repository_are_blockers():
    api = FixtureAPI()
    api.issue["state"] = "closed"
    api.archived = True
    result = inspect(api, "example/project#42")
    assert {"closed_issue", "archived_repository"} <= codes(result)


def test_reject_pr_target_before_scanning():
    api = FixtureAPI()
    api.issue["pull_request"] = {}
    with pytest.raises(ValueError, match="pull request"):
        inspect(api, "example/project#42")


def test_local_policy_links_do_not_fetch_external_or_traversal_paths():
    api = FixtureAPI("[guide](https://evil.test/contributing.md) [other](../contributing.md)")
    inspect(api, "example/project#42")
    assert not any("evil" in call or ".." in call for call in api.calls)
