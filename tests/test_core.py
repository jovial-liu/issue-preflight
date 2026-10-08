from __future__ import annotations

import base64
import json
from copy import deepcopy

import pytest

from issue_preflight import cli
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


@pytest.mark.parametrize(
    "clause",
    [
        "Contents are fully **reviewed, tested, and understood by a human**",
        "Contributions must be reviewed by a human.",
        "Review by a human is expected.",
        "Contributions must be reviewed, tested,\nand understood by a human.",
        "Contributions must be reviewed\nby a **human**.",
        "Contributions must be reviewed by\na human.",
        "Contributions must be reviewed by **a human**.",
        "Contributions must be reviewed and approved by a human.",
        "Contributions must be reviewed, checked, and approved by a human.",
        "Human review is required before submitting a PR.",
    ],
)
def test_human_review_policy_keeps_original_evidence(clause):
    # First clause: requests-cache CONTRIBUTING.md at e7f0f73a8194a89497f41f8556334d8993ebee2a.
    policy = "# Contributing\n\n" + clause + "\n"
    result = inspect(FixtureAPI(policy), "example/project#42")
    finding = next(f for f in result["findings"] if f["code"] == "human_review_policy")
    assert result["decision"] == "review"
    assert result["collection_gaps"] == []
    assert finding["severity"] == "review"
    assert finding["excerpt"] == clause
    assert finding["line_start"] == 3
    assert finding["line_end"] == 3 + clause.count("\n")
    anchor = "#L3" + (f"-L{finding['line_end']}" if finding["line_end"] != 3 else "")
    assert finding["url"] == f"https://github.com/{REPO}/blob/{SHA}/CONTRIBUTING.md{anchor}"


@pytest.mark.parametrize(
    "policy",
    [
        "Contributions must be reviewed by a bot.",
        "The review document is written by a human.",
        "Code is reviewed by a bot, and documentation is written by a human.",
        "Code is reviewed and documentation is written by a human.",
        "Code is reviewed\n# Documentation\nWritten by a human.",
        "- Code is reviewed\n- Documentation is written by a human.",
        "Code is reviewed. Documentation is written by a human.",
        "Code is reviewed! Documentation is written by a human.",
        "Code is reviewed? Documentation is written by a human.",
        "Code is reviewed\n\nDocumentation is written by a human.",
        "Code is reviewed by\n\na human.",
        "Code is reviewed" + " elsewhere" * 20 + " by a human.",
        "```\nContributions must be reviewed by a human.\n```",
        "Example: `Contributions must be reviewed by a human.`",
        "<!-- Contributions must be reviewed by a human. -->",
    ],
)
def test_unrelated_or_example_review_text_is_not_a_human_policy(policy):
    result = inspect(FixtureAPI(policy), "example/project#42")
    assert "human_review_policy" not in codes(result)
    assert result["decision"] == "no_obvious_blockers"


