"""Policy citations must describe verified bytes at the cited repository path."""

from copy import deepcopy
from urllib.parse import unquote

import pytest
from policy_fixtures import blob_sha, file_response
from test_core import APPROVAL_RULE, REPO, SHA, FixtureAPI, codes, policy_requests

from issue_preflight.core import inspect
from issue_preflight.github import GitHubError, NotFound

GUIDE = "# Contributing\n\nAI-generated contributions must be reviewed by a human.\n"
TARGET = "docs/rules/contributor-policy.md"


class SourceAPI(FixtureAPI):
    def __init__(self, files, aliases=None):
        super().__init__()
        self.files = {path: file_response(path, text) for path, text in files.items()}
        self.blobs = {}
        for path, (target, body) in (aliases or {}).items():
            raw = target.encode("utf-8")
            payload = file_response(path, body)
            payload["sha"] = blob_sha(raw)
            self.files[path] = payload
            blob = file_response(path, target)
            blob.pop("path")
            blob.pop("type")
            self.blobs[blob["sha"]] = blob

    def get(self, endpoint):
        for prefix, values in (
            (f"repos/{REPO}/contents/", self.files),
            (f"repos/{REPO}/git/blobs/", self.blobs),
        ):
            if not endpoint.startswith(prefix):
                continue
            self.calls.append(endpoint)
            name, _, query = endpoint[len(prefix) :].partition("?")
            if values is self.files:
                assert query == f"ref={SHA}"
                name = unquote(name)
            value = values.get(name)
            if value is None:
                raise NotFound()
            if isinstance(value, GitHubError):
                raise value
            return deepcopy(value)
        return super().get(endpoint)


def test_symlink_cites_canonical_lines_and_resolves_policy_links_from_that_directory():
    guide = GUIDE + "\n[AI policy](AI_POLICY.md)\n"
    api = SourceAPI(
        {TARGET: guide, "docs/rules/AI_POLICY.md": APPROVAL_RULE},
        {"CONTRIBUTING.md": (TARGET, guide)},
    )
    report = inspect(api, "example/project#42")
    assert report["collection_gaps"] == []
    assert {source["path"] for source in report["policy_sources"]} == {
        TARGET,
        "docs/rules/AI_POLICY.md",
    }
    human = next(f for f in report["findings"] if f["code"] == "human_review_policy")
    assert human["path"] == TARGET
    assert human["url"] == f"https://github.com/{REPO}/blob/{SHA}/{TARGET}#L3"
    assert "approval_policy" in codes(report)
    assert "AI_POLICY.md" not in policy_requests(api)
    assert "docs/contributing.md" not in policy_requests(api)


def test_unverified_symlink_never_reports_rules_at_the_alias_lines():
    api = SourceAPI({}, {"CONTRIBUTING.md": (TARGET, GUIDE)})
    api.blobs.clear()
    report = inspect(api, "example/project#42")
    assert report["decision"] == "review"
    assert report["policy_sources"] == []
    assert "human_review_policy" not in codes(report)
    assert any("CONTRIBUTING.md" in gap for gap in report["collection_gaps"])


def test_verified_normal_policy_needs_no_extra_blob_request():
    api = SourceAPI({"CONTRIBUTING.md": GUIDE})
    report = inspect(api, "example/project#42")
    human = next(f for f in report["findings"] if f["code"] == "human_review_policy")
    assert human["url"].endswith("/CONTRIBUTING.md#L3")
    assert report["collection_gaps"] == []
    assert not any("/git/blobs/" in call for call in api.calls)


@pytest.mark.parametrize(
    "metadata",
    [
        {"sha": None},
        {"sha": "not-a-git-sha"},
        {"path": "elsewhere.md"},
        {"type": "dir"},
        {"type": []},
        {"size": True},
        {"size": 0},
    ],
)
def test_incomplete_or_conflicting_normal_file_metadata_is_a_gap(metadata):
    api = SourceAPI({"CONTRIBUTING.md": GUIDE})
    api.files["CONTRIBUTING.md"].update(metadata)
    report = inspect(api, "example/project#42")
    assert report["decision"] == "review"
    assert report["policy_sources"] == []
    assert "human_review_policy" not in codes(report)
    assert report["collection_gaps"]
    assert not any("/git/blobs/" in call for call in api.calls)


