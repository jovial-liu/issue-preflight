from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from issue_preflight.policy_links import PolicyLink, policy_links

REPO = "example/project"
SHA = "a" * 40


def links(text: str, source: str = "CONTRIBUTING.md") -> list[PolicyLink]:
    return policy_links(text, REPO, source)


@pytest.mark.parametrize(
    ("source", "destination", "expected"),
    [
        ("CONTRIBUTING.md", "AI_POLICY.md", "AI_POLICY.md"),
        ("CONTRIBUTING.md", "./docs/AI_POLICY.md", "docs/AI_POLICY.md"),
        (".github/CONTRIBUTING.md", "../AI_POLICY.md", "AI_POLICY.md"),
        ("docs/guides/CONTRIBUTING.md", "../../AI_POLICY.md", "AI_POLICY.md"),
        ("docs/guides/CONTRIBUTING.md", "../ai/policy.md", "docs/ai/policy.md"),
        (".github/CONTRIBUTING.md", "/docs/AI_POLICY.md", "docs/AI_POLICY.md"),
        ("CONTRIBUTING.md", "docs/../AI_POLICY.md", "AI_POLICY.md"),
        ("CONTRIBUTING.md", "docs/%2e%2e/AI_POLICY.md", "AI_POLICY.md"),
        (".github/CONTRIBUTING.md", "%2E%2E/AI_POLICY.md", "AI_POLICY.md"),
        ("CONTRIBUTING.md", "docs/AI%20POLICY.md?raw=1#L3", "docs/AI POLICY.md"),
        ("CONTRIBUTING.md", "docs/AI%23POLICY.md#rules", "docs/AI#POLICY.md"),
        ("CONTRIBUTING.md", "docs/AI%3FPOLICY.md?plain=1", "docs/AI?POLICY.md"),
        ("CONTRIBUTING.md", "docs/%252e%252e/AI_POLICY.md", "docs/%2e%2e/AI_POLICY.md"),
        ("CONTRIBUTING.md", "docs/AI%2520POLICY.md", "docs/AI%20POLICY.md"),
        ("CONTRIBUTING.md", "docs/AI_POLICY.MD", "docs/AI_POLICY.MD"),
        ("CONTRIBUTING.md", "docs/AI_POLICY.markdown", "docs/AI_POLICY.markdown"),
        ("CONTRIBUTING.md", "docs/AI_POLICY.rst", "docs/AI_POLICY.rst"),
        ("CONTRIBUTING.md", "docs/AI_POLICY.txt", "docs/AI_POLICY.txt"),
        ("CONTRIBUTING.md", "docs/CONTRIBUTING", "docs/CONTRIBUTING"),
    ],
)
def test_repository_relative_documents(source, destination, expected):
    assert links(f"[AI policy]({destination})", source) == [PolicyLink(expected)]


@pytest.mark.parametrize(
    ("reference", "path"),
    [
        ("main", "docs/AI_POLICY.md"),
        ("master", "docs/AI_POLICY.md"),
        (SHA, "docs/AI_POLICY.md"),
        ("feature%2Fpolicy", "docs/AI_POLICY.md"),
        ("release", "AI_POLICY.md"),
    ],
)
def test_same_repository_blob_links_ignore_the_original_ref(reference, path):
    destination = f"https://github.com/EXAMPLE/Project/blob/{reference}/{path}?plain=1#L4"
    assert links(f"[AI policy]({destination})", ".github/CONTRIBUTING.md") == [PolicyLink(path)]


@pytest.mark.parametrize(
    "destination",
    [
        "../AI_POLICY.md",
        "%2e%2e/AI_POLICY.md",
        "docs/../../AI_POLICY.md",
        "/../AI_POLICY.md",
        "https://github.com/example/project/blob/main/../AI_POLICY.md",
    ],
)
def test_paths_cannot_leave_the_repository(destination):
    result = links(f"[AI policy]({destination})")
    assert result == [PolicyLink(None, "Policy path leaves this repository.")]


@pytest.mark.parametrize(
    "destination",
    [
        "https://evil.test/AI_POLICY.md",
        "//evil.test/AI_POLICY.md",
        "https://github.com.evil.test/example/project/blob/main/AI_POLICY.md",
        "https://github.com@evil.test/example/project/blob/main/AI_POLICY.md",
        "https://secret:password@github.com/example/project/blob/main/AI_POLICY.md",
        "http://github.com/example/project/blob/main/AI_POLICY.md",
        "https://raw.githubusercontent.com/example/project/main/AI_POLICY.md",
        "mailto:policies@example.test",
    ],
)
def test_external_policy_links_have_a_gap_without_echoing_the_url(destination):
    result = links(f"[AI policy]({destination})")
    assert len(result) == 1
    assert result[0].path is None
    assert result[0].reason == "External policy link is not collected."
    assert "secret" not in result[0].reason
    assert "password" not in result[0].reason


