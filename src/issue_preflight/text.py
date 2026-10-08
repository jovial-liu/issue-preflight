"""Mask common Markdown examples without moving source evidence offsets."""

from __future__ import annotations

import re


def _escaped(text: str, position: int) -> bool:
    start = position
    while start > 0 and text[start - 1] == "\\":
        start -= 1
    return (position - start) % 2 == 1


def prose(text: str) -> str:
    """Hide fences, inline code and HTML comments, preserving length and newlines.

    This is a conservative classifier aid, not a complete Markdown parser.
    """
    masked = list(text)

    def hide(start: int, end: int) -> None:
        # A non-whitespace separator prevents erasing `not` into a positive rule.
        for position in range(start, end):
            if text[position] not in "\r\n":
                masked[position] = "\x00"

    fence = ""
    fence_depth = 0
    indented = False
    previous_blank = True
    offset = 0
    for line in text.splitlines(keepends=True):
        stop = offset + len(line)
        visible = "".join(masked[offset:stop])
        # Blockquote fences also contain examples, not contribution directives.
        prefix = re.match(r"^ {0,3}(?:> ?)+", visible)
        depth = prefix[0].count(">") if prefix else 0
        content = visible[prefix.end() :] if prefix else visible
        # A fenced block in a quote ends when that quote container ends.
        if fence and depth < fence_depth:
            fence = ""
        match = re.match(r"^ {0,3}(`{3,}|~{3,})([^\r\n]*)", content)
        if fence:
            hide(offset, stop)
            if depth == fence_depth and re.fullmatch(
                rf" {{0,3}}{re.escape(fence[0])}{{{len(fence)},}}\s*", content
            ):
                fence = ""
        elif match and not (match[1].startswith("`") and "`" in match[2]):
            fence = match[1]
            fence_depth = depth
            hide(offset, stop)
        elif (indented or previous_blank) and re.match(r"^(?: {4}|\t)[ \t]*\S", content):
            indented = True
            hide(offset, stop)
        elif indented and not content.strip():
            hide(offset, stop)
        else:
            indented = False
            # Read in source order so literal comment markers in code and literal
            # fences in comments cannot mask unrelated prose after their region.
            for token in re.finditer(r"<!--|`+", line):
                start = offset + token.start()
                if masked[start] == "\x00" or _escaped(text, start):
                    continue
                if token[0] == "<!--":
                    end = text.find("-->", start + 4)
                    hide(start, len(text) if end < 0 else end + 3)
                    continue
                boundary = re.search(r"\r?\n[ \t]*\r?\n", text[start:])
                limit = start + boundary.start() if boundary else len(text)
                # Fenced blocks can interrupt a paragraph without a blank line.
                for block in re.finditer(
                    r"\r?\n {0,3}(?:> ?)*(`{3,}|~{3,})([^\r\n]*)", text[start:limit]
                ):
                    if not (block[1].startswith("`") and "`" in block[2]):
                        limit = start + block.start()
                        break
                delimiter = rf"(?<!`)`{{{len(token[0])}}}(?!`)"
                end = re.search(delimiter, text[start + len(token[0]) : limit])
                if end:
                    hide(start, start + len(token[0]) + end.end())
        previous_blank = not content.strip()
        offset = stop
    return "".join(masked)