@pytest.mark.parametrize(
    "target",
    [
        "/docs/policy.md",
        "../policy.md",
        "https://user:secret@example.org/policy.md",
        "C:\\policy.md",
        "docs/policy.md\n",
        "docs/\0policy.md",
        "docs/policy.pdf",
        "docs/",
        "x" * 4097,
    ],
)
def test_unsafe_or_unsupported_link_targets_are_gaps_without_target_requests(target):
    api = SourceAPI({}, {"CONTRIBUTING.md": (target, GUIDE)})
    report = inspect(api, "example/project#42")
    assert report["policy_sources"] == []
    assert "human_review_policy" not in codes(report)
    assert any("source target" in gap for gap in report["collection_gaps"])
    assert "secret" not in str(report)
    assert len(policy_requests(api)) == 5
    assert len([call for call in api.calls if "/git/blobs/" in call]) == 1


@pytest.mark.parametrize("target", ["docs/policy%20name.md", "docs/policy #1?.md", "政策.md"])
def test_link_targets_preserve_literal_percent_spaces_fragment_query_and_unicode(target):
    api = SourceAPI({target: GUIDE}, {"CONTRIBUTING.md": (target, GUIDE)})
    report = inspect(api, "example/project#42")
    assert report["collection_gaps"] == []
    assert report["policy_sources"][0]["path"] == target
    source = report["policy_sources"][0]["url"]
    assert unquote(source.split(f"/blob/{SHA}/", 1)[1]) == target
    assert len(policy_requests(api)) == 4


def test_nested_link_chain_resolves_relative_targets_and_preserves_guide_role():
    api = SourceAPI(
        {TARGET: GUIDE},
        {
            "CONTRIBUTING.md": ("docs/contributing.md", GUIDE),
            "docs/contributing.md": ("rules/contributor-policy.md", GUIDE),
        },
    )
    report = inspect(api, "example/project#42")
    assert report["collection_gaps"] == []
    assert [p["path"] for p in report["policy_sources"]] == [TARGET]
    assert len(policy_requests(api)) == 5
    assert "docs/contributing.rst" not in policy_requests(api)


def test_explicit_symlink_response_without_forwarded_content_uses_verified_blob():
    api = SourceAPI({TARGET: GUIDE}, {"CONTRIBUTING.md": (TARGET, GUIDE)})
    link = api.files["CONTRIBUTING.md"]
    link.update(type="symlink", target="untrusted-target.md")
    for key in ("encoding", "content"):
        del link[key]
    report = inspect(api, "example/project#42")
    assert report["collection_gaps"] == []
    assert [p["path"] for p in report["policy_sources"]] == [TARGET]
    assert "untrusted-target.md" not in policy_requests(api)


def test_link_cycle_is_a_visible_gap_and_never_classifies_forwarded_body():
    api = SourceAPI(
        {},
        {"CONTRIBUTING.md": ("AGENTS.md", GUIDE), "AGENTS.md": ("CONTRIBUTING.md", GUIDE)},
    )
    report = inspect(api, "example/project#42")
    assert report["decision"] == "review"
    assert report["policy_sources"] == []
    assert any("cycle" in gap for gap in report["collection_gaps"])
    assert len(policy_requests(api)) == len(set(policy_requests(api))) == 5


@pytest.mark.parametrize("problem", [None, GitHubError("private failure"), [], {"sha": "b" * 40}])
def test_blob_failures_are_visible_and_do_not_expose_exception_text(problem):
    api = SourceAPI({TARGET: GUIDE}, {"CONTRIBUTING.md": (TARGET, GUIDE)})
    identity = api.files["CONTRIBUTING.md"]["sha"]
    api.blobs[identity] = problem
    report = inspect(api, "example/project#42")
    assert report["policy_sources"] == []
    assert report["collection_gaps"]
    assert "private failure" not in str(report)
    assert TARGET not in policy_requests(api)


def test_blob_content_must_match_the_requested_identity():
    api = SourceAPI({TARGET: GUIDE}, {"CONTRIBUTING.md": (TARGET, GUIDE)})
    identity = api.files["CONTRIBUTING.md"]["sha"]
    api.blobs[identity] = {**file_response("", "another.md"), "sha": identity}
    report = inspect(api, "example/project#42")
    assert report["policy_sources"] == []
    assert report["collection_gaps"]
    assert TARGET not in policy_requests(api)


def test_forwarded_body_conflicting_with_canonical_bytes_is_a_gap():
    api = SourceAPI({TARGET: "Contributions welcome."}, {"CONTRIBUTING.md": (TARGET, GUIDE)})
    report = inspect(api, "example/project#42")
    assert report["policy_sources"] == []
    assert "human_review_policy" not in codes(report)
    assert any("disagree" in gap for gap in report["collection_gaps"])


