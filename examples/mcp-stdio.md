# Installed-wheel MCP stdio check

At `2026-10-08T21:16:44.843612+00:00`, an isolated Python 3.12 environment ran Issue Preflight 0.3.0 from its built wheel with official MCP SDK 2.3.0. The SDK client launched `python -u -m issue_preflight.mcp` as a real subprocess, using `mode="legacy"` to exercise the initialize handshake.

The client discovered exactly `inspect_issue` and `scan_repository`. Both advertised bounded inputs, rejection of additional parameters and read-only annotations. The successful real invocation was:

```json
{"target":"python-jsonschema/jsonschema#1584","max_prs":1}
```

The complete returned `structuredContent` used schema `issue-preflight/1`; the accompanying Markdown agreed on `hold`. This excerpt records the decision and access fields:

```json
{
  "schema": "issue-preflight/1",
  "repository": "python-jsonschema/jsonschema",
  "actor": "jovial-liu",
  "decision": "hold",
  "policy_ref": "c497561ea0a95f5aac09cd63d15eb1420eb7bbec",
  "repository_access": {
    "source": "https://api.github.com/repos/python-jsonschema/jsonschema",
    "has_pull_requests": true,
    "pull_request_creation_policy": "collaborators_only",
    "permissions_push": false,
    "authenticated_user": "jovial-liu",
    "identity_source": "https://api.github.com/user",
    "actor_write_access": false
  },
  "collection_gaps": [
    "No contribution policy was found in the checked paths; rules may live elsewhere."
  ]
}
```

The MCP result had `isError=false`: a blocker is a successful evidence inspection. An additional call with boolean `limit=true` returned `isError=true` and no structured report. Authentication remained with `gh`; no contribution was posted.

Repository settings and identity are live evidence; `policy_ref` pins only contribution files. This snapshot can become stale. It verifies SDK subprocess discovery and one live issue inspection, not named-client installation, popularity, maintainer approval, or complete competing-work discovery. Batch and invalid-input behavior are also exercised with offline fixtures in the protocol tests.
