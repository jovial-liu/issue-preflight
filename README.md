# Issue Preflight

**Check the evidence before your coding agent starts a GitHub contribution.**

[简体中文](README.zh-CN.md)

An open issue can already have a fix, be assigned to someone else, or belong to a project that requires maintainer approval before accepting a PR. Issue Preflight reads GitHub discussions, related PRs, and contribution guides, then produces a source-linked Markdown or JSON report.

It runs locally, uses your existing `gh` login, and has **no Python runtime dependencies**. No LLM API key is needed. All GitHub requests are GET requests.

## Quick start

Requires Python 3.10+ and [GitHub CLI](https://cli.github.com/). The first example also uses [pipx](https://pipx.pypa.io/stable/installation/); the virtual-environment alternative below needs neither pipx nor Git.

```bash
gh auth login
pipx install https://github.com/jovial-liu/issue-preflight/releases/download/v0.1.3/issue_preflight-0.1.3-py3-none-any.whl
issue-preflight 'modelcontextprotocol/python-sdk#3656'
```

Alternatively, install in a Python virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install https://github.com/jovial-liu/issue-preflight/releases/download/v0.1.3/issue_preflight-0.1.3-py3-none-any.whl
python -m issue_preflight 'OWNER/REPO#123'
```

## What it checks

| Evidence | What the report tells you |
| --- | --- |
| Issue state and assignees | Whether the issue is closed or someone is already assigned |
| PRs in the timeline, discussion links, and search | Which proposals might overlap, including closed PRs |
| Explicit closing references | Whether a PR says it fixes this exact issue; `#12` does not match `#123` |
| Contribution guides, `AGENTS.md`, and linked policies | Recognizable assignment, proposal approval, AI disclosure, and autonomous-agent rules |
| Maintainer messages | Whether a maintainer explicitly says not to open another PR |
| Collection limits and API failures | Where the evidence is incomplete |

Contribution files are read at one pinned commit. Detected policy rules include exact line links and bounded original excerpts. Issues and discussions are a timestamped live snapshot and can change during the scan. The CLI evaluates your authenticated `gh` user by default; use `--actor LOGIN` to evaluate someone else. Identity lookup failures appear as collection gaps.

The scan starts with `CONTRIBUTING.md`, `.github/CONTRIBUTING.md`, and `AGENTS.md`, then follows recognizable explicit links to AI, agent, and contribution policies, including reference-style links. Supported text targets in the same repository can use relative paths, parent directories within the repository, root paths, or GitHub `blob` URLs. Every fetched file uses the report's pinned commit, including links written with an older branch or SHA. The budget is **six contents requests total**, including default probes, missing files, and failed requests. Explicit linked files that are missing, inaccessible, unsupported, external, or ambiguous appear as collection gaps.

An `approval_policy` finding has severity `review`: a detected rule requires a PR to link an issue or discussion containing a maintainer-approved solution. Read the quoted rule and its scope, which may specifically cover AI-generated contributions. The scan does not verify whether an approved solution already exists.

## Real examples

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

## Limits

Policy detection is heuristic and currently recognizes English phrasing. Contribution rules can live outside the checked paths, a quoted rule can be ambiguous, and trusted-contributor exceptions may require a maintainer's judgment. Common code examples and HTML comments are excluded, but text handling and link discovery are not a complete Markdown parser. A `blob` URL with an unknown ref and a nested file path may be ambiguous; it is reported as a gap. Closing references show stated intent; automatic closure also depends on GitHub's default-branch rules.

PR search discovers references, not semantic equivalence; a differently worded competing fix can be missed. This REST scan does not resolve current manual links in the Development sidebar or infer fixes from commit messages. Manual-link events are reported as collection gaps. Read the sources rather than treating any decision as a guarantee of completeness or acceptance.

GitHub authentication remains managed by `gh`. The tool does not create issues, comments, branches, or PRs. Reports can contain private repository metadata if you scan a private repo; choose where to save and share them.

## Develop

```bash
git clone https://github.com/jovial-liu/issue-preflight.git
cd issue-preflight
python -m pip install -e . pytest ruff build
python -m pytest -q
ruff check .
ruff format --check .
python -m build
```

Tests exercise number collisions, cross-repo references, closed versus merged PRs, assignment exceptions, partial API failures, collection caps, and read-only subprocess behavior without network access. CI covers Linux and Windows on Python 3.10, 3.12, and 3.14.

Contributions are welcome: include a reproduction or a small anonymized fixture for any classification error. Prepared with OpenAI Codex; maintained by [jovial-liu](https://github.com/jovial-liu).

MIT licensed.
