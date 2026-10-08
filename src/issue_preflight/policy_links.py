"""Resolve recognizable Markdown policy links within one repository snapshot."""

from __future__ import annotations

import re
import string
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from .text import prose

DOCUMENT_SUFFIXES = {"md", "markdown", "rst", "txt"}
EXTENSIONLESS_GUIDES = {"contributing", "contribute", "contribution", "contributions"}
LABEL = re.compile(r"\[([^\]\r\n]+)\]")
DEFINITION = re.compile(r"^ {0,3}\[([^\]\r\n]+)\]:[ \t]*(.*)$", re.MULTILINE)
BAD_ESCAPE = re.compile(r"%(?![0-9a-fA-F]{2})")
MARKDOWN_ESCAPE = re.compile(r"\\([" + re.escape(string.punctuation) + r"])")


@dataclass(frozen=True)
class PolicyLink:
    path: str | None
    reason: str | None = None


def _escaped(text: str, position: int) -> bool:
    start = position
    while start and text[start - 1] == "\\":
        start -= 1
    return (position - start) % 2 == 1


def _reference_label(value: str) -> str:
    value = MARKDOWN_ESCAPE.sub(r"\1", value)
    return " ".join(value.split()).casefold()


def _looks_like_policy(label: str, destination: str) -> bool:
    # A generic README can hold policy; a file named AI_POLICY is meaningful
    # even when its link label is only "here". Separate underscores into words.
    try:
        parsed = urlsplit(MARKDOWN_ESCAPE.sub(r"\1", destination))
        path = parsed.path
        if parsed.scheme or parsed.netloc:
            parts = path.removeprefix("/").split("/")
            if len(parts) >= 5 and parts[2] == "blob":
                path = "/".join(parts[4:])
    except ValueError:
        path = destination
    path = _decode(path) or path
    value = re.sub(r"[-_./]+", " ", f"{label} {path}").casefold()
    if re.search(r"\b(?:contribut(?:e|es|ed|ing|ions?|ors?)|polic(?:y|ies))\b", value):
        return True
    if re.search(r"\bagents?\b", value):
        return True
    return bool(
        re.search(r"\b(?:ai|llm)\b", value)
        and re.search(r"\b(?:guidelines?|rules?|instructions?|usage|use|requirements?)\b", value)
    )


def _destination(value: str, position: int) -> tuple[str, int] | None:
    """Read an angle destination or a balanced, whitespace-free destination."""
    while position < len(value) and value[position] in " \t":
        position += 1
    start = position
    if position >= len(value):
        return None
    if value[position] == "<":
        position += 1
        start = position
        while position < len(value):
            character = value[position]
            if character in "\r\n\x00" or character == "<":
                return None
            if character == ">" and not _escaped(value, position):
                return value[start:position], position + 1
            position += 1
        return None
    depth = 0
    while position < len(value):
        character = value[position]
        if character in "\r\n\x00":
            return None
        if not _escaped(value, position):
            if character == "(":
                depth += 1
            elif character == ")":
                if depth == 0:
                    break
                depth -= 1
            elif character in " \t":
                break
        position += 1
    if depth or position == start:
        return None
    return value[start:position], position


def _tail(value: str, position: int, inline: bool) -> int | None:
    """Accept an optional one-line title followed by the link's closing delimiter."""
    initial = position
    while position < len(value) and value[position] in " \t":
        position += 1
    if position > initial and position < len(value) and value[position] in "\"'(":
        delimiter = ")" if value[position] == "(" else value[position]
        position += 1
        while position < len(value):
            if value[position] in "\r\n\x00":
                return None
            if value[position] == delimiter and not _escaped(value, position):
                position += 1
                break
            position += 1
        else:
            return None
        while position < len(value) and value[position] in " \t":
            position += 1
    if inline:
        return position + 1 if value[position : position + 1] == ")" else None
    return position if position == len(value) else None


def _decode(value: str) -> str | None:
    if BAD_ESCAPE.search(value):
        return None
    try:
        return unquote(value, encoding="utf-8", errors="strict")
    except UnicodeError:
        return None


