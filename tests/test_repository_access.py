"""Repository PR settings are eligibility evidence, not contributor approval."""

from __future__ import annotations

import base64
import copy
import json
import re

import pytest

from issue_preflight import cli
from issue_preflight.core import inspect
from issue_preflight.github import GitHubError, NotFound
from issue_preflight.scan import scan

REPOSITORY = "example/project"
SOURCE = f"https://api.github.com/repos/{REPOSITORY}"
USER_SOURCE = "https://api.github.com/user"
COMMIT = "a" * 40
ABSENT = object()


class RepositoryAPI:
    """An entirely local API, with independent settings and authenticated identity."""

    def __init__(
        self,
        *,
        has_pull_requests=True,
        creation_policy="all",
        permissions=ABSENT,
        user=ABSENT,
        policy="Small bug fixes are welcome.",
    ):
        self.metadata = {
            "full_name": REPOSITORY,
            "default_branch": "main",
            "archived": False,
        }
        if has_pull_requests is not ABSENT:
            self.metadata["has_pull_requests"] = has_pull_requests
        if creation_policy is not ABSENT:
            self.metadata["pull_request_creation_policy"] = creation_policy
        if permissions is not ABSENT:
            self.metadata["permissions"] = permissions
        self.user = {"login": "Contributor"} if user is ABSENT else user
        self.policy = policy
        self.calls = []
        self.writes = []
        self.issues = {
            number: {
                "number": number,
                "title": f"Functional bug {number}",
                "body": "An isolated functional bug with a reproducible example.",
                "html_url": f"https://github.com/{REPOSITORY}/issues/{number}",
                "state": "open",
                "assignees": [],
                "labels": [],
            }
            for number in (42, 43)
        }

    def get(self, endpoint):
        self.calls.append(endpoint)
        path = endpoint.partition("?")[0]
        if path == "user":
            if isinstance(self.user, GitHubError):
                raise self.user
            return copy.deepcopy(self.user)
        if path == f"repos/{REPOSITORY}":
            return copy.deepcopy(self.metadata)
        if path == f"repos/{REPOSITORY}/issues":
            return copy.deepcopy(list(self.issues.values()))
        issue = re.fullmatch(rf"repos/{REPOSITORY}/issues/(42|43)", path)
        if issue:
            return copy.deepcopy(self.issues[int(issue[1])])
        if re.fullmatch(rf"repos/{REPOSITORY}/issues/(42|43)/(comments|timeline)", path):
            return []
        if path == "search/issues":
            return {"items": [], "total_count": 0, "incomplete_results": False}
        if path == f"repos/{REPOSITORY}/commits/main":
            return {"sha": COMMIT}
        if path == f"repos/{REPOSITORY}/contents/CONTRIBUTING.md":
            assert endpoint.endswith(f"?ref={COMMIT}")
            return {
                "type": "file",
                "encoding": "base64",
                "size": len(self.policy.encode()),
                "content": base64.b64encode(self.policy.encode()).decode(),
            }
        if path.startswith(f"repos/{REPOSITORY}/contents/"):
            raise NotFound()
        raise AssertionError(f"Unexpected API GET: {endpoint}")

    def _write(self, *args, **kwargs):
        self.writes.append((args, kwargs))
        raise AssertionError("Eligibility inspection must not write to GitHub")

    post = patch = put = delete = _write


def evaluate(api, actor="Contributor"):
    return inspect(api, f"{REPOSITORY}#42", actor=actor)


def access(report):
    evidence = report["repository_access"]
    assert evidence["source"] == SOURCE
    return evidence


def assert_raw(actual, expected):
    expected = None if expected is ABSENT else expected
    # False, 0, and null must remain distinguishable in the machine-readable evidence.
    assert json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True)


def assert_review_gap(report):
    assert report["decision"] == "review"
    assert report["collection_gaps"]
    assert any(finding["code"] == "incomplete_evidence" for finding in report["findings"])


