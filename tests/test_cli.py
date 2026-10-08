from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from issue_preflight import cli
from issue_preflight.github import GitHub, GitHubError, NotFound


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


def test_cli_fail_on_hold_still_writes_report(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "GitHub", lambda: object())
    monkeypatch.setattr(cli, "inspect", lambda *a, **k: {"decision": "hold"})
    output = tmp_path / "report.json"
    assert (
        cli.main(
            ["example/project#42", "--format", "json", "--output", str(output), "--fail-on-hold"]
        )
        == 2
    )
    assert json.loads(output.read_text(encoding="utf-8")) == {"decision": "hold"}


def test_cli_api_failure_returns_error_without_report(monkeypatch, capsys):
    def fail():
        raise GitHubError("Install gh")

    monkeypatch.setattr(cli, "GitHub", fail)
    assert cli.main(["example/project#42"]) == 1
    assert "Install gh" in capsys.readouterr().err
