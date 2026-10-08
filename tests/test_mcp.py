"""Optional MCP tools preserve the CLI's evidence and validate before any reads."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_core import FixtureAPI
from test_scan import REPO, SHA, ScanAPI, issue

from issue_preflight import github
from issue_preflight.cli import markdown, scan_markdown
from issue_preflight.mcp import create_server

mcp_sdk = pytest.importorskip("mcp")
Client = mcp_sdk.Client
StdioServerParameters = mcp_sdk.StdioServerParameters
PRIVATE = "PRIVATE_EXCEPTION_TEXT_892761"


def run(scenario):
    return asyncio.run(scenario())


def text(result):
    return "\n".join(block.text for block in result.content if block.type == "text")


def assert_complete(result, *, batch=False):
    assert result.is_error is False
    report = result.structured_content
    assert isinstance(report, dict)
    assert report["schema"] == ("issue-preflight-scan/1" if batch else "issue-preflight/1")
    assert "result" not in report
    assert text(result) == (scan_markdown(report) if batch else markdown(report))
    wire = result.model_dump(mode="json", by_alias=True)
    assert wire["structuredContent"] == report
    assert wire["isError"] is False
    return report


def test_discovery_lists_only_bounded_read_only_tools_without_creating_api():
    calls = []

    def factory():
        calls.append("factory")
        raise AssertionError("Discovery must not create a GitHub adapter")

    async def scenario():
        async with Client(create_server(factory)) as client:
            result = await client.list_tools()
            tools = {tool.name: tool for tool in result.tools}
            assert set(tools) == {"inspect_issue", "scan_repository"}
            for name, tool in tools.items():
                schema = tool.input_schema
                target = "target" if name == "inspect_issue" else "repository"
                assert schema["type"] == "object"
                assert schema["additionalProperties"] is False
                assert schema["required"] == [target]
                assert schema["properties"]["max_prs"]["minimum"] == 1
                assert schema["properties"]["max_prs"]["maximum"] == 20
                assert schema["properties"]["max_prs"]["default"] == 8
                assert tool.output_schema["type"] == "object"
                assert tool.annotations.read_only_hint is True
                assert tool.annotations.destructive_hint is False
                assert tool.annotations.idempotent_hint is True
                assert tool.annotations.open_world_hint is True
            limit = tools["scan_repository"].input_schema["properties"]["limit"]
            assert (limit["minimum"], limit["maximum"], limit["default"]) == (1, 10, 5)
            assert not calls

    run(scenario)
    assert not calls


@pytest.mark.parametrize("decision", ["hold", "review"])
def test_inspection_decisions_are_successful_complete_reports(decision):
    api = FixtureAPI(policy="" if decision == "review" else "Small fixes are welcome.")
    if decision == "hold":
        api.issue["state"] = "closed"

    async def scenario():
        async with Client(create_server(lambda: api)) as client:
            result = await client.call_tool(
                "inspect_issue", {"target": f"{REPO}#42", "actor": "Contributor"}
            )
            report = assert_complete(result)
            assert report["decision"] == decision
            assert report["actor"] == "Contributor"
            assert report["policy_ref"] == SHA
            assert report["repository_access"]["source"] == f"https://api.github.com/repos/{REPO}"
            assert report["issue"]["number"] == 42
            assert {
                "findings",
                "pull_requests",
                "collection_gaps",
                "policy_sources",
            } <= report.keys()
            if decision == "review":
                assert report["collection_gaps"]
            else:
                assert any(f["severity"] == "blocker" for f in report["findings"])

    run(scenario)


def test_batch_partial_errors_and_identity_gaps_are_successful_visible_reports():
    api = ScanAPI([[issue(1), issue(2)]])
    api.fail_issue = 2
    api.user = github.GitHubError(PRIVATE)

    async def scenario():
        async with Client(create_server(lambda: api)) as client:
            report = assert_complete(
                await client.call_tool("scan_repository", {"repository": REPO}), batch=True
            )
            assert report["limit"] == 5
            assert report["max_prs"] == 8
            assert report["summary"] == {
                "hold": 0,
                "review": 1,
                "no_obvious_blockers": 0,
                "errors": 1,
            }
            assert report["actor"] is None
            assert report["identity_gaps"]
            successful = report["results"][0]["report"]
            assert successful["decision"] == "review"
            assert successful["collection_gaps"]
            assert any(f["code"] == "incomplete_evidence" for f in successful["findings"])
            assert report["results"][1]["status"] == "error"
            assert PRIVATE not in json.dumps(report)
            assert PRIVATE not in scan_markdown(report)

    run(scenario)


def test_failed_identity_does_not_downgrade_existing_hold():
    api = ScanAPI([[issue(1)]])
    api.issues[1] = issue(1)
    api.issues[1]["state"] = "closed"
    api.user = {"login": None}

    async def scenario():
        async with Client(create_server(lambda: api)) as client:
            report = assert_complete(
                await client.call_tool("inspect_issue", {"target": f"{REPO}#1"})
            )
            assert report["actor"] is None
            assert report["decision"] == "hold"
            assert report["collection_gaps"]

    run(scenario)


INVALID = [
    ("inspect_issue", {}),
    ("inspect_issue", {"target": None}),
    ("inspect_issue", {"target": f"{REPO}#42", "command": "ignored-command"}),
    ("inspect_issue", {"target": f"{REPO}#42", "token": "ignored-token"}),
    ("inspect_issue", {"target": "https://github.com/example/project/pull/42"}),
    ("inspect_issue", {"target": "https://other.invalid/example/project/issues/42"}),
    ("inspect_issue", {"target": f"{REPO}#0"}),
    ("inspect_issue", {"target": [f"{REPO}#42"]}),
    ("inspect_issue", {"target": "x" * 2049}),
    ("scan_repository", {"repository": f"{REPO}#42"}),
    ("scan_repository", {"repository": "../project"}),
    ("scan_repository", {"repository": REPO, "output": "report.json"}),
]
INVALID += [
    (name, {target: value, field: raw})
    for name, target, value, field, maximum in (
        ("inspect_issue", "target", f"{REPO}#42", "max_prs", 20),
        ("scan_repository", "repository", REPO, "max_prs", 20),
        ("scan_repository", "repository", REPO, "limit", 10),
    )
    for raw in (True, False, 1.0, "1", None, 0, maximum + 1)
]
INVALID += [
    ("inspect_issue", {"target": f"{REPO}#42", "actor": raw})
    for raw in (True, 7, "", " two", "two words", "Contributor\n", "a_b", "a/b", "a" * 101)
]


@pytest.mark.parametrize("name,arguments", INVALID)
def test_invalid_tool_arguments_are_rejected_before_factory_and_reads(name, arguments):
    calls = []

    def factory():
        calls.append("factory")
        raise AssertionError("Invalid arguments reached the API factory")

    async def scenario():
        async with Client(create_server(factory)) as client:
            result = await client.call_tool(name, arguments)
            assert result.is_error is True
            assert result.structured_content is None
            assert text(result)
            assert not calls

    run(scenario)


def test_unknown_tool_is_an_error_without_constructing_api():
    calls = []

    async def scenario():
        async with Client(create_server(lambda: calls.append("factory"))) as client:
            result = await client.call_tool("run_shell", {"command": "ignored"})
            assert result.is_error is True
            assert result.structured_content is None
            assert not calls

    run(scenario)


@pytest.mark.parametrize("max_prs,limit", [(1, 1), (20, 10)])
def test_valid_numeric_boundaries_and_bot_actor_are_accepted(max_prs, limit):
    api = ScanAPI([[issue(1)]])

    async def scenario():
        async with Client(create_server(lambda: api)) as client:
            report = assert_complete(
                await client.call_tool(
                    "scan_repository",
                    {
                        "repository": REPO,
                        "actor": "github-actions[bot]",
                        "max_prs": max_prs,
                        "limit": limit,
                    },
                ),
                batch=True,
            )
            assert (report["max_prs"], report["limit"]) == (max_prs, limit)
            assert report["actor"] == "github-actions[bot]"
            assert "user" not in api.calls

    run(scenario)


def test_repeated_calls_use_fresh_api_and_authenticated_identity():
    created = []

    class RestrictedAPI(ScanAPI):
        def get(self, endpoint):
            value = super().get(endpoint)
            if endpoint == f"repos/{REPO}":
                value["pull_request_creation_policy"] = "collaborators_only"
                value["permissions"] = {"push": self.user["login"] == "Bob"}
            return value

    def factory():
        api = RestrictedAPI([[issue(1)]])
        api.user = {"login": "Alice" if not created else "Bob"}
        created.append(api)
        return api

    async def scenario():
        async with Client(create_server(factory)) as client:
            assert not created
            reports = []
            for target in (f"{REPO}#1", f"https://github.com/{REPO}/issues/1"):
                reports.append(
                    assert_complete(await client.call_tool("inspect_issue", {"target": target}))
                )
            assert [report["actor"] for report in reports] == ["Alice", "Bob"]
            assert [report["repository_access"]["actor_write_access"] for report in reports] == [
                False,
                True,
            ]
            assert [report["decision"] for report in reports] == ["hold", "no_obvious_blockers"]
            assert len(created) == 2
            assert created[0] is not created[1]
            assert [api.calls.count("user") for api in created] == [2, 2]

    run(scenario)


@pytest.mark.parametrize("exception", [RuntimeError, ValueError, OSError])
def test_unexpected_factory_errors_do_not_expose_original_text(exception):
    def factory():
        raise exception(PRIVATE)

    async def scenario():
        async with Client(create_server(factory)) as client:
            result = await client.call_tool("inspect_issue", {"target": f"{REPO}#42"})
            assert result.is_error is True
            assert result.structured_content is None
            assert PRIVATE not in text(result)
            assert "unexpectedly" in text(result)

    run(scenario)


class FaultAPI(ScanAPI):
    def __init__(self, endpoint, exception):
        super().__init__([[issue(1), issue(2)]])
        self.fault_endpoint = endpoint
        self.exception = exception

    def get(self, endpoint):
        if endpoint == self.fault_endpoint:
            self.calls.append(endpoint)
            raise self.exception(PRIVATE)
        return super().get(endpoint)


@pytest.mark.parametrize("exception", [ValueError, RuntimeError])
@pytest.mark.parametrize("endpoint", [f"repos/{REPO}", "user"])
def test_unexpected_required_and_optional_gets_are_sanitized(endpoint, exception):
    api = FaultAPI(endpoint, exception)

    async def scenario():
        async with Client(create_server(lambda: api)) as client:
            result = await client.call_tool("inspect_issue", {"target": f"{REPO}#1"})
            assert PRIVATE not in text(result)
            assert PRIVATE not in json.dumps(result.structured_content)
            if endpoint == "user":
                report = assert_complete(result)
                assert report["actor"] is None
                assert report["decision"] == "review"
                assert report["collection_gaps"]
            else:
                assert result.is_error is True
                assert result.structured_content is None

    run(scenario)


@pytest.mark.parametrize("exception", [ValueError, RuntimeError])
def test_unexpected_batch_get_preserves_partial_report_without_private_error(exception):
    api = FaultAPI(f"repos/{REPO}/issues/2", exception)

    async def scenario():
        async with Client(create_server(lambda: api)) as client:
            result = await client.call_tool("scan_repository", {"repository": REPO})
            report = assert_complete(result, batch=True)
            assert report["summary"]["errors"] == 1
            assert report["results"][0]["status"] == "inspected"
            assert report["results"][1]["status"] == "error"
            assert PRIVATE not in json.dumps(report)
            assert PRIVATE not in text(result)

    run(scenario)


def test_real_github_adapter_sanitizes_denial_before_tool_error(monkeypatch):
    commands = []
    monkeypatch.setattr(github.shutil, "which", lambda _: "/fake/gh")

    def denied(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=1, stdout="", stderr=f"HTTP 403 {PRIVATE}")

    monkeypatch.setattr(github.subprocess, "run", denied)

    async def scenario():
        async with Client(create_server()) as client:
            result = await client.call_tool(
                "inspect_issue", {"target": f"{REPO}#42", "actor": "Contributor"}
            )
            assert result.is_error is True
            assert "GitHub denied" in text(result)
            assert PRIVATE not in text(result)

    run(scenario)
    assert commands
    assert all(command[command.index("--method") + 1] == "GET" for command in commands)


def test_real_stdio_legacy_roundtrip_validation_freshness_and_clean_shutdown(tmp_path):
    project = Path(__file__).resolve().parents[1]
    harness = tmp_path / "fixture_stdio.py"
    harness.write_text(
        "import asyncio\n"
        "from mcp.server.stdio import stdio_server\n"
        "from issue_preflight.mcp import create_server\n"
        "from test_scan import ScanAPI, issue\n"
        "count = 0\n"
        "def factory():\n"
        "    global count\n"
        "    count += 1\n"
        "    api = ScanAPI([[issue(1)]])\n"
        "    api.user = {'login': 'Account' + str(count)}\n"
        "    api.issues[1] = issue(1)\n"
        "    api.issues[1]['state'] = 'closed'\n"
        "    return api\n"
        "async def serve():\n"
        "    server = create_server(factory)\n"
        "    async with stdio_server() as (read, write):\n"
        "        await server.run(read, write, server.create_initialization_options())\n"
        "asyncio.run(serve())\n"
    )
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(harness)],
        cwd=str(project),
        env={"PYTHONPATH": os.pathsep.join([str(project / "src"), str(project / "tests")])},
    )

    async def scenario():
        async with Client(parameters, mode="legacy", cache=None, read_timeout_seconds=10) as client:
            tools = await client.list_tools()
            assert {tool.name for tool in tools.tools} == {"inspect_issue", "scan_repository"}
            invalid = await client.call_tool(
                "inspect_issue", {"target": f"{REPO}#1", "max_prs": 1.0}
            )
            assert invalid.is_error is True
            for expected in ("Account1", "Account2"):
                report = assert_complete(
                    await client.call_tool("inspect_issue", {"target": f"{REPO}#1"})
                )
                assert report["decision"] == "hold"
                assert report["actor"] == expected
                assert report["repository_access"]["has_pull_requests"] is True

    run(scenario)
