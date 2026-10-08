# Changelog

## 0.1.2

- Follow recognizable explicit AI, agent, and contribution policy links, including reference-style links, to supported text files in the same repository.
- Resolve repository-relative, parent-directory, root-path, and supported GitHub `blob` links at the report's pinned commit rather than the link's branch or SHA.
- Report missing, failed, unsupported, external, and ambiguous linked policies as evidence gaps. Limit discovery to six contents requests, including failed requests and default probes.
- Add `approval_policy` review findings with source lines and excerpts when a PR must link a maintainer-approved solution; approval itself is not verified.
- Detect reviewed-by-a-human wording, including coordinated actions, soft wrapping, and common paired Markdown emphasis; preserve original evidence and exclude human-like bot descriptions.
- Incorporate PR #1 with follow-up regression and bounded-input fixes; scan emphasis delimiters once to avoid repeated suffix scans on unmatched input.
- Include a Rich snapshot demonstrating a previously omitted AI policy, and update installation examples to the 0.1.2 wheel.

## 0.1.1

- Report exact pinned policy lines and original text excerpts for detected rules, maintainer stop requests, and existing fix declarations.
- Exclude common fenced, indented, and inline code examples and HTML comments without losing source positions or later real fixes.
- Make unresolved manual-link timeline events visible as evidence gaps.
- Evaluate the authenticated GitHub user by default, display the contributor in Markdown, and report failed identity lookups.
- Add `--fail-on-review` for workflows that must stop on uncertainty as well as blockers.
- Document release-wheel installation without Git and include a virtual-environment alternative in both languages.

## 0.1.0

Initial preview: bounded read-only issue, discussion, PR, and policy collection; Markdown and JSON reports; offline regression tests and Linux/Windows CI.
