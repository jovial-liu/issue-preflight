from __future__ import annotations

import json
from copy import deepcopy
from urllib.parse import parse_qs, urlsplit

import pytest
from policy_fixtures import file_response

from issue_preflight import cli
from issue_preflight.github import GitHubError, NotFound

REPO = "example/project"
SHA = "a" * 40


def issue(number: int, **kwargs):
    return dict(
        number=number,
        title=f"Issue {number}",
        html_url=f"https://github.com/{REPO}/issues/{number}",
        state="open",
        body="",
        author_association="NONE",
        assignees=[],
        labels=[],
        **kwargs,
    )


class ScanAPI:
    def __init__(self, pages=None):
        self.pages = pages or [[]]
        self.calls = []
        self.issues = {}
        self.fail_issue = None
        self.policy = "Small fixes are welcome."
        self.timeline = {}
        self.comments = {}
        self.user = {"login": "Contributor"}
        self.pr = None

    def get(self, endpoint):
        self.calls.append(endpoint)
        if endpoint == "user":
            if isinstance(self.user, GitHubError):
                raise self.user
            return self.user
        if endpoint == f"repos/{REPO}":
            return dict(
                full_name=REPO,
                default_branch="main",
                archived=False,
                has_pull_requests=True,
                pull_request_creation_policy="all",
            )
        if endpoint.startswith(f"repos/{REPO}/issues?"):
            params = parse_qs(urlsplit(endpoint).query)
            assert params["state"] == ["open"]
            assert params["sort"] == ["updated"]
            assert params["direction"] == ["desc"]
            assert params["per_page"] == ["100"]
            page = int(params["page"][0])
            value = self.pages[page - 1]
            if isinstance(value, GitHubError):
                raise value
            return deepcopy(value)
        if endpoint.startswith(f"repos/{REPO}/issues/"):
            path = urlsplit(endpoint).path.split("/")
            number = int(path[4])
            if len(path) == 5:
                if number == self.fail_issue:
                    raise GitHubError("Required GitHub API request failed.")
                return deepcopy(self.issues.get(number, issue(number)))
            if path[5] == "comments":
                return self.comments.get(number, [])
            if path[5] == "timeline":
                value = self.timeline.get(number, [])
                if isinstance(value, GitHubError):
                    raise value
                return value
        if endpoint.startswith("search/issues?"):
            return dict(items=[], total_count=0, incomplete_results=False)
        if endpoint == f"repos/{REPO}/commits/main":
            return {"sha": SHA}
        if endpoint == f"repos/{REPO}/contents/CONTRIBUTING.md?ref={SHA}":
            return file_response("CONTRIBUTING.md", self.policy)
        if "/contents/" in endpoint:
            raise NotFound()
        if "/pulls/" in endpoint:
            return self.pr
        raise AssertionError(f"Unexpected request: {endpoint}")


def run_scan(monkeypatch, capsys, api, *args):
    monkeypatch.setattr(cli, "GitHub", lambda: api)
    code = cli.main(["scan", REPO, "--actor", "Contributor", "--format", "json", *args])
    captured = capsys.readouterr()
    assert not captured.err
    return code, json.loads(captured.out)


def decisions(report):
    return [result["report"]["decision"] for result in report["results"] if "report" in result]


def test_scan_excludes_prs_preserves_order_and_complete_reports(monkeypatch, capsys):
    api = ScanAPI([[issue(8, pull_request={}), issue(7), issue(3)]])
    code, report = run_scan(monkeypatch, capsys, api)
    assert code == 0
    assert report["schema"] == "issue-preflight-scan/1"
    assert [result["issue"]["number"] for result in report["results"]] == [7, 3]
    assert decisions(report) == ["no_obvious_blockers"] * 2
    assert all(result["report"]["schema"] == "issue-preflight/1" for result in report["results"])
    assert all(result["report"]["policy_ref"] == SHA for result in report["results"])
    assert report["listing_status"] == "exhausted"
    assert report["selection_truncated"] is False
    assert not report["listing_gaps"]
    assert api.calls.count(f"repos/{REPO}") == 1
    assert api.calls.count(f"repos/{REPO}/commits/main") == 1
    assert api.calls.count(f"repos/{REPO}/contents/CONTRIBUTING.md?ref={SHA}") == 1
    assert not any(call.endswith("/issues/8") for call in api.calls)


def test_default_limit_has_visible_selection_without_collection_failure(monkeypatch, capsys):
    api = ScanAPI([[issue(n) for n in range(9, 2, -1)]])
    code, report = run_scan(monkeypatch, capsys, api)
    assert code == 0
    assert len(report["results"]) == 5
    assert report["selection_truncated"] is True
    assert report["listing_status"] == "selection_limit"
    assert report["listing_gaps"] == []
    assert report["summary"]["errors"] == 0
    assert not any(call.endswith("/issues/4") for call in api.calls)