def test_other_repository_blob_link_is_not_followed():
    assert links("[AI policy](https://github.com/other/project/blob/main/AI_POLICY.md)") == [
        PolicyLink(None, "Policy link points outside this repository.")
    ]


def test_unknown_ref_with_directories_is_explicitly_ambiguous():
    assert links(
        "[AI policy](https://github.com/example/project/blob/feature/ai/docs/AI_POLICY.md)"
    ) == [PolicyLink(None, "Policy link has an ambiguous GitHub branch/file path.")]


@pytest.mark.parametrize(
    "destination",
    ["AI_POLICY.py", "AI_POLICY.pdf", "AI_POLICY.png", "AI_POLICY", "docs/"],
)
def test_unsupported_policy_documents_are_visible_gaps(destination):
    assert links(f"[AI policy]({destination})") == [
        PolicyLink(None, "Policy link is not a supported text document.")
    ]


@pytest.mark.parametrize(
    "destination",
    ["AI_POLICY%GG.md", "AI_POLICY%.md", "AI_POLICY%FF.md", "AI_POLICY%C3.md"],
)
def test_invalid_percent_encoding_is_not_silently_replaced(destination):
    assert links(f"[AI policy]({destination})") == [
        PolicyLink(None, "Policy path has invalid percent encoding or UTF-8.")
    ]


@pytest.mark.parametrize("destination", ["AI_POLICY%00.md", "AI_POLICY%0A.md", "AI%5CPOLICY.md"])
def test_unsupported_decoded_characters_are_visible_gaps(destination):
    assert links(f"[AI policy]({destination})") == [
        PolicyLink(None, "Policy path contains unsupported characters.")
    ]


@pytest.mark.parametrize("destination", ["#ai-policy", "?plain=1#rules", ""])
def test_same_document_anchors_do_not_trigger_file_requests(destination):
    assert links(f"[AI policy]({destination})") == []


def test_policy_filename_and_label_are_both_meaningful():
    assert links(
        "[here](AI_POLICY.md) [AI usage guidelines](README.md) [instructions](AGENTS.md)"
    ) == [
        PolicyLink("AI_POLICY.md"),
        PolicyLink("README.md"),
        PolicyLink("AGENTS.md"),
    ]


def test_encoded_policy_filename_is_recognized_with_a_generic_label():
    assert links("[here](AI%5FPOLICY.md) [details](docs/%43ONTRIBUTING.md)") == [
        PolicyLink("AI_POLICY.md"),
        PolicyLink("docs/CONTRIBUTING.md"),
    ]


def test_url_authority_query_and_fragment_do_not_create_policy_links():
    assert (
        links(
            "[API docs](https://policy.example.test/api.md?AI_POLICY=yes#policy) "
            "[API docs](https://github.com/example/project/blob/ai-policy/api.md)"
        )
        == []
    )


def test_unrelated_links_and_images_are_ignored():
    assert (
        links(
            "[API docs](docs/api.md) [website](https://example.test/) "
            "[source](src/module.py) ![AI policy](docs/AI_POLICY.md)"
        )
        == []
    )


@pytest.mark.parametrize(
    "text",
    [
        "[AI policy](<docs/AI Policy.md>)",
        '[AI policy](<docs/AI Policy.md> "Usage requirements")',
        "[AI policy](docs/AI%20Policy.md 'Usage requirements')",
        "[AI policy](docs/AI%20Policy.md (Usage requirements))",
    ],
)
def test_angle_paths_with_spaces_and_optional_titles(text):
    assert links(text) == [PolicyLink("docs/AI Policy.md")]


def test_balanced_parentheses_and_escaped_markdown_destination():
    assert links(r"[AI policy](docs/AI_POLICY(v2).md) [AI policy](docs/AI_POLICY\(v3\).md)") == [
        PolicyLink("docs/AI_POLICY(v2).md"),
        PolicyLink("docs/AI_POLICY(v3).md"),
    ]


@pytest.mark.parametrize(
    "text",
    [
        "[AI policy][rules]\n\n[rules]: AI_POLICY.md",
        '[AI policy][rules]\n\n[rules]: AI_POLICY.md "Usage rules"',
        "[AI policy][]\n\n[AI policy]: AI_POLICY.md",
        "[AI policy]\n\n[AI policy]: AI_POLICY.md",
        "[AI policy][  RULES  ]\n\n[rules]: AI_POLICY.md",
        "[AI policy][rules]\n\n[rules]: <AI_POLICY.md>",
    ],
)
def test_full_collapsed_and_shortcut_reference_links(text):
    assert links(text) == [PolicyLink("AI_POLICY.md")]