def _resolve(destination: str, repo: str, source_path: str) -> PolicyLink | None:
    destination = MARKDOWN_ESCAPE.sub(r"\1", destination)
    if any(ord(character) < 32 or ord(character) == 127 for character in destination):
        return PolicyLink(None, "Policy link contains unsupported control characters.")
    try:
        parsed = urlsplit(destination)
    except ValueError:
        return PolicyLink(None, "Policy link has an unsupported URL.")
    if not parsed.path and not parsed.scheme and not parsed.netloc:
        return None  # Same-document query/fragment links need no file request.
    base = source_path.split("/")[:-1]
    raw_path = parsed.path
    if parsed.scheme or parsed.netloc:
        # Never request a linked URL. Extract a same-repository path, then let
        # the collector request it at its already pinned commit.
        if parsed.scheme.casefold() != "https" or parsed.netloc.casefold() != "github.com":
            return PolicyLink(None, "External policy link is not collected.")
        parts = raw_path.removeprefix("/").split("/")
        if len(parts) < 5 or parts[2] != "blob":
            return PolicyLink(None, "Policy link is not a supported GitHub file link.")
        owner, name = _decode(parts[0]), _decode(parts[1])
        if owner is None or name is None or f"{owner}/{name}".casefold() != repo.casefold():
            return PolicyLink(None, "Policy link points outside this repository.")
        reference = _decode(parts[3])
        if (
            not reference
            or reference in {".", ".."}
            or "\\" in reference
            or any(ord(character) < 32 or ord(character) == 127 for character in reference)
        ):
            return PolicyLink(None, "Policy link has an unsupported GitHub reference.")
        known_reference = (
            reference in {"main", "master"}
            or re.fullmatch(r"[0-9a-fA-F]{40}", reference)
            or "/" in reference
        )
        if not known_reference and len(parts[4:]) > 1:
            return PolicyLink(None, "Policy link has an ambiguous GitHub branch/file path.")
        raw_path = "/".join(parts[4:])
        base = []
    elif raw_path.startswith("/"):
        base = []
    path = _decode(raw_path)
    if path is None:
        return PolicyLink(None, "Policy path has invalid percent encoding or UTF-8.")
    if "\\" in path or any(ord(character) < 32 or ord(character) == 127 for character in path):
        return PolicyLink(None, "Policy path contains unsupported characters.")
    for part in path.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            if not base:
                return PolicyLink(None, "Policy path leaves this repository.")
            base.pop()
        else:
            base.append(part)
    if not base:
        return PolicyLink(None, "Policy link does not identify a document.")
    basename = base[-1].casefold()
    suffix = basename.rsplit(".", 1)[-1] if "." in basename else ""
    if suffix not in DOCUMENT_SUFFIXES and basename not in EXTENSIONLESS_GUIDES:
        return PolicyLink(None, "Policy link is not a supported text document.")
    return PolicyLink("/".join(base))


def policy_links(text: str, repo: str, source_path: str) -> list[PolicyLink]:
    """Find recognizable inline/reference policy links without following URLs.

    Code examples and comments are masked. This intentionally supports common
    one-line Markdown links rather than implementing a complete Markdown parser.
    Returned paths keep filename case and can be read at the collector's SHA.
    """
    visible = prose(text)
    definitions: dict[str, str] = {}
    for definition in DEFINITION.finditer(visible):
        parsed = _destination(definition[2], 0)
        if parsed and _tail(definition[2], parsed[1], inline=False) is not None:
            definitions.setdefault(_reference_label(definition[1]), parsed[0])
    results = []
    seen: set[PolicyLink] = set()
    consumed = 0
    for label in LABEL.finditer(visible):
        if label.start() < consumed or _escaped(visible, label.start()):
            continue
        if label.start() and visible[label.start() - 1] == "!":
            continue
        position = label.end()
        if visible[position : position + 1] == ":":
            continue  # A definition is not itself an occurrence of a link.
        destination = None
        if visible[position : position + 1] == "(":
            parsed = _destination(visible, position + 1)
            if parsed:
                end = _tail(visible, parsed[1], inline=True)
                if end is not None:
                    destination = parsed[0]
                    consumed = end
        elif visible[position : position + 1] == "[":
            reference = re.match(r"\[([^\]\r\n]*)\]", visible[position:])
            if reference:
                key = _reference_label(reference[1] or label[1])
                destination = definitions.get(key)
                consumed = position + reference.end()
        else:
            destination = definitions.get(_reference_label(label[1]))
        if destination is None or not _looks_like_policy(label[1], destination):
            continue
        result = _resolve(destination, repo, source_path)
        if result is not None and result not in seen:
            seen.add(result)
            results.append(result)
    return results