def test_exact_limit_exhausted_is_not_truncated(monkeypatch, capsys):
    code, report = run_scan(monkeypatch, capsys, ScanAPI([[issue(1), issue(2)]]), "--limit", "2")
    assert code == 0
    assert report["selection_truncated"] is False
    assert report["listing_status"] == "exhausted"


def test_cross_page_prs_and_duplicate_issues_do_not_use_issue_budget(monkeypatch, capsys):
    api = ScanAPI([[issue(999, pull_request={})] * 99 + [issue(1)], [issue(1), issue(2)]])
    code, report = run_scan(monkeypatch, capsys, api)
    assert code == 0
    assert [r["issue"]["number"] for r in report["results"]] == [1, 2]
    assert report["pages_fetched"] == 2
    assert len([call for call in api.calls if call.endswith("/issues/1")]) == 1


def test_listing_page_cap_has_unknown_selection_and_review_exit(monkeypatch, capsys):
    api = ScanAPI([[issue(999, pull_request={})] * 100] * 2)
    code, report = run_scan(monkeypatch, capsys, api, "--fail-on-review")
    assert code == 2
    assert report["results"] == []
    assert report["listing_status"] == "page_limit"
    assert report["selection_truncated"] is None
    assert any("200" in gap for gap in report["listing_gaps"])
    assert report["pages_fetched"] == 2


@pytest.mark.parametrize("page", [GitHubError("denied"), {"message": "bad"}, [None]])
def test_first_page_failure_writes_error_report(monkeypatch, capsys, page):
    code, report = run_scan(monkeypatch, capsys, ScanAPI([page]))
    assert code == 1
    assert report["listing_status"] == "error"
    assert report["selection_truncated"] is None
    assert report["listing_gaps"]
    assert report["results"] == []


def test_failed_later_page_preserves_collected_issue(monkeypatch, capsys):
    api = ScanAPI([[issue(999, pull_request={})] * 99 + [issue(1)], GitHubError("denied")])
    code, report = run_scan(monkeypatch, capsys, api, "--fail-on-review")
    assert code == 1
    assert report["listing_status"] == "error"
    assert [r["issue"]["number"] for r in report["results"]] == [1]
    assert decisions(report) == ["no_obvious_blockers"]


def test_required_issue_failure_preserves_other_reports_and_precedes_gates(monkeypatch, capsys):
    api = ScanAPI([[issue(1), issue(2), issue(3)]])
    api.fail_issue = 2
    api.issues[1] = issue(1)
    api.issues[1]["state"] = "closed"
    code, report = run_scan(monkeypatch, capsys, api, "--fail-on-hold")
    assert code == 1
    assert decisions(report) == ["hold", "no_obvious_blockers"]
    assert report["results"][1]["status"] == "error"
    assert "report" not in report["results"][1]
    assert report["summary"]["errors"] == 1


def test_optional_failure_is_per_issue_review_not_api_failure(monkeypatch, capsys):
    api = ScanAPI([[issue(1), issue(2)]])
    api.timeline[1] = GitHubError("denied")
    code, report = run_scan(monkeypatch, capsys, api, "--fail-on-review")
    assert code == 2
    assert decisions(report) == ["review", "no_obvious_blockers"]
    assert report["results"][0]["report"]["collection_gaps"]
    assert report["listing_gaps"] == []


def test_zero_comments_still_find_timeline_fix(monkeypatch, capsys):
    api = ScanAPI([[issue(1)]])
    api.timeline[1] = [
        dict(
            event="cross-referenced",
            source=dict(issue=dict(html_url=f"https://github.com/{REPO}/pull/10", pull_request={})),
        )
    ]
    api.pr = dict(
        number=10,
        title="Fix issue",
        html_url=f"https://github.com/{REPO}/pull/10",
        body="Fixes #1",
        state="open",
        merged=False,
        base=dict(repo=dict(full_name=REPO)),
    )
    code, report = run_scan(monkeypatch, capsys, api, "--fail-on-hold")
    assert code == 2
    assert decisions(report) == ["hold"]
    assert report["results"][0]["report"]["findings"][0]["code"] == "existing_fix"


def test_policy_assignment_is_evaluated_for_each_issue(monkeypatch, capsys):
    api = ScanAPI([[issue(1), issue(2)]])
    api.policy = "The author must be assigned."
    api.issues[1] = issue(1)
    api.issues[1]["assignees"] = [{"login": "Contributor"}]
    code, report = run_scan(monkeypatch, capsys, api)
    assert code == 0
    assert decisions(report) == ["no_obvious_blockers", "hold"]


