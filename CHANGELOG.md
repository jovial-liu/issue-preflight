# Changelog

## 0.1.1

- Report exact pinned policy lines and original text excerpts for detected rules, maintainer stop requests, and existing fix declarations.
- Exclude common fenced, indented, and inline code examples and HTML comments without losing source positions or later real fixes.
- Make unresolved manual-link timeline events visible as evidence gaps.
- Evaluate the authenticated GitHub user by default, display the contributor in Markdown, and report failed identity lookups.
- Add `--fail-on-review` for workflows that must stop on uncertainty as well as blockers.
- Document release-wheel installation without Git and include a virtual-environment alternative in both languages.

## 0.1.0

Initial preview: bounded read-only issue, discussion, PR, and policy collection; Markdown and JSON reports; offline regression tests and Linux/Windows CI.
