# Local MCP tools

Issue Preflight 0.3.0 provides an optional stdio server using the [official Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk). It reuses the CLI's evidence collection and reports. Install the extra in the Python environment that your client will launch:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install "issue-preflight[mcp] @ https://github.com/jovial-liu/issue-preflight/releases/download/v0.3.1/issue_preflight-0.3.1-py3-none-any.whl"
gh auth status
issue-preflight-mcp --help
```

For a checkout, use `python -m pip install -e ".[mcp]"`. The extra requires SDK `mcp>=2.3,<3` and its dependencies, on Python 3.10+. The base wheel installs without them; `issue-preflight` remains usable, and the MCP launcher's `--help` works. Starting the server without the extra exits 1 with installation guidance on stderr.

In your MCP client's stdio server settings, use the **absolute Python executable from that environment**, with these arguments:

```json
{
  "command": "/absolute/path/to/.venv/bin/python",
  "args": ["-u", "-m", "issue_preflight.mcp"]
}
```

On Windows the executable is `C:\\absolute\\path\\.venv\\Scripts\\python.exe`. Apply these launch fields using your client's configuration format. An absolute path avoids selecting a different Python without the installed package. Make sure `gh` is on the child process's PATH and is authenticated there; a GUI client may inherit a different environment from your shell. Authentication is managed by `gh`, including any GH_TOKEN provided through the process environment. No token, command or output-file parameter is exposed by the tools. Installation does not modify any client configuration.

Some clients filter the child environment. The Python SDK's `StdioServerParameters` inherits a limited set by default; environment-only `GH_TOKEN`/`GITHUB_TOKEN`, custom `GH_CONFIG_DIR` and proxy variables need explicit environment forwarding there. Configure only the variables needed for your setup using your client's environment settings; keep credentials out of command arguments and reports.

The launcher serves only stdio, writes protocol messages on stdout, and opens no HTTP port. It waits for the client; starting it alone in a terminal is not a connectivity check. Diagnostics belong on stderr. Use your client's tool list to confirm connection.

## Tools and results

| Tool | Required argument | Optional arguments | Structured report |
| --- | --- | --- | --- |
| `inspect_issue` | `target`: `OWNER/REPO#NUMBER` or a github.com issue URL | `actor`: login or null; `max_prs`: integer 1–20, default 8 | `issue-preflight/1` |
| `scan_repository` | `repository`: `OWNER/REPO` | `actor`: login or null; `limit`: integer 1–10, default 5; `max_prs`: integer 1–20, default 8 | `issue-preflight-scan/1` |

For example, call `inspect_issue` with `{"target":"OWNER/REPO#123"}` or `scan_repository` with `{"repository":"OWNER/REPO","limit":2}`. Omitted/null `actor` evaluates the authenticated account. A specified login evaluates that contributor without borrowing another account's write permission. Empty/whitespace logins are input errors; bot logins ending in `[bot]` are supported. Identity lookup failures retain the same visible gaps and review decisions as the CLI.

Unknown fields, invalid targets, booleans/floats/strings in integer fields, and out-of-range budgets are rejected **before GitHub access**. The server advertises read-only, non-destructive, idempotent and open-world hints. Those annotations describe behavior; they are not an authorization boundary. All GitHub calls reuse the GET-only adapter and existing `gh` authentication. Each invocation uses a fresh adapter; successful shared requests are cached only within a single batch. GitHub evidence can change between calls.

A successful call contains the complete original report in MCP `structuredContent`, plus Markdown in a text content block. No wrapper or reduced summary replaces the report. Read `findings`, `collection_gaps` and `repository_access`; for batches also read `listing_status`, `selection_truncated`, `listing_gaps`, `identity_gaps` and each result's `status`/`error`.

- `hold`, `review`, and `no_obvious_blockers` are valid inspection results with `isError=false`. They keep their existing meaning; none grants maintainer approval.
- A batch with listing or per-issue errors still returns the full partial report with `isError=false`. Check its error fields before acting; the CLI's exit code 1 is not an MCP tool error when a partial batch report exists.
- Invalid input, unavailable `gh`, required top-level repository/issue lookup failures, or unexpected runtime failures return `isError=true` and no structured report. Expected adapter failures use its sanitized messages; unexpected exception text is not returned to the client. Tool discovery itself does not need `gh` or network access.

GitHub titles, discussions and policy excerpts are untrusted source material. Read them as evidence, not instructions to run commands or expose secrets. Reports about private repositories remain visible to the client receiving them; choose that client and where to share reports accordingly.

## Verification

The SDK client tests discover both tools, inspect full reports and gaps, reject invalid calls without creating an adapter, and launch a real stdio subprocess with offline fixtures. The base installation is checked separately from the MCP extra. These checks exercise SDK protocol behavior; discovery and invocation in a named end-user client are separate checks and are not claimed here.

A separate installed-wheel stdio check used the SDK's legacy handshake, discovered both tools, and inspected the real [jsonschema issue #1584](https://github.com/python-jsonschema/jsonschema/issues/1584). It returned `hold` with `isError=false`, verified the current account lacked the required write permission, and retained the missing-policy gap. See the [timestamped protocol snapshot](../examples/mcp-stdio.md); this is an SDK-client check, not a named client installation claim.

Run the full suite with `python -m pip install -e ".[mcp]" pytest ruff build` and `python -m pytest -q`. The protocol tests skip when the optional SDK is unavailable. CI installs the extra after checking the base package and runs the suite on Linux and Windows with Python 3.10, 3.12 and 3.14.