@pytest.mark.parametrize("policy", ["all", "collaborators_only", "future_policy"])
def test_disabled_pull_requests_are_a_blocker_without_identity_lookup(policy):
    api = RepositoryAPI(
        has_pull_requests=False,
        creation_policy=policy,
        permissions={"push": True},
    )
    report = evaluate(api)
    assert report["decision"] == "hold"
    evidence = access(report)
    assert evidence["has_pull_requests"] is False
    assert evidence["pull_request_creation_policy"] == policy
    assert evidence["permissions_push"] is True
    assert evidence["actor_write_access"] is None
    assert evidence["authenticated_user"] is None
    assert evidence["identity_source"] is None
    assert api.calls.count("user") == 0


@pytest.mark.parametrize("raw", [ABSENT, None, 0, 1, "false", [], {}])
def test_unknown_pull_request_switch_is_review_with_raw_evidence(raw):
    api = RepositoryAPI(has_pull_requests=raw)
    report = evaluate(api)
    assert_review_gap(report)
    assert_raw(access(report)["has_pull_requests"], raw)


@pytest.mark.parametrize("raw", [ABSENT, None, "", True, 0, "future_policy", [], {}])
def test_unknown_creation_policy_is_review_with_raw_evidence(raw):
    api = RepositoryAPI(creation_policy=raw)
    report = evaluate(api)
    assert_review_gap(report)
    assert_raw(access(report)["pull_request_creation_policy"], raw)


@pytest.mark.parametrize("actor", ["Contributor", "Other", None])
def test_public_creation_does_not_require_authenticated_write_permission(actor):
    api = RepositoryAPI(permissions={"push": False}, user=GitHubError("denied"))
    report = evaluate(api, actor)
    assert report["decision"] == "no_obvious_blockers"
    evidence = access(report)
    assert evidence["has_pull_requests"] is True
    assert evidence["pull_request_creation_policy"] == "all"
    assert evidence["permissions_push"] is False
    assert evidence["actor_write_access"] is None
    assert evidence["identity_source"] is None
    assert api.calls.count("user") == 0


@pytest.mark.parametrize("push,decision", [(False, "hold"), (True, "no_obvious_blockers")])
def test_restricted_creation_binds_permission_to_matching_identity(push, decision):
    api = RepositoryAPI(creation_policy="collaborators_only", permissions={"push": push})
    report = evaluate(api, actor="cONtRibUTOR")
    assert report["decision"] == decision
    evidence = access(report)
    assert evidence["permissions_push"] is push
    assert evidence["authenticated_user"] == "Contributor"
    assert evidence["actor_write_access"] is push
    assert evidence["identity_source"] == USER_SOURCE
    assert not report["collection_gaps"]
    assert api.calls.count("user") == 1


@pytest.mark.parametrize("push", [True, False])
def test_actor_override_cannot_borrow_another_users_permission(push):
    api = RepositoryAPI(creation_policy="collaborators_only", permissions={"push": push})
    report = evaluate(api, actor="Other")
    assert_review_gap(report)
    evidence = access(report)
    assert evidence["permissions_push"] is push
    assert evidence["authenticated_user"] == "Contributor"
    assert evidence["actor_write_access"] is None
    assert evidence["identity_source"] == USER_SOURCE
    assert api.calls.count("user") == 1


@pytest.mark.parametrize("actor", [None, ""])
def test_restricted_creation_without_actor_is_review_without_identity_lookup(actor):
    api = RepositoryAPI(creation_policy="collaborators_only", permissions={"push": True})
    report = evaluate(api, actor)
    assert_review_gap(report)
    evidence = access(report)
    assert evidence["actor_write_access"] is None
    assert evidence["authenticated_user"] is None
    assert evidence["identity_source"] is None
    assert api.calls.count("user") == 0


@pytest.mark.parametrize(
    "permissions",
    [ABSENT, None, [], True, {}, {"push": None}, {"push": 0}, {"push": 1}, {"push": "true"}],
)
def test_missing_or_nonboolean_write_permission_is_review_without_identity_lookup(permissions):
    api = RepositoryAPI(creation_policy="collaborators_only", permissions=permissions)
    report = evaluate(api)
    assert_review_gap(report)
    evidence = access(report)
    raw_push = permissions.get("push") if isinstance(permissions, dict) else None
    assert_raw(evidence["permissions_push"], raw_push)
    assert evidence["actor_write_access"] is None
    assert evidence["identity_source"] is None
    assert api.calls.count("user") == 0