def test_independent_link_can_use_canonical_bytes_after_an_alias_source_conflict():
    api = SourceAPI(
        {
            "CONTRIBUTING.md": f"[AI policy](alias.md) [AI rules]({TARGET})",
            TARGET: GUIDE,
        },
        {"alias.md": (TARGET, "Different content.")},
    )
    report = inspect(api, "example/project#42")
    assert [p["path"] for p in report["policy_sources"]] == ["CONTRIBUTING.md", TARGET]
    assert "human_review_policy" in codes(report)
    assert any("disagree" in gap for gap in report["collection_gaps"])
    assert policy_requests(api).count(TARGET) == 1


@pytest.mark.parametrize("body", ["\ufeff# Rules\r\n\r\n" + APPROVAL_RULE, ""])
def test_canonical_bytes_preserve_bom_crlf_and_blank_guide_fallback(body):
    api = SourceAPI({TARGET: body}, {"CONTRIBUTING.md": (TARGET, body)})
    report = inspect(api, "example/project#42")
    assert [p["path"] for p in report["policy_sources"]] == [TARGET]
    if body:
        assert report["collection_gaps"] == []
        rule = next(f for f in report["findings"] if f["code"] == "approval_policy")
        assert rule["url"].endswith("#L3")
    else:
        assert report["decision"] == "review"
        assert any("No contribution policy" in gap for gap in report["collection_gaps"])
        assert len(policy_requests(api)) == 6


def test_canonical_rst_extension_controls_classification_after_markdown_alias():
    target = "docs/policy.rst"
    api = SourceAPI({target: GUIDE}, {"CONTRIBUTING.md": (target, GUIDE)})
    report = inspect(api, "example/project#42")
    assert [p["path"] for p in report["policy_sources"]] == [target]
    assert "human_review_policy" not in codes(report)
    assert any("RST policy formatting" in gap for gap in report["collection_gaps"])


def test_sixth_contents_request_can_reuse_an_already_verified_canonical_target():
    paths = [f"links/AI_POLICY_{i}.md" for i in range(4)]
    guide = " ".join(f"[AI policy]({path})" for path in [TARGET, *paths])
    api = SourceAPI(
        {"CONTRIBUTING.md": guide, TARGET: GUIDE},
        {path: ("../" + TARGET, GUIDE) for path in paths},
    )
    report = inspect(api, "example/project#42")
    assert policy_requests(api) == ["CONTRIBUTING.md", TARGET, *paths]
    assert [p["path"] for p in report["policy_sources"]] == ["CONTRIBUTING.md", TARGET]
    assert len([c for c in api.calls if "/git/blobs/" in c]) == 1
    assert report["collection_gaps"] == ["Policy discovery capped at six file requests."]
    assert "human_review_policy" in codes(report)


def test_six_contents_cap_leaves_unverified_target_as_a_gap():
    guide = " ".join(f"[AI policy](link{i}.md)" for i in range(5))
    api = SourceAPI(
        {"CONTRIBUTING.md": guide, **{f"link{i}.md": "Rules." for i in range(4)}},
        {"link4.md": (TARGET, GUIDE)},
    )
    report = inspect(api, "example/project#42")
    assert len(policy_requests(api)) == 6
    assert TARGET not in policy_requests(api)
    assert "human_review_policy" not in codes(report)
    assert any("source verification capped at six" in gap for gap in report["collection_gaps"])


def test_scan_reuses_verified_blob_and_canonical_contents_within_one_batch():
    from test_scan import ScanAPI, issue

    from issue_preflight.scan import scan

    class SourceScanAPI(SourceAPI):
        def __init__(self):
            super().__init__({TARGET: GUIDE}, {"CONTRIBUTING.md": (TARGET, GUIDE)})
            self.other = ScanAPI([[issue(42), issue(43)]])

        def get(self, endpoint):
            if "/contents/" in endpoint or "/git/blobs/" in endpoint:
                return super().get(endpoint)
            return self.other.get(endpoint)

    api = SourceScanAPI()
    report = scan(api, REPO, actor="Contributor")
    for result in report["results"]:
        assert result["report"]["collection_gaps"] == []
        assert [p["path"] for p in result["report"]["policy_sources"]] == [TARGET]
    assert policy_requests(api).count(TARGET) == 1
    assert len([c for c in api.calls if "/git/blobs/" in c]) == 1
