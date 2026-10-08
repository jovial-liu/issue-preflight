# Contributing

Issue Preflight needs accurate evidence collection and understandable uncertainty. Bug reports with a repository/issue URL, observed result, expected result, and reproduction are welcome. For private repos, use an anonymized fixture and remove credentials.

Before changing a classifier, add a test for the user-visible false positive or false negative. Preserve the distinction between a related PR and an explicit fix. Any collection cap or failed optional fetch must remain visible in the report. GitHub access must remain read-only.

Run `python -m pytest -q`, `ruff check .`, `ruff format --check .`, and `python -m build` before opening a PR. Keep changes focused. AI assistance is welcome; disclose it and verify the result. Public reports and fixtures must not contain secrets or private conversations.