@pytest.mark.parametrize(
    "user",
    [None, [], "Contributor", {}, {"login": None}, {"login": 7}, {"login": ""}, {"login": " "}],
)
def test_unusable_authenticated_identity_is_review_without_borrowing_permission(user):
    api = RepositoryAPI(creation_policy="collaborators_only", permissions={"push": True}, user=user)
    report = evaluate(api)
    assert_review_gap(report)
    evidence = access(report)
    assert evidence["permissions_push"] is True
    assert evidence["authenticated_user"] is None
    assert evidence["actor_write_access"] is None
    assert evidence["identity_source"] == USER_SOURCE
    assert api.calls.count("user") == 1


@pytest.mark.parametrize("error", [GitHubError("identity denied"), NotFound()])
def test_identity_request_failure_keeps_a_review_report(error):
    api = RepositoryAPI(
        creation_policy="collaborators_only", permissions={"push": True}, user=error
    )
    report = evaluate(api)
    assert_review_gap(report)
    evidence = access(report)
    assert evidence["authenticated_user"] is None
    assert evidence["actor_write_access"] is None
    assert evidence["identity_source"] == USER_SOURCE


@pytest.mark.parametrize(
    "policy,code",
    [
        ("The author must be assigned.", "assignment_policy"),
        (
            "Agents opening pull requests autonomously are not allowed.",
            "autonomous_agent_policy",
        ),
    ],
)
def test_verified_write_permission_does_not_remove_contribution_blockers(policy, code):
    api = RepositoryAPI(
        creation_policy="collaborators_only", permissions={"push": True}, policy=policy
    )
    report = evaluate(api)
    assert report["decision"] == "hold"
    policy_finding = next(f for f in report["findings"] if f["code"] == code)
    assert policy_finding["severity"] == "blocker"
    assert policy_finding["excerpt"] == policy
    assert f"/{COMMIT}/CONTRIBUTING.md#L1" in policy_finding["url"]
    assert access(report)["actor_write_access"] is True


def run_cli(monkeypatch, tmp_path, api, *, actor="Contributor", strict="--fail-on-review"):
    monkeypatch.setattr(cli, "GitHub", lambda: api)
    output = tmp_path / "eligibility.json"
    args = [f"{REPOSITORY}#42", "--format", "json", "--output", str(output), strict]
    if actor is not None:
        args += ["--actor", actor]
    status = cli.main(args)
    assert output.is_file(), "The complete report must still be written on strict gate failure"
    return status, json.loads(output.read_text())


@pytest.mark.parametrize(
    "settings,actor,decision",
    [
        ({"has_pull_requests": False}, "Contributor", "hold"),
        (
            {"creation_policy": "collaborators_only", "permissions": {"push": False}},
            "Contributor",
            "hold",
        ),
        ({"has_pull_requests": ABSENT}, "Contributor", "review"),
        ({"creation_policy": "future_policy"}, "Contributor", "review"),
        (
            {"creation_policy": "collaborators_only", "permissions": {"push": True}},
            "Other",
            "review",
        ),
    ],
)
def test_strict_cli_exits_two_and_writes_full_access_evidence(
    monkeypatch, tmp_path, settings, actor, decision
):
    api = RepositoryAPI(**settings)
    status, report = run_cli(monkeypatch, tmp_path, api, actor=actor)
    assert status == 2
    assert report["decision"] == decision
    assert access(report)["source"] == SOURCE
    assert not api.writes


def test_fail_on_hold_does_not_treat_unknown_access_as_a_known_blocker(monkeypatch, tmp_path):
    api = RepositoryAPI(creation_policy="future_policy")
    status, report = run_cli(monkeypatch, tmp_path, api, strict="--fail-on-hold")
    assert status == 0
    assert_review_gap(report)


def test_default_cli_actor_and_authenticated_permission_use_the_same_identity(
    monkeypatch, tmp_path
):
    api = RepositoryAPI(creation_policy="collaborators_only", permissions={"push": False})
    status, report = run_cli(monkeypatch, tmp_path, api, actor=None)
    assert status == 2
    assert report["actor"] == "Contributor"
    assert report["decision"] == "hold"
    assert access(report)["actor_write_access"] is False
    assert 1 <= api.calls.count("user") <= 2


