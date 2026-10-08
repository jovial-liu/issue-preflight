This snapshot was collected with the installed v0.2.3 wheel, using `gh` account `jovial-liu`. Repository settings and authenticated permissions are live evidence; rerun the CLI for current values.

The installed v0.2.2 wheel returned `review` for this issue because no contribution guide was collected, but omitted the PR creation restriction and exited 0 with `--fail-on-hold`. Version 0.2.3 returns `hold` and exits 2 with the same flag: the repository reports `collaborators_only`, and the evaluated authenticated account lacks the required write access. The contribution-guide collection gap remains visible. No PR creation was attempted.

# python-jsonschema/jsonschema#1584

Iterator error contexts lose parent links and absolute paths

Decision: **hold**

Contributor evaluated: jovial-liu

[Issue](https://github.com/python-jsonschema/jsonschema/issues/1584) · Evidence collected: 2026-10-08T20:42:57.280638+00:00

Heuristic evidence review, not maintainer approval or a guarantee of complete discovery.

## Findings

- **blocker**: Repository restricts PR creation to users with write access. The authenticated contributor lacks the required write access. ([source](https://api.github.com/repos/python-jsonschema/jsonschema))

  > pull\_request\_creation\_policy: collaborators\_only

- **review**: Some evidence was not collected. Review collection gaps. ([source](https://github.com/python-jsonschema/jsonschema/issues/1584))

## Pull requests

No candidates discovered by this bounded scan. This does not prove no competing work exists.

## Repository PR access

- Pull requests: enabled (reported: true)
- Creation policy: `collaborators_only` (reported: "collaborators\_only")
- Authenticated account write permission reported by API: false
- Write access for evaluated contributor: no

[Live repository API](https://api.github.com/repos/python-jsonschema/jsonschema)
Authenticated account checked: jovial-liu ([identity source](https://api.github.com/user))

These settings are a live snapshot; the policy commit does not pin them.

## Contribution policies

Pinned commit: `c497561ea0a95f5aac09cd63d15eb1420eb7bbec`


## Collection gaps

- No contribution policy was found in the checked paths; rules may live elsewhere.