@pytest.mark.parametrize("user", [{}, GitHubError("denied")])
def test_unknown_actor_applies_to_every_issue_with_one_lookup(monkeypatch, capsys, user):
    api = ScanAPI([[issue(1), issue(2)]])
    api.user = user
    monkeypatch.setattr(cli, "GitHub", lambda: api)
    assert cli.main(["scan", REPO, "--format", "json", "--fail-on-review"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert decisions(report) == ["review", "review"]
    assert api.calls.count("user") == 1
    assert all(r["report"]["collection_gaps"] for r in report["results"])


def test_empty_repository_reports_empty_selection(monkeypatch, capsys):
    code, report = run_scan(monkeypatch, capsys, ScanAPI())
    assert code == 0
    assert report["listing_status"] == "exhausted"
    assert report["results"] == []
    assert report["summary"]["errors"] == 0


@pytest.mark.parametrize("limit", ["0", "11"])
def test_invalid_limit_fails_before_api_call(monkeypatch, capsys, limit):
    api = ScanAPI()
    monkeypatch.setattr(cli, "GitHub", lambda: api)
    assert cli.main(["scan", REPO, "--limit", limit, "--actor", "Contributor"]) == 1
    assert api.calls == []
    assert "between 1 and 10" in capsys.readouterr().err


def test_scan_markdown_output_written_before_review_exit(monkeypatch, tmp_path, capsys):
    api = ScanAPI([[issue(1), issue(2)]])
    monkeypatch.setattr(cli, "GitHub", lambda: api)
    output = tmp_path / "scan.md"
    assert (
        cli.main(
            [
                "scan",
                REPO,
                "--limit",
                "1",
                "--actor",
                "Contributor",
                "--output",
                str(output),
                "--fail-on-review",
            ]
        )
        == 2
    )
    assert capsys.readouterr().out == ""
    text = output.read_text(encoding="utf-8")
    assert "Selected the first 1" in text
    assert "# example/project#1" in text
    assert "not maintainer approval" in text


def test_page_cap_preserves_selected_report_without_claiming_extra_issue(monkeypatch, capsys):
    api = ScanAPI([[issue(1)] * 100, [issue(999, pull_request={})] * 100])
    code, report = run_scan(monkeypatch, capsys, api)
    assert code == 0
    assert report["listing_status"] == "page_limit"
    assert report["selection_truncated"] is None
    assert len(report["results"]) == 1
    assert decisions(report) == ["no_obvious_blockers"]


def test_invalid_later_entry_keeps_earlier_selected_issue(monkeypatch, capsys):
    code, report = run_scan(monkeypatch, capsys, ScanAPI([[issue(1), {"number": "2"}]]))
    assert code == 1
    assert len(report["results"]) == 1
    assert report["listing_status"] == "error"
    assert report["selection_truncated"] is None


def test_unknown_identity_is_visible_even_when_no_issue_selected(monkeypatch, capsys):
    api = ScanAPI()
    api.user = {}
    monkeypatch.setattr(cli, "GitHub", lambda: api)
    assert cli.main(["scan", REPO, "--format", "json", "--fail-on-review"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["identity_gaps"]
    assert report["results"] == []


def test_authenticated_identity_is_resolved_once(monkeypatch, capsys):
    api = ScanAPI([[issue(1), issue(2)]])
    monkeypatch.setattr(cli, "GitHub", lambda: api)
    assert cli.main(["scan", REPO, "--format", "json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["actor"] == "Contributor"
    assert report["identity_gaps"] == []
    assert api.calls.count("user") == 1


def test_repository_redirect_uses_canonical_listing_and_shared_metadata(monkeypatch, capsys):
    class RedirectAPI(ScanAPI):
        def get(self, endpoint):
            if endpoint == "repos/old/project":
                self.calls.append(endpoint)
                return dict(
                    full_name=REPO,
                    default_branch="main",
                    archived=False,
                    has_pull_requests=True,
                    pull_request_creation_policy="all",
                )
            return super().get(endpoint)

    api = RedirectAPI([[issue(1), issue(2)]])
    monkeypatch.setattr(cli, "GitHub", lambda: api)
    assert cli.main(["scan", "old/project", "--actor", "Contributor", "--format", "json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["repository"] == REPO
    assert api.calls.count("repos/old/project") == 1
    assert f"repos/{REPO}" not in api.calls


def test_scan_markdown_sanitizes_listing_title_and_shows_error(monkeypatch, capsys):
    item = issue(1)
    item["title"] = "| injected\n[link](javascript:x)\x1b"
    api = ScanAPI([[item]])
    api.fail_issue = 1
    monkeypatch.setattr(cli, "GitHub", lambda: api)
    assert cli.main(["scan", REPO, "--actor", "Contributor"]) == 1
    text = capsys.readouterr().out
    assert r"\| injected \[link\]" in text
    assert "Issue #1: error" in text
    assert "Required GitHub API request failed" in text
    assert "\x1b" not in text


def test_invalid_repository_returns_input_error_before_listing(monkeypatch, capsys):
    api = ScanAPI()
    monkeypatch.setattr(cli, "GitHub", lambda: api)
    assert cli.main(["scan", "../project", "--actor", "Contributor"]) == 1
    assert api.calls == []
    assert capsys.readouterr().err


def test_max_pr_limit_is_forwarded_to_each_issue(monkeypatch, capsys):
    api = ScanAPI([[issue(1)]])
    api.comments[1] = [
        {"body": (f"https://github.com/{REPO}/pull/10 https://github.com/{REPO}/pull/11")}
    ]
    api.pr = dict(
        number=10,
        title="Related",
        html_url=f"https://github.com/{REPO}/pull/10",
        body="Related to #1",
        state="open",
        merged=False,
        base=dict(repo=dict(full_name=REPO)),
    )
    code, report = run_scan(monkeypatch, capsys, api, "--max-prs", "1")
    assert code == 0
    result = report["results"][0]["report"]
    assert len(result["pull_requests"]) == 1
    assert any("1 of 2" in gap for gap in result["collection_gaps"])
    assert not any(call.endswith("/pulls/11") for call in api.calls)


def test_shared_cache_does_not_cache_issue_comments_or_timeline():
    from issue_preflight.scan import _SharedAPI

    api = ScanAPI([[issue(1)]])
    metadata = dict(full_name=REPO, default_branch="main", archived=False)
    shared = _SharedAPI(api, REPO, REPO, metadata)
    for endpoint in (
        f"repos/{REPO}/issues/1",
        f"repos/{REPO}/issues/1/comments?per_page=100&page=1",
        f"repos/{REPO}/issues/1/timeline?per_page=100&page=1",
    ):
        shared.get(endpoint)
        shared.get(endpoint)
        assert api.calls.count(endpoint) == 2


def test_cli_scan_uses_get_only_without_implicit_file_write(monkeypatch, capsys, tmp_path):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from issue_preflight.github import GitHub

    api = ScanAPI()
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        assert command[1:6] == ["api", "--hostname", "github.com", "--method", "GET"]
        return SimpleNamespace(returncode=0, stdout=json.dumps(api.get(command[-1])), stderr="")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("issue_preflight.github.shutil.which", lambda _: "/usr/bin/gh")
    monkeypatch.setattr("issue_preflight.github.subprocess.run", run)
    monkeypatch.setattr(cli, "GitHub", GitHub)
    write = Mock(side_effect=AssertionError("Unexpected file write"))
    monkeypatch.setattr("issue_preflight.cli.Path.write_text", write)
    assert cli.main(["scan", REPO, "--actor", "Contributor", "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["results"] == []
    assert commands
    write.assert_not_called()


@pytest.mark.parametrize("args", [["--limit", "oops"], ["--unknown"], []])
def test_scan_argument_errors_use_exit_one_not_evidence_gate(monkeypatch, capsys, args):
    api = ScanAPI()
    monkeypatch.setattr(cli, "GitHub", lambda: api)
    argv = ["scan", REPO, *args] if args else ["scan"]
    assert cli.main(argv) == 1
    captured = capsys.readouterr()
    assert captured.err
    assert captured.out == ""
    assert api.calls == []


@pytest.mark.parametrize("actor", ["", "   ", "\t \n"])
@pytest.mark.parametrize("items", [[], [issue(1), issue(2)]])
def test_explicit_blank_actor_is_unknown_without_falling_back_to_login(
    monkeypatch, capsys, actor, items
):
    api = ScanAPI([items])
    monkeypatch.setattr(cli, "GitHub", lambda: api)
    assert (
        cli.main(
            [
                "scan",
                REPO,
                "--actor",
                actor,
                "--format",
                "json",
                "--fail-on-review",
            ]
        )
        == 2
    )
    report = json.loads(capsys.readouterr().out)
    assert report["actor"] is None
    assert report["identity_gaps"]
    assert "user" not in api.calls
    assert decisions(report) == ["review"] * len(items)
    assert all(r["report"]["actor"] is None for r in report["results"])
    assert all(r["report"]["collection_gaps"] for r in report["results"])
