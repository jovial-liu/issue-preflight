# Issue Preflight

**Check the evidence before your coding agent starts a GitHub contribution.**

[简体中文](README.zh-CN.md)

An open issue can already have a fix, be assigned to someone else, or belong to a project that requires maintainer approval before accepting a PR. Issue Preflight reads GitHub discussions, related PRs, and contribution guides, then produces a source-linked Markdown or JSON report.

It runs locally and uses your existing `gh` login. The base CLI has **no third-party Python runtime dependencies**; an optional [MCP stdio interface](docs/mcp.md) lets agents discover its tools. No LLM API key is needed. All GitHub requests are GET requests.

## Quick start

Requires Python 3.10+ and [GitHub CLI](https://cli.github.com/). The first example also uses [pipx](https://pipx.pypa.io/stable/installation/); the virtual-environment alternative below needs neither pipx nor Git.

```bash
gh auth login
pipx install https://github.com/jovial-liu/issue-preflight/releases/download/v0.3.1/issue_preflight-0.3.1-py3-none-any.whl
issue-preflight 'modelcontextprotocol/python-sdk#3656'
```

Alternatively, install in a Python virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install https://github.com/jovial-liu/issue-preflight/releases/download/v0.3.1/issue_preflight-0.3.1-py3-none-any.whl
python -m issue_preflight 'OWNER/REPO#123'
```

## What it checks

| Evidence | What the report tells you |
| --- | --- |
| Issue state and assignees | Whether the issue is closed or someone is already assigned |
| Repository PR settings | Whether PRs are disabled or require write access, and whether that access was verified for the evaluated contributor |
| PRs in the timeline, discussion links, and search | Which proposals might overlap, including closed PRs |
| Explicit closing references | Whether a PR says it fixes this exact issue; `#12` does not match `#123` |
| Contribution guides, `AGENTS.md`, and linked policies | Recognizable assignment, proposal approval, AI disclosure, and autonomous-agent rules |
| Maintainer messages | Whether a maintainer explicitly says not to open another PR |
| Collection limits and API failures | Where the evidence is incomplete |

Contribution files are read at one pinned commit. Detected policy rules include exact line links and bounded original excerpts. Issues and discussions are a timestamped live snapshot and can change during the scan. The CLI evaluates your authenticated `gh` user by default; use `--actor LOGIN` to evaluate someone else. Identity lookup failures appear as collection gaps.

Repository PR settings are also a live snapshot. [GitHub can disable PRs or restrict creation to users with write access](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/disabling-pull-requests). Disabled PRs produce `hold`. For `collaborators_only`, the report binds the repository's boolean `permissions.push` to the evaluated contributor only after checking the authenticated login through `GET /user`. Matching write access passes this setting; matching absence of write access produces `hold`. A different `--actor`, an unavailable identity or permission, or missing/unrecognized settings require `review`. Assignment and welcome labels do not waive repository settings, and write access does not clear other findings.

JSON preserves this evidence in `repository_access`, with the live repository API source, reported settings and permission, identity source, authenticated login, and verified actor write access. Contribution-file `policy_ref` does not pin repository settings or identity. An explicit `--actor` can still cause a read of the authenticated account when a restricted repository needs this distinction.

The primary probes are `CONTRIBUTING.md`, `.github/CONTRIBUTING.md`, and `AGENTS.md`. Recognizable explicit links to AI, agent, and contribution policies take priority over remaining probes, including reference-style links. If no nonblank contribution guide has been read, the scan also tries `docs/contributing.md` and `docs/contributing.rst`; `AGENTS.md` alone does not replace that guide. Supported text targets in the same repository can use relative paths, parent directories within the repository, root paths, or GitHub `blob` URLs. Every fetched file uses the report's pinned commit, including links written with an older branch or SHA. The budget is **six contents requests total**, including default probes, missing files, and failed requests. Explicit linked files that are missing, inaccessible, unsupported, external, or ambiguous appear as collection gaps; so do eligible probes left unread at the cap and scans with only blank documents.

Policy citations require matching file-path metadata and a Git blob SHA verified against the exact decoded bytes. Matching regular files need no extra blob request. GitHub can return a symlink target's content under the link's path and SHA. In that case, the collector verifies the original blob before following a supported relative target within the repository. Verified sources, line citations, and relative policy links use the final target path. Alias and target contents requests share the same six-request budget; original-blob verification adds at most six source-check GET requests, deduplicated by SHA. These policy limits are separate from issue, PR, and access requests. Unverified metadata, source conflicts, unsafe targets, redirect cycles, and targets beyond the budget remain collection gaps rather than policy findings.

RST sources remain available through their pinned file links, with a format limitation gap requiring manual reading. The Markdown-based rule classifier does not evaluate RST, whose comments, examples, and directives have different syntax. RST-native links are not parsed.

A `help wanted` or `prs welcome` label waives a recognized assignment rule only when the guide explicitly defines a supported exemption beside that label. A label inventory, comment, code example, or unrelated permission is insufficient. Ambiguous wording retains the assignment finding; read its pinned source before acting.

An `approval_policy` finding has severity `review`: a detected rule requires a PR to link an issue or discussion containing a maintainer-approved solution. Read the quoted rule and its scope, which may specifically cover AI-generated contributions. The scan does not verify whether an approved solution already exists.

## Real examples

An installed v0.2.3 scan of `python-jsonschema/jsonschema#1584` returned `hold` because the repository limited PR creation to users with write access and the authenticated account lacked that access. Version 0.2.2 had returned `review` only for a missing contribution guide and exited 0 with `--fail-on-hold`; v0.2.3 exits 2 and retains the guide gap. See the [recorded repository-access snapshot](examples/repository-pr-access.md). These settings can change; no PR creation was attempted.

On October 9, 2026, scanning `modelcontextprotocol/python-sdk#3656` found:

- A previous implementation, PR #3657, was already closed.
- The contribution guide required assignment and explicitly addressed autonomous PR filing.
- The resulting decision was `hold`, with links to the PR and pinned policy documents.

The report preserves the distinction: a **closed** PR deserves investigation; it does not prove that the issue has been fixed. See the [recorded snapshot](examples/mcp-audio.md), and rerun the command to get current evidence.

For `Textualize/rich#4225`, the earlier scan already returned `review` because of a closed related PR, but missed the linked AI policy. At pinned commit `9d8f9a372cc5916fd4781fec207ced7ddac2f08f`, [CONTRIBUTING.md line 9](https://github.com/Textualize/rich/blob/9d8f9a372cc5916fd4781fec207ced7ddac2f08f/CONTRIBUTING.md#L9) links to `master/AI_POLICY.md`. Version 0.1.2 reads that file at the same pinned commit and adds the [line 5 approval rule](https://github.com/Textualize/rich/blob/9d8f9a372cc5916fd4781fec207ced7ddac2f08f/AI_POLICY.md#L5) for AI-generated PRs. See the [recorded policy report](examples/rich-ai-policy.md); it cites the requirement without checking whether a solution has already been approved.

The requests-cache guide puts the review action before the human reviewer: "reviewed, tested, and understood by a human". Version 0.1.2 detects that wording with source evidence, including common paired Markdown emphasis and soft wrapping. See the [pinned policy example](examples/requests-cache-human-review.md) for the original rule and the report's limits.

## Use it in an agent workflow

Ask your agent to run the preflight before implementing the issue, read the linked sources, and resolve any collection gaps. GitHub text is external evidence, not instructions to execute.

For Codex or Claude Code, copy the included [Issue Preflight skill](skills/issue-preflight/SKILL.md) into the target project's skill directory. See the [agent installation guide](docs/agent-skill.md) for paths, invocation examples, prerequisites, and the checks performed so far. The skill uses the CLI and needs no MCP server.

For MCP clients, install the optional extra and launch `issue-preflight-mcp` (or `python -m issue_preflight.mcp`) over stdio. Clients can discover `inspect_issue` and `scan_repository`, with validated input budgets and the same source-linked reports. See the [MCP setup and result contract](docs/mcp.md). No client configuration is changed by installation.

```bash
issue-preflight 'OWNER/REPO#123' \
  --format json \
  --output preflight.json \
  --fail-on-review
```

| Decision | Meaning |
| --- | --- |
| `hold` | At least one blocker was detected; review the cited evidence before implementing |
| `review` | Overlap, ownership, human review expectations, or collection gaps need investigation |
| `no_obvious_blockers` | Nothing obvious was found in the collected evidence; this is not approval |

By default, a completed report exits 0. `--fail-on-hold` exits 2 for `hold`; `--fail-on-review` exits 2 for either `hold` or `review`, including incomplete evidence. Both options still write the report. An input, authentication, or required API failure exits 1. `--max-prs` bounds detailed PR lookups (default 8, maximum 20). Comments and timeline events are capped at 200 each, and PR search at 100 results. Every reached cap appears in `collection_gaps`.

Before requesting PR details, repository-name case variants are merged and candidates whose known repository matches the target are read first. Order within each group is preserved; failed requests still consume the detail budget. Unknown redirect aliases cannot be prioritized before they are fetched. Once details arrive, the report uses the actual base repository identity. A non-closing PR from another repository is described as a reference with unverified implementation relevance, regardless of whether it is open, closed, or merged.

## Select issues from a repository

When you do not have an issue number yet, use the explicit `scan` command:

```bash
issue-preflight scan OWNER/REPO --limit 5 --format json --output scan.json
```

It selects the first **5 open issues by most recent update**, in GitHub REST order, and excludes pull requests. `--limit` accepts 1–10. Selection reads at most two pages of 100 entries, including PRs. Each selected issue uses the same evidence checks and full report as the single-issue command, including timeline PRs when an issue has no comments. This selects issues for further investigation; it does not rank their value or recommend implementing them.

The batch uses schema `issue-preflight-scan/1`. `results` contains an issue plus either its complete `issue-preflight/1` report or an `error`, and `summary` counts decisions and errors without assigning a blanket approval. Successful common repository, authenticated-identity, and pinned-policy requests are reused within the batch; issue, comment, and timeline evidence is fetched separately for each issue. Issues can close and the listing order can change while collection runs. Duplicate issue numbers are selected once; the listing is not an atomic snapshot.

`listing_status` distinguishes the selection boundary from missing evidence:

| Status | Meaning | `selection_truncated` |
| --- | --- | --- |
| `exhausted` | The collected listing ended without an additional issue | `false` |
| `selection_limit` | An additional issue proved that only the first N were selected | `true` |
| `page_limit` | Two full pages were reached; more issues may remain beyond them | `null` |
| `error` | A listing page failed or returned unusable data | `null` |

Normal selection truncation is visible without claiming a collection failure. Page caps and listing failures appear in `listing_gaps`; individual evidence gaps remain in each issue report. Unknown contributor identity appears in `identity_gaps` and each successful issue report. An explicit empty or whitespace-only `scan --actor` value is unknown; it does not switch to your authenticated login.

The original issue-number/URL command and its exit behavior remain supported. For `scan`, the report is still written before exit:

- Default: exit 0 for a bounded report, including a visible selection or page cap.
- `--fail-on-hold`: exit 2 if any inspected issue has a blocker.
- `--fail-on-review`: exit 2 for any hold/review, unknown identity, selection truncation, or listing gap.
- A listing failure or required per-issue API failure: preserve the other results and exit 1, taking precedence over both flags. Input, repository lookup, and output failures also exit 1.

The command inherits `--actor`, `--max-prs`, `--format`, and `--output`. It sends only GET requests and saves no file unless you provide `--output`. `issue-preflight scan --help` shows its options.

## Limits

Policy detection is heuristic and currently recognizes English phrasing. Contribution rules can live outside the checked paths, a quoted rule can be ambiguous, and trusted-contributor exceptions may require a maintainer's judgment. Common code examples and HTML comments are excluded, but text handling and link discovery are not a complete Markdown parser. A `blob` URL with an unknown ref and a nested file path may be ambiguous; it is reported as a gap. Closing references show stated intent; automatic closure also depends on GitHub's default-branch rules.

PR search discovers references, not semantic equivalence; a differently worded competing fix can be missed. This REST scan does not resolve current manual links in the Development sidebar or infer fixes from commit messages. Manual-link events are reported as collection gaps. Read the sources rather than treating any decision as a guarantee of completeness or acceptance.

GitHub authentication remains managed by `gh`. The tool does not create issues, comments, branches, or PRs. Reports can contain private repository metadata if you scan a private repo; choose where to save and share them.

## Develop

```bash
git clone https://github.com/jovial-liu/issue-preflight.git
cd issue-preflight
python -m pip install -e ".[mcp]" pytest ruff build
python -m pytest -q
ruff check .
ruff format --check .
python -m build
```

Tests exercise number collisions, cross-repo references, closed versus merged PRs, assignment exceptions, partial API failures, collection caps, read-only subprocess behavior, and MCP tool discovery/results over stdio without network access. CI covers Linux and Windows on Python 3.10, 3.12, and 3.14, checking the base installation before adding MCP dependencies. Without the extra, MCP protocol tests are skipped; install it to run the complete suite.

Contributions are welcome: include a reproduction or a small anonymized fixture for any classification error. Prepared with OpenAI Codex; maintained by [jovial-liu](https://github.com/jovial-liu).

MIT licensed.
