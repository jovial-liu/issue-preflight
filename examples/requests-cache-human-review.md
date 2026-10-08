# requests-cache: reversed human-review wording

At pinned commit `e7f0f73a8194a89497f41f8556334d8993ebee2a`, [CONTRIBUTING.md line 24](https://github.com/requests-cache/requests-cache/blob/e7f0f73a8194a89497f41f8556334d8993ebee2a/CONTRIBUTING.md#L24) states:

> Contents are fully **reviewed, tested, and understood by a human**

The earlier classifier looked for human-before-review wording and omitted this rule. Version 0.1.2 detects `human_review_policy`, with severity `review`, and preserves line 24 and its original Markdown excerpt. The change originates in [PR #1](https://github.com/jovial-liu/issue-preflight/pull/1), with follow-up fixes for common paired emphasis and human-like bot descriptions.

A live scan of [issue #602](https://github.com/requests-cache/requests-cache/issues/602), collected on 2026-10-08 at 18:25 UTC, returned `review` both before and after this rule was added: related PR references and an external-policy collection gap already needed investigation. The improvement adds missing policy evidence; it does not change that earlier overall decision or establish human approval.

The external policy link remains a visible gap. Issue discussions and PR states can change; rerun the scan for current evidence. The source excerpt is pinned to the commit above.