@pytest.mark.parametrize(
    "settings,raw_values",
    [
        ({"has_pull_requests": False}, ("False", "all")),
        ({"creation_policy": "future_policy"}, ("True", "future_policy")),
        (
            {"creation_policy": "collaborators_only", "permissions": {"push": False}},
            ("True", "collaborators_only", "False"),
        ),
    ],
)
def test_markdown_shows_original_repository_settings_and_api_source(settings, raw_values):
    report = evaluate(RepositoryAPI(**settings))
    rendered = cli.markdown(report)
    assert SOURCE in rendered
    # Markdown may escape underscores while still displaying the original enum.
    visible = rendered.replace("\\", "")
    for value in raw_values:
        assert value.casefold() in visible.casefold()


@pytest.mark.parametrize("push,decision", [(True, "no_obvious_blockers"), (False, "hold")])
def test_batch_reuses_verified_identity_and_preserves_each_issue_access(push, decision):
    api = RepositoryAPI(creation_policy="collaborators_only", permissions={"push": push})
    batch = scan(api, REPOSITORY, actor="Contributor", limit=2)
    assert batch["summary"][decision] == 2
    assert batch["summary"]["errors"] == 0
    assert len(batch["results"]) == 2
    for result in batch["results"]:
        assert result["status"] == "inspected"
        assert result["report"]["decision"] == decision
        assert access(result["report"])["actor_write_access"] is push
    assert api.calls.count("user") == 1
    assert not api.writes


def test_disabled_repository_scan_blocks_all_issues_without_identity_lookup():
    api = RepositoryAPI(
        has_pull_requests=False,
        creation_policy="collaborators_only",
        permissions={"push": True},
    )
    batch = scan(api, REPOSITORY, actor="Contributor", limit=2)
    assert batch["summary"]["hold"] == 2
    assert api.calls.count("user") == 0
    assert SOURCE in cli.scan_markdown(batch)
    assert not api.writes


def test_scan_actor_override_never_uses_another_users_permission():
    api = RepositoryAPI(creation_policy="collaborators_only", permissions={"push": True})
    batch = scan(api, REPOSITORY, actor="Other", limit=2)
    assert batch["summary"]["review"] == 2
    for result in batch["results"]:
        assert_review_gap(result["report"])
        assert access(result["report"])["actor_write_access"] is None
    assert api.calls.count("user") == 1
    assert not api.writes


def test_strict_scan_writes_review_results_and_inherits_access_gate(monkeypatch, tmp_path):
    api = RepositoryAPI(creation_policy="future_policy")
    monkeypatch.setattr(cli, "GitHub", lambda: api)
    output = tmp_path / "scan.json"
    status = cli.main(
        [
            "scan",
            REPOSITORY,
            "--limit",
            "2",
            "--actor",
            "Contributor",
            "--format",
            "json",
            "--output",
            str(output),
            "--fail-on-review",
        ]
    )
    assert status == 2
    batch = json.loads(output.read_text())
    assert batch["summary"]["review"] == 2
    for result in batch["results"]:
        assert access(result["report"])["pull_request_creation_policy"] == "future_policy"
    assert not api.writes


def test_default_scan_actor_lookup_is_bounded_for_two_restricted_issues(monkeypatch, tmp_path):
    api = RepositoryAPI(creation_policy="collaborators_only", permissions={"push": True})
    monkeypatch.setattr(cli, "GitHub", lambda: api)
    output = tmp_path / "scan.json"
    assert (
        cli.main(["scan", REPOSITORY, "--limit", "2", "--format", "json", "--output", str(output)])
        == 0
    )
    batch = json.loads(output.read_text())
    assert batch["actor"] == "Contributor"
    assert batch["summary"]["no_obvious_blockers"] == 2
    for result in batch["results"]:
        assert access(result["report"])["actor_write_access"] is True
    assert 1 <= api.calls.count("user") <= 2
    assert not api.writes
