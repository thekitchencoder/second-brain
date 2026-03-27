"""Surgical edit operations for brain notes.

Supports targeted modifications without full-file replacement:
section replace/append, frontmatter merge, line-range ops, find-replace.
"""
import re
from typing import Optional

import yaml

from lib.clean import extract_frontmatter


def _rebuild_file(meta: dict, content: str) -> str:
    """Reassemble a markdown file from frontmatter dict and body content."""
    if meta:
        fm = yaml.dump(meta, default_flow_style=False, sort_keys=False, allow_unicode=True).rstrip("\n")
        return f"---\n{fm}\n---\n\n{content}"
    return content


def _heading_pattern(heading: str) -> re.Pattern:
    """Match a markdown heading line (any level) with the given text."""
    escaped = re.escape(heading.strip())
    return re.compile(rf"^(#{{1,6}})\s+{escaped}\s*$", re.MULTILINE)


def _find_section(text: str, heading: str) -> Optional[tuple[int, int, int]]:
    """Find a section by heading. Returns (heading_start, body_start, body_end).

    body_end is the start of the next heading at the same or higher level,
    or end-of-string if none.
    """
    pat = _heading_pattern(heading)
    m = pat.search(text)
    if not m:
        return None
    level = len(m.group(1))  # number of # chars
    heading_start = m.start()
    body_start = m.end() + 1  # skip the newline after the heading

    # Find next heading at same or higher level
    next_heading = re.compile(rf"^#{{1,{level}}}\s", re.MULTILINE)
    n = next_heading.search(text, body_start)
    body_end = n.start() if n else len(text)
    return heading_start, body_start, body_end


# ── Public edit operations ──────────────────────────────────────────


def update_frontmatter(text: str, updates: dict) -> str:
    """Merge key-value pairs into existing frontmatter."""
    meta, content = extract_frontmatter(text)
    meta.update(updates)
    return _rebuild_file(meta, content)


def replace_section(text: str, heading: str, new_body: str) -> tuple[str, bool]:
    """Replace the body of a section (preserving the heading).

    Returns (new_text, found).
    """
    loc = _find_section(text, heading)
    if not loc:
        return text, False
    _, body_start, body_end = loc
    new_text = text[:body_start] + new_body.rstrip("\n") + "\n\n" + text[body_end:].lstrip("\n")
    return new_text, True


def append_to_section(text: str, heading: str, content_to_append: str) -> tuple[str, bool]:
    """Append content to the end of a section's body.

    Returns (new_text, found).
    """
    loc = _find_section(text, heading)
    if not loc:
        return text, False
    _, _, body_end = loc
    insertion = content_to_append.rstrip("\n") + "\n"
    # Insert before the trailing whitespace at end of section
    insert_at = body_end
    new_text = text[:insert_at] + insertion + text[insert_at:]
    return new_text, True


def prepend_to_section(text: str, heading: str, content_to_prepend: str) -> tuple[str, bool]:
    """Prepend content right after the heading line.

    Returns (new_text, found).
    """
    loc = _find_section(text, heading)
    if not loc:
        return text, False
    _, body_start, _ = loc
    insertion = content_to_prepend.rstrip("\n") + "\n"
    new_text = text[:body_start] + insertion + text[body_start:]
    return new_text, True


def replace_lines(text: str, start: int, end: int, replacement: str) -> tuple[str, Optional[str]]:
    """Replace lines [start, end) (1-indexed, inclusive start, exclusive end).

    Returns (new_text, error_or_none).
    """
    lines = text.split("\n")
    total = len(lines)
    if start < 1 or end < start or start > total:
        return text, f"Invalid line range [{start}, {end}): file has {total} lines"
    # Clamp end to total+1 (past-the-end)
    end = min(end, total + 1)
    replacement_lines = replacement.split("\n") if replacement else []
    lines[start - 1: end - 1] = replacement_lines
    return "\n".join(lines), None


def find_replace(text: str, find: str, replace: str, *, regex: bool = False, count: int = 0) -> tuple[str, int]:
    """Find and replace text. Returns (new_text, num_replacements).

    count=0 means replace all occurrences.
    On invalid regex, returns (error_message, -1).
    """
    if regex:
        try:
            pattern = re.compile(find)
        except re.error as e:
            return f"Invalid regex: {e}", -1
        new_text, n = pattern.subn(replace, text, count=count or 0)
    else:
        if count == 0:
            new_text = text.replace(find, replace)
            n = text.count(find)
        else:
            new_text = text.replace(find, replace, count)
            n = min(text.count(find), count)
    return new_text, n


def insert_wikilink(text: str, target: str, *, context_heading: Optional[str] = None) -> tuple[str, bool]:
    """Insert a [[wikilink]] to target. If context_heading is given, appends
    to that section; otherwise appends to the end of the file.

    Returns (new_text, inserted). inserted is False if link already exists.
    """
    link = f"[[{target}]]"
    if link in text:
        return text, False
    if context_heading:
        new_text, found = append_to_section(text, context_heading, link)
        if found:
            return new_text, True
    # Fallback: append to end
    return text.rstrip("\n") + "\n" + link + "\n", True