def test_cli_fails_on_newly_detected_human_review_policy(monkeypatch, tmp_path, capsys):
    api = FixtureAPI("Contents are fully **reviewed, tested, and understood by a human**")
    monkeypatch.setattr(cli, "GitHub", lambda: api)
    output = tmp_path / "report.json"
    assert (
        cli.main(
            [
                "example/project#42",
                "--actor",
                "Contributor",
                "--format",
                "json",
                "--output",
                str(output),
                "--fail-on-review",
            ]
        )
        == 2
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    assert capsys.readouterr().out == ""
    assert report["decision"] == "review"
    assert "human_review_policy" in codes(report)


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


def test_assignment_evidence_has_pinned_lines_and_original_excerpt():
    policy = "# Contributing\n\nThe author must be assigned.\nMore details here.\n"
    result = inspect(FixtureAPI(policy), "example/project#42")
    finding = next(f for f in result["findings"] if f["code"] == "assignment_policy")
    assert finding["url"] == f"https://github.com/{REPO}/blob/{SHA}/CONTRIBUTING.md#L3"
    assert finding["line_start"] == finding["line_end"] == 3
    assert finding["excerpt"] == "The author must be assigned."
    assert finding["path"] == "CONTRIBUTING.md"


def test_wrapped_assignment_evidence_covers_both_source_lines():
    policy = "# Contributing\n\nThe author must\nbe assigned.\n"
    result = inspect(FixtureAPI(policy), "example/project#42")
    finding = next(f for f in result["findings"] if f["code"] == "assignment_policy")
    assert finding["url"].endswith("#L3-L4")
    assert finding["excerpt"] == "The author must\nbe assigned."


@pytest.mark.parametrize(
    "body",
    [
        "~~~markdown\nFixes #42\n~~~",
        "````markdown\n```\nFixes #42\n```\n````",
        "<!-- Fixes #42 -->",
        "Example: ``Fixes #42``",
    ],
)
def test_markdown_examples_do_not_block_contributions(body):
    api = FixtureAPI()
    api.timeline = [link()]
    api.prs = {51: pr(body=body)}
    result = inspect(api, "example/project#42")
    assert "existing_fix" not in codes(result)


def test_fenced_policy_and_maintainer_examples_are_not_rules():
    api = FixtureAPI("# Examples\n\n~~~\nThe author must be assigned.\n~~~\n")
    api.comments = [
        {
            "author_association": "MEMBER",
            "body": "Example comment:\n```\nDo not open another PR.\n```",
        }
    ]
    assert inspect(api, "example/project#42")["decision"] == "no_obvious_blockers"


def test_maintainer_request_keeps_original_text_and_comment_url():
    api = FixtureAPI()
    api.comments = [
        {
            "author_association": "MEMBER",
            "body": "Thanks for looking.\nPlease do not open another PR until we agree.\n",
            "html_url": f"https://github.com/{REPO}/issues/42#issuecomment-123",
        }
    ]
    result = inspect(api, "example/project#42")
    finding = next(f for f in result["findings"] if f["code"] == "maintainer_stop")
    assert finding["excerpt"] == "Please do not open another PR until we agree."
    assert finding["url"].endswith("#issuecomment-123")
    assert finding["line_start"] == finding["line_end"] == 2


def test_existing_fix_reports_original_closing_directive():
    api = FixtureAPI()
    api.timeline = [link()]
    api.prs = {51: pr(body="Changes:\n\nFixes #42.\n")}
    result = inspect(api, "example/project#42")
    finding = next(f for f in result["findings"] if f["code"] == "existing_fix")
    assert finding["excerpt"] == "Fixes #42."
    assert finding["line_start"] == 3


def test_unresolved_manual_link_is_visible_in_collection_gaps():
    api = FixtureAPI()
    api.timeline = [{"event": "connected", "node_id": "CE_example"}]
    result = inspect(api, "example/project#42")
    assert result["decision"] == "review"
    assert any("manual" in gap.lower() for gap in result["collection_gaps"])


@pytest.mark.parametrize(
    "body",
    [
        "Example:\n\n    Fixes #42",
        "Example:\n\n        Fixes #42",
        "> ~~~\n> Fixes #42\n> ~~~",
    ],
)
def test_indented_and_quoted_code_are_not_fixes(body):
    assert not closes_issue(pr(body=body), REPO, 42)


@pytest.mark.parametrize(
    "example",
    [
        "~~~\nFixes #41\n~~~",
        "````\n```\nFixes #41\n```\n````",
        "<!-- Fixes #41 -->",
        "Example: ``Fixes #41``",
        "Example:\n\n    Fixes #41\n",
    ],
)
def test_real_fix_after_an_example_remains_visible_at_original_line(example):
    body = example + "\n\nFixes #42.\n"
    api = FixtureAPI()
    api.timeline = [link()]
    api.prs = {51: pr(body=body)}
    result = inspect(api, "example/project#42")
    finding = next(f for f in result["findings"] if f["code"] == "existing_fix")
    assert finding["excerpt"] == "Fixes #42."
    assert finding["line_start"] == body.splitlines().index("Fixes #42.") + 1


def test_cross_repo_reference_mask_preserves_original_evidence_offsets():
    api = FixtureAPI()
    api.timeline = [link()]
    candidate = pr(body="Fixes #99, but also fixes example/project#42.\n")
    candidate["base"]["repo"]["full_name"] = "another/project"
    api.prs = {51: candidate}
    result = inspect(api, "example/project#42")
    finding = next(f for f in result["findings"] if f["code"] == "existing_fix")
    assert finding["excerpt"] == candidate["body"].strip()


def test_long_line_excerpt_stays_bounded_and_keeps_detected_rule():
    policy = "Before " * 500 + "The author must be assigned." + " After" * 500
    result = inspect(FixtureAPI(policy), "example/project#42")
    finding = next(f for f in result["findings"] if f["code"] == "assignment_policy")
    assert len(finding["excerpt"]) < 400
    assert "author must be assigned" in finding["excerpt"]
    assert finding["excerpt_truncated"] is True
    assert finding["line_start"] == finding["line_end"] == 1


def test_policy_windows_newlines_have_correct_line_anchors():
    policy = "# Contributing\r\n\r\nThe author must be assigned.\r\n"
    result = inspect(FixtureAPI(policy), "example/project#42")
    finding = next(f for f in result["findings"] if f["code"] == "assignment_policy")
    assert finding["url"].endswith("#L3")
    assert finding["excerpt"] == "The author must be assigned."


@pytest.mark.parametrize(
    "before",
    [
        "Example `<!--` syntax.",
        "```html\n<!--\n```",
        "<!--\n```\n-->",
        "An unmatched backtick `",
        "> ```\n> example",
        r"Literal \` notation.",
    ],
)
def test_examples_and_comments_do_not_hide_a_later_real_fix(before):
    after = "\n\nFixes #42\n\nAnother unmatched backtick `"
    assert closes_issue(pr(body=before + after), REPO, 42)


def test_inline_negation_is_not_erased_into_an_assignment_requirement():
    api = FixtureAPI("The author must `not` be assigned.")
    assert "assignment_policy" not in codes(inspect(api, "example/project#42"))


def test_inline_code_does_not_cross_a_paragraph_interrupting_fence():
    body = 'An unmatched backtick `\n```python\nprint("`")\n```\nFixes #42'
    assert closes_issue(pr(body=body), REPO, 42)


APPROVAL_RULE = (
    "The Pull Request must link to a issue or discussion where a solution "
    "has been approved by a maintainer (@example)."
)


class LinkedPolicyAPI(FixtureAPI):
    def __init__(self, policies):
        super().__init__()
        self.policies = policies

    def get(self, endpoint):
        from urllib.parse import unquote

        prefix = f"repos/{REPO}/contents/"
        if endpoint.startswith(prefix):
            self.calls.append(endpoint)
            path, query = endpoint[len(prefix) :].split("?", 1)
            assert query == f"ref={SHA}"
            value = self.policies.get(unquote(path))
            if value is None:
                raise NotFound()
            if isinstance(value, GitHubError):
                raise value
            if not isinstance(value, str):
                return value
            raw = value.encode("utf-8")
            return dict(encoding="base64", size=len(raw), content=base64.b64encode(raw).decode())
        return super().get(endpoint)


@pytest.mark.parametrize(
    "url",
    [
        "AI_POLICY.md",
        f"https://github.com/{REPO}/blob/master/AI_POLICY.md",
        f"https://github.com/{REPO.upper()}/blob/{'b' * 40}/AI_POLICY.md?plain=1#L5",
    ],
)
def test_linked_ai_policy_is_read_at_the_report_snapshot_and_reported(url):
    api = LinkedPolicyAPI(
        {
            "CONTRIBUTING.md": f"# Contributing\n\nSee [AI policy]({url}) when using AI.\n",
            "AI_POLICY.md": "# AI policy\n\n" + APPROVAL_RULE + "\n",
        }
    )
    result = inspect(api, "example/project#42")
    assert result["decision"] == "review"
    assert {p["path"] for p in result["policy_sources"]} == {"CONTRIBUTING.md", "AI_POLICY.md"}
    finding = next(f for f in result["findings"] if f["code"] == "approval_policy")
    assert finding["severity"] == "review"
    assert finding["url"] == f"https://github.com/{REPO}/blob/{SHA}/AI_POLICY.md#L3"
    assert finding["excerpt"] == APPROVAL_RULE
    assert "not verified" in finding["message"]


def test_linked_policy_can_return_to_repo_root_from_a_nested_guide():
    api = LinkedPolicyAPI(
        {
            ".github/CONTRIBUTING.md": "[AI policy](../AI_POLICY.md)",
            "AI_POLICY.md": APPROVAL_RULE,
        }
    )
    result = inspect(api, "example/project#42")
    assert "approval_policy" in codes(result)
    assert result["collection_gaps"] == []


def test_root_relative_policy_link_uses_the_repository_root():
    api = LinkedPolicyAPI(
        {
            ".github/CONTRIBUTING.md": "[AI policy](/docs/AI_POLICY.md)",
            "docs/AI_POLICY.md": APPROVAL_RULE,
        }
    )
    result = inspect(api, "example/project#42")
    assert {p["path"] for p in result["policy_sources"]} == {
        ".github/CONTRIBUTING.md",
        "docs/AI_POLICY.md",
    }


@pytest.mark.parametrize("problem", [None, GitHubError("denied"), []])
def test_explicit_policy_link_failure_remains_visible(problem):
    api = LinkedPolicyAPI(
        {
            "CONTRIBUTING.md": "[AI policy](AI_POLICY.md)",
            "AI_POLICY.md": problem,
        }
    )
    result = inspect(api, "example/project#42")
    assert result["decision"] == "review"
    assert any("AI_POLICY.md" in gap for gap in result["collection_gaps"])


def test_probe_404_is_not_hidden_when_a_later_guide_explicitly_links_it():
    api = LinkedPolicyAPI(
        {
            "CONTRIBUTING.md": "[Contributing guide](docs/contributing.md)",
            "docs/contributing.md": "[Agent policy](../AGENTS.md)",
        }
    )
    result = inspect(api, "example/project#42")
    assert sum("/contents/AGENTS.md?" in call for call in api.calls) == 1
    assert any("AGENTS.md" in gap for gap in result["collection_gaps"])


def test_policy_link_cycles_and_path_aliases_are_fetched_once():
    api = LinkedPolicyAPI(
        {
            "CONTRIBUTING.md": (
                "[AI policy](docs/../AI_POLICY.md) "
                "[AI policy again](AI%5FPOLICY.md) "
                "[Contribution guide](CONTRIBUTING.md)"
            ),
            "AI_POLICY.md": "[Contribution guide](CONTRIBUTING.md)",
        }
    )
    result = inspect(api, "example/project#42")
    calls = [call for call in api.calls if "/contents/" in call]
    assert len(calls) == len(set(calls)) == 4
    assert result["collection_gaps"] == []


def test_six_policy_request_budget_includes_missing_probe_files():
    api = LinkedPolicyAPI(
        {
            "CONTRIBUTING.md": " ".join(f"[AI policy](docs/AI_POLICY_{i}.md)" for i in range(8)),
            **{f"docs/AI_POLICY_{i}.md": "Read this policy." for i in range(8)},
        }
    )
    result = inspect(api, "example/project#42")
    assert sum("/contents/" in call for call in api.calls) == 6
    assert any("capped at six" in gap for gap in result["collection_gaps"])


def test_unfetched_external_policy_is_an_evidence_gap_without_credentials():
    api = LinkedPolicyAPI(
        {
            "CONTRIBUTING.md": "[AI policy](https://user:secret@elsewhere.example/AI_POLICY.md)",
        }
    )
    result = inspect(api, "example/project#42")
    assert result["decision"] == "review"
    assert result["collection_gaps"]
    assert "secret" not in str(result)
    assert not any("elsewhere.example" in call for call in api.calls)


@pytest.mark.parametrize(
    "policy",
    [
        "After code review, a maintainer may approve the Pull Request.",
        "You may want to discuss a solution before submitting a Pull Request.",
        f"Example:\n\n```\n{APPROVAL_RULE}\n```",
        f"<!-- {APPROVAL_RULE} -->",
    ],
)
def test_optional_or_example_approval_is_not_a_requirement(policy):
    assert "approval_policy" not in codes(inspect(FixtureAPI(policy), "example/project#42"))


@pytest.mark.parametrize(
    "payload",
    [
        dict(encoding="base64", size=3, content="!!!"),
        dict(encoding="base64", size=1, content=base64.b64encode(b"\xff").decode()),
        dict(encoding="base64", size=0, content=base64.b64encode(b"x" * 80001).decode()),
    ],
)
def test_linked_policy_invalid_or_oversized_payload_is_not_silently_accepted(payload):
    api = LinkedPolicyAPI(
        {
            "CONTRIBUTING.md": "[AI policy](AI_POLICY.md)",
            "AI_POLICY.md": payload,
        }
    )
    result = inspect(api, "example/project#42")
    assert result["decision"] == "review"
    assert any("AI_POLICY.md" in gap for gap in result["collection_gaps"])
    assert {p["path"] for p in result["policy_sources"]} == {"CONTRIBUTING.md"}


def test_wrapped_approval_rule_keeps_exact_source_line_range():
    api = FixtureAPI(
        "The Pull Request must link to an issue where a solution\n"
        "has been approved by a maintainer.\n"
    )
    result = inspect(api, "example/project#42")
    finding = next(f for f in result["findings"] if f["code"] == "approval_policy")
    assert finding["url"].endswith("#L1-L2")
    assert finding["line_start"] == 1 and finding["line_end"] == 2
