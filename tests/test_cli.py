from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from issue_preflight import cli
from issue_preflight.github import GitHub, GitHubError, NotFound


@pytest.fixture
def report():
    return dict(
        repository="example/project",
        issue=dict(
            number=42, title="Fix URL fragments", url="https://github.com/example/project/issues/42"
        ),
        decision="no_obvious_blockers",
        actor=None,
        fetched_at="2026-10-09T00:00:00+00:00",
        interpretation="Heuristic evidence review.",
        findings=[],
        pull_requests=[],
        policy_ref="a" * 40,
        policy_sources=[],
        collection_gaps=[],
    )


def test_github_adapter_uses_get_without_a_shell(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/gh")
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout='{"ok": true}', stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    assert GitHub().get("repos/example/project") == {"ok": True}
    argv, kwargs = calls[0]
    assert argv == [
        "/usr/bin/gh",
        "api",
        "--hostname",
        "github.com",
        "--method",
        "GET",
        "repos/example/project",
    ]
    assert kwargs["timeout"] == 30
    assert "shell" not in kwargs


def test_api_failure_does_not_echo_stderr_secrets(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/gh")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="token=never-print-this",
        ),
    )
    with pytest.raises(GitHubError) as error:
        GitHub().get("repos/example/project")
    assert "never-print" not in str(error.value)


def test_404_is_not_silently_treated_as_an_empty_policy(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/gh")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="gh: HTTP 404",
        ),
    )
    with pytest.raises(NotFound):
        GitHub().get("repos/example/project")


def test_timeout_is_reported(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/gh")

    def run(*args, **kwargs):
        raise subprocess.TimeoutExpired("gh", 30)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(GitHubError, match="deadline"):
        GitHub().get("repos/example/project")


def test_markdown_escapes_title_and_terminal_control_codes():
    assert cli._plain("[click](x)\x1b[31m|hi") == r"\[click\](x) \[31m\|hi"


@pytest.mark.parametrize(
    ("decision", "flag", "exit_code"),
    [
        ("hold", "--fail-on-hold", 2),
        ("review", "--fail-on-hold", 0),
        ("hold", "--fail-on-review", 2),
        ("review", "--fail-on-review", 2),
        ("no_obvious_blockers", "--fail-on-review", 0),
    ],
)
def test_cli_decision_flags_still_write_report(
    monkeypatch, tmp_path, report, decision, flag, exit_code
):
    report["decision"] = decision
    monkeypatch.setattr(cli, "GitHub", lambda: object())
    monkeypatch.setattr(cli, "inspect", lambda *a, **k: report)
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
                flag,
            ]
        )
        == exit_code
    )
    assert json.loads(output.read_text(encoding="utf-8")) == report


def test_cli_defaults_to_authenticated_user(monkeypatch, capsys, report):
    calls = []

    def get(endpoint):
        calls.append(endpoint)
        return {"login": "AuthenticatedContributor"}

    api = SimpleNamespace(get=get)
    monkeypatch.setattr(cli, "GitHub", lambda: api)

    def inspect(client, target, actor, max_prs):
        assert client is api
        assert target == "example/project#42"
        assert actor == "AuthenticatedContributor"
        assert max_prs == 8
        report["actor"] = actor
        return report

    monkeypatch.setattr(cli, "inspect", inspect)
    assert cli.main(["example/project#42", "--format", "json"]) == 0
    assert calls == ["user"]
    assert json.loads(capsys.readouterr().out)["actor"] == "AuthenticatedContributor"


def test_explicit_actor_overrides_authentication_without_user_request(monkeypatch, capsys, report):
    api = object()
    monkeypatch.setattr(cli, "GitHub", lambda: api)

    def inspect(client, target, actor, max_prs):
        assert client is api
        assert actor == "RequestedContributor"
        report["actor"] = actor
        return report

    monkeypatch.setattr(cli, "inspect", inspect)
    assert cli.main(["example/project#42", "--actor", "RequestedContributor"]) == 0
    assert "Contributor evaluated: RequestedContributor" in capsys.readouterr().out


