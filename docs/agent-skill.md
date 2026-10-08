# Use Issue Preflight with a coding agent

The [Issue Preflight skill](../skills/issue-preflight/SKILL.md) calls the existing CLI before an agent implements a GitHub issue. It uses the same GitHub CLI login as the command line and needs no MCP server or LLM API key.

Install the CLI first using the project's [quick start](https://github.com/jovial-liu/issue-preflight#quick-start). The skill requires Issue Preflight 0.1.2 or newer, Python 3.10+, and an authenticated `gh` in the agent's execution environment. Confirm that `issue-preflight --help` includes `--fail-on-review`. Installing a skill alone does not install the CLI or configure GitHub authentication.

Copy the same `skills/issue-preflight` folder from this checkout into your target project's skill directory. Keep the enclosing `issue-preflight` directory and its `SKILL.md` file:

| Agent | Project location | Explicit invocation |
| --- | --- | --- |
| Codex CLI / IDE | `.agents/skills/issue-preflight/SKILL.md` | `$issue-preflight Textualize/rich#4225` |
| Claude Code | `.claude/skills/issue-preflight/SKILL.md` | `/issue-preflight Textualize/rich#4225` |

Codex and Claude Code document these respective discovery paths and invocation forms. See [OpenAI's skills guide](https://learn.chatgpt.com/docs/build-skills) and [Claude Code's skills guide](https://code.claude.com/docs/en/skills). The skill uses only shared `name` and `description` metadata, without host-specific argument expansion or permission configuration. If it does not appear, inspect the client's skill list and discovery settings. Other agents can read the same instructions and run the CLI; their installation paths are not specified here.

The command used by the skill is:

```bash
issue-preflight 'OWNER/REPO#123' --format json --fail-on-review
```

Exit 2 still returns the JSON report: `hold` or `review` needs investigation. Exit 0 means no obvious blockers were found in the collected evidence. Exit 1 reports a failed scan on stderr. A preflight result does not establish permission or maintainer approval.

To check a client installation, invoke the skill explicitly and ask it to **only inspect the issue, without implementing or posting anything**. Confirm that it runs the command, reads its JSON even when the exit code is 2, and returns source links and unresolved gaps. Check that no contribution or code change was created. This verifies the client's behavior, beyond the CLI and skill file's static checks.

Validation so far: the Skill Creator validator accepted the skill, current command help matches the documented flags, and offline fixtures exercised exits 0, 2, and 1. A separate read-only inspection using the released 0.1.2 wheel on [urllib3 issue #3676](https://github.com/urllib3/urllib3/issues/3676) read the valid `issue-preflight/1` JSON after exit 2, checked the competing PRs, and investigated a missing-policy gap. This was an agent following the file's instructions with the CLI. Codex and Claude Code skill discovery and invocation have not been tested.
