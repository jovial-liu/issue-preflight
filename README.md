# Issue Preflight

**Check the evidence before your coding agent starts a GitHub contribution.**

[简体中文](README.zh-CN.md)

An open issue can already have a fix, be assigned to someone else, or belong to a project that requires maintainer approval before accepting a PR. Issue Preflight reads GitHub discussions, related PRs, and contribution guides, then produces a source-linked Markdown or JSON report.

It runs locally, uses your existing `gh` login, and has **no Python runtime dependencies**. No LLM API key is needed. All GitHub requests are GET requests.

## Quick start

Requires Python 3.10+ and [GitHub CLI](https://cli.github.com/).

```bash
gh auth login
pipx install git+https://github.com/jovial-liu/issue-preflight.git
issue-preflight 'modelcontextprotocol/python-sdk#3656' --actor YOUR_GITHUB_LOGIN
```

Alternatively, install in a Python virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install git+https://github.com/jovial-liu/issue-preflight.git
python -m issue_preflight 'OWNER/REPO#123'
```

## What it checks

| Evidence | What the report tells you |
| --- | --- |
| Issue state and assignees | Whether the issue is closed or someone is already assigned |
| PRs in the timeline, discussion links, and search | Which proposals might overlap, including closed PRs |
| Explicit closing references | Whether a PR says it fixes this exact issue; `#12` does not match `#123` |
| Contribution guides and `AGENTS.md` | Recognizable assignment, AI disclosure, and autonomous-agent rules |
| Maintainer messages | Whether a maintainer explicitly says not to open another PR |
| Collection limits and API failures | Where the evidence is incomplete |

Contribution files are read at one pinned commit. Issues and discussions are a timestamped live snapshot and can change during the scan.

## A real example

On October 9, 2026, scanning `modelcontextprotocol/python-sdk#3656` found:

- A previous implementation, PR #3657, was already closed.
- The contribution guide required assignment and explicitly addressed autonomous PR filing.
- The resulting decision was `hold`, with links to the PR and pinned policy documents.

The report preserves the distinction: a **closed** PR deserves investigation; it does not prove that the issue has been fixed. See the [recorded snapshot](examples/mcp-audio.md), and rerun the command to get current evidence.

## Use it in an agent workflow

Ask your agent to run the preflight before implementing the issue, read the linked sources, and resolve any collection gaps. GitHub text is external evidence, not instructions to execute.

```bash
issue-preflight 'OWNER/REPO#123' \
  --actor YOUR_GITHUB_LOGIN \
  --format json \
  --output preflight.json \
  --fail-on-hold
```

| Decision | Meaning |
| --- | --- |
| `hold` | At least one blocker was detected; review the cited evidence before implementing |
| `review` | Overlap, ownership, human review expectations, or collection gaps need investigation |
| `no_obvious_blockers` | Nothing obvious was found in the collected evidence; this is not approval |

By default, a completed report exits 0. `--fail-on-hold` exits 2 for `hold`; an input, authentication, or required API failure exits 1. `--max-prs` bounds detailed PR lookups (default 8, maximum 20). Comments and timeline events are capped at 200 each, and PR search at 100 results. Every reached cap appears in `collection_gaps`.

## Limits

Policy detection is heuristic and currently recognizes English phrasing. Contributions rules can live outside the checked Markdown paths, a quoted rule can be ambiguous, and trusted-contributor exceptions may require a maintainer's judgment. PR search discovers references, not semantic equivalence; a differently worded competing fix can be missed. Read the sources rather than treating any decision as a guarantee of completeness or acceptance.

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