@pytest.mark.parametrize("decision", ["no_obvious_blockers", "review", "hold"])
def test_identity_failure_is_an_explicit_gap_without_losing_report(
    monkeypatch, capsys, report, decision
):
    report["decision"] = decision

    def get(endpoint):
        assert endpoint == "user"
        raise GitHubError("token=never-print-this")

    monkeypatch.setattr(cli, "GitHub", lambda: SimpleNamespace(get=get))

    def inspect(client, target, actor, max_prs):
        assert actor is None
        return report

    monkeypatch.setattr(cli, "inspect", inspect)
    assert cli.main(["example/project#42", "--format", "json"]) == 0
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert result["actor"] is None
    assert result["decision"] == ("hold" if decision == "hold" else "review")
    assert any("assignment eligibility is unknown" in gap for gap in result["collection_gaps"])
    assert [finding["code"] for finding in result["findings"]] == ["incomplete_evidence"]
    assert "never-print-this" not in output.out + output.err


@pytest.mark.parametrize("user", [{}, {"login": ""}, {"login": None}, []])
def test_unusable_user_response_marks_identity_unknown(monkeypatch, capsys, report, user):
    monkeypatch.setattr(cli, "GitHub", lambda: SimpleNamespace(get=lambda endpoint: user))
    monkeypatch.setattr(cli, "inspect", lambda *a, **k: report)
    assert cli.main(["example/project#42", "--format", "json", "--fail-on-review"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["decision"] == "review"
    assert result["collection_gaps"]


def test_identity_gap_does_not_duplicate_incomplete_evidence(monkeypatch, capsys, report):
    report["findings"] = [dict(code="incomplete_evidence", severity="review")]
    monkeypatch.setattr(cli, "GitHub", lambda: SimpleNamespace(get=lambda endpoint: {}))
    monkeypatch.setattr(cli, "inspect", lambda *a, **k: report)
    assert cli.main(["example/project#42", "--format", "json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert len(result["findings"]) == 1
    assert result["collection_gaps"]


def test_markdown_shows_unknown_contributor(report):
    assert (
        "Contributor evaluated: unknown; assignment eligibility could not be evaluated"
        in cli.markdown(report)
    )


def test_markdown_quotes_each_excerpt_line_and_escapes_untrusted_markup(report):
    report["findings"] = [
        dict(
            severity="blocker",
            message="Read the contribution rule.",
            url="https://github.com/example/project/blob/abc/CONTRIBUTING.md#L4-L12",
            excerpt=(
                "[run](javascript:alert(1))\n"
                "> escape\n"
                "# Forged header\n"
                "1. fake list\n"
                "![secret](https://evil.test/x)\n"
                "<script>alert(1)</script>\n"
                "```\n"
                "\x1b[31mterminal\x00"
            ),
            excerpt_truncated=True,
        )
    ]
    output = cli.markdown(report)
    assert "#L4-L12))" in output
    assert r"  > \[run\]\(javascript:alert\(1\)\)" in output
    assert r"  > \> escape" in output
    assert r"  > \# Forged header" in output
    assert r"  > 1\. fake list" in output
    assert r"  > \!\[secret\]\(https://evil\.test/x\)" in output
    assert r"  > \<script\>alert\(1\)\</script\>" in output
    assert r"  > \`\`\`" in output
    assert r"  >  \[31mterminal" in output
    assert all(line == line.rstrip() for line in output.splitlines())
    assert "Excerpt truncated; read the source for the full context." in output
    assert "\x1b" not in output and "\x00" not in output


def test_markdown_complete_excerpt_does_not_claim_truncation(report):
    report["findings"] = [
        dict(
            severity="review", message="Read it.", url=report["issue"]["url"], excerpt="Full text."
        )
    ]
    output = cli.markdown(report)
    assert r"  > Full text\." in output
    assert "Excerpt truncated" not in output


def test_cli_api_failure_returns_error_without_report(monkeypatch, capsys):
    def fail():
        raise GitHubError("Install gh")

    monkeypatch.setattr(cli, "GitHub", fail)
    assert cli.main(["example/project#42"]) == 1
    assert "Install gh" in capsys.readouterr().err
