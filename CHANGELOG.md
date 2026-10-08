# Changelog

## 0.3.0

- Add an optional local MCP stdio server with `inspect_issue` and `scan_repository` tools, using the official Python SDK 2.3 or newer. The base CLI still has no third-party runtime dependencies.
- Return the existing complete JSON reports alongside Markdown, including identity, permission, collection and batch-error gaps. `hold` and `review` remain successful inspections.
- Reject unknown parameters, invalid targets, incorrect types and out-of-range budgets before looking up GitHub. Use a fresh adapter per tool invocation; authentication stays with `gh` and all requests remain GET.
- Share the existing identity-gap behavior with the CLI and synchronize package/server version metadata.

## 0.2.3

- Check live repository PR settings. Disabled PRs block contributions; restricted creation requires matching authenticated identity and boolean write permission.
- Preserve missing or ambiguous settings/identity/permission as review gaps. Keep reported access fields and sources in JSON and Markdown, and cache only successful common requests within a batch.

## 0.2.2

- Require a visible, explicit assignment exemption before a quoted `help wanted` or `prs welcome` label can waive an assignment rule. Label inventories, comments, code examples, negative conditions, and unrelated permissions retain the blocker.
- Bind exemptions to the stated label and local sentence or table cell. Preserve supported positive inline-code and linked-label wording, case-insensitive assignment, and original source lines.

## 0.2.1

- Try the demonstrated `docs/contributing.md` and `docs/contributing.rst` layouts when no nonblank contribution guide has been read; an agent guide alone does not suppress fallback.
- Prioritize explicit policy links before remaining probes, sharing one six-request budget and preserving missing, failed, and unread-evidence gaps.
- Report whitespace or BOM-only documents as missing readable guidance. Keep original source text and pinned URLs.
- Keep RST sources for manual reading with an explicit format gap, rather than applying Markdown rules to RST comments, examples, and directives.
- Avoid repeated scans of unclosed Markdown labels and long escape runs, remove suffix copies for reference links, and accept CRLF reference definitions.

## 0.2.0

- Add an explicit `scan OWNER/REPO` command that selects up to five recently updated open issues by default (maximum ten), excluding PRs, and reuses the full single-issue evidence checks.
- Distinguish normal selection truncation, listing exhaustion, two-page caps, identity gaps, and API failures. Preserve partial per-issue results with exit 1 for required fetch failures.
- Reuse successful common repository and pinned-policy requests within a batch, retaining read-only access and the existing single-issue CLI.

## 0.1.3

- Use neutral wording for cross-repository non-closing PR references, preserving their sources and states without claiming implementation overlap or a reverse reference.
- Prioritize candidates whose known repository matches the target before bounded PR detail requests. Preserve discovery order within each group and report skipped candidates.
- Merge repository-name case variants before applying the detail cap, retaining the first endpoint spelling and combined discovery sources.
- Use the actual base repository from PR details for report identity and same-repository classification, including repository redirects.
- Add a shared agent skill and installation instructions for Codex and Claude Code. Validate a skill-guided read-only scan with the release CLI; client discovery and invocation remain untested.

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