def test_reference_link_can_use_a_filename_to_identify_policy():
    assert links("[details][rules]\n\n[rules]: docs/AI_POLICY.md") == [
        PolicyLink("docs/AI_POLICY.md")
    ]


def test_unused_definitions_and_undefined_references_are_not_links():
    assert links("[AI policy][missing]\n\n[unused]: AI_POLICY.md") == []


@pytest.mark.parametrize(
    "text",
    [
        "`[AI policy](AI_POLICY.md)`",
        "```markdown\n[AI policy](AI_POLICY.md)\n```",
        "~~~markdown\n[AI policy](AI_POLICY.md)\n~~~",
        "    [AI policy](AI_POLICY.md)",
        "<!-- [AI policy](AI_POLICY.md) -->",
        r"\[AI policy](AI_POLICY.md)",
        "[AI policy][rules]\n\n```\n[rules]: AI_POLICY.md\n```",
    ],
)
def test_code_examples_comments_and_escaped_links_are_not_collected(text):
    assert links(text) == []


def test_links_outside_examples_are_preserved_and_canonical_paths_are_deduplicated():
    text = "```\n[AI policy](FAKE_POLICY.md)\n```\n\n[AI policy](./AI_POLICY.md#x) "
    text += "[AI policy](docs/../AI_POLICY.md?plain=1) [Agent policy](AGENTS.md)"
    assert links(text) == [PolicyLink("AI_POLICY.md"), PolicyLink("AGENTS.md")]


@pytest.mark.parametrize(
    "prefix",
    ["[" * 79_000, ("[unclosed" * 8_000)],
    ids=["open-brackets", "unclosed-labels"],
)
def test_unclosed_labels_at_file_limit_do_not_stall_or_hide_the_next_line(prefix):
    # Isolate a possible parser stall so a regression cannot hang the test runner.
    text = prefix + "\r\n[AI policy](AI_POLICY.md)"
    assert len(text.encode()) < 80_000
    assert bounded_links(text) == ["AI_POLICY.md"]


def bounded_links(text):
    code = (
        "import json, sys; from issue_preflight.policy_links import policy_links; "
        "print(json.dumps([link.path for link in "
        "policy_links(sys.stdin.read(), 'example/project', 'CONTRIBUTING.md')]))"
    )
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    result = subprocess.run(
        [sys.executable, "-c", code],
        input=text,
        text=True,
        capture_output=True,
        timeout=5,
        check=True,
        env=env,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    ("prefix", "suffix", "expected"),
    [
        ("[AI policy](", ")", [None]),
        ('[AI policy](AI_POLICY.md "', '")', ["AI_POLICY.md"]),
    ],
    ids=["escaped-destination", "escaped-title"],
)
def test_long_escape_runs_do_not_stall(prefix, suffix, expected):
    text = prefix + "\\" * 79_000 + suffix
    assert len(text.encode()) < 80_000
    assert bounded_links(text) == expected


def test_reference_definitions_with_crlf_preserve_the_destination():
    text = "[AI policy][rules]\r\n\r\n[rules]: ../AI_POLICY.md\r\n"
    assert links(text, "docs/contributing.md") == [PolicyLink("AI_POLICY.md")]


def test_reference_occurrences_use_their_original_offsets_after_an_inline_link():
    text = (
        "[AI policy](AI_POLICY.md) [Agent policy][agents] [AI rules][rules]\n\n"
        "[agents]: AGENTS.md\n[rules]: AI_RULES.md\n"
    )
    assert links(text) == [
        PolicyLink("AI_POLICY.md"),
        PolicyLink("AGENTS.md"),
        PolicyLink("AI_RULES.md"),
    ]


def test_repeated_unclosed_destinations_do_not_stall_or_hide_a_later_valid_link():
    text = "[policy](" * 8_000 + "\n[AI policy](AI_POLICY.md)"
    assert len(text.encode()) < 80_000
    assert bounded_links(text) == ["AI_POLICY.md"]


def test_valid_nested_link_after_an_unclosed_destination_is_still_collected():
    assert links("[broken]([AI_POLICY](AI_POLICY.md)") == [PolicyLink("AI_POLICY.md")]


@pytest.mark.parametrize(
    "text",
    [
        "[AI [usage policy](AI_POLICY.md)",
        "[] [AI policy](AI_POLICY.md)",
        "[unclosed\n[AI policy](AI_POLICY.md)",
        "[unclosed\r[AI policy](AI_POLICY.md)",
        "[unclosed\vAI policy](AI_POLICY.md)",
        r"\[ignored](IGNORED_POLICY.md) [AI policy](AI_POLICY.md)",
    ],
)
def test_label_scanning_keeps_existing_one_line_boundaries(text):
    assert links(text) == [PolicyLink("AI_POLICY.md")]
