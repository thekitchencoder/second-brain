# tests/lib/test_edit.py
"""Unit tests for surgical edit operations."""
import textwrap

from lib.edit import (
    append_to_section,
    find_replace,
    insert_wikilink,
    prepend_to_section,
    replace_lines,
    replace_section,
    update_frontmatter,
)

_NOTE = textwrap.dedent("""\
    ---
    title: Test Note
    status: draft
    tags: [alpha, beta]
    ---

    # Overview

    Some overview text.

    # Details

    Detail paragraph one.

    Detail paragraph two.

    # References

    - [[other-note]]
""")


# ── update_frontmatter ──────────────────────────────────────────────


def test_update_frontmatter_merges_keys():
    result = update_frontmatter(_NOTE, {"status": "current", "effort": "sprint-1"})
    assert "status: current" in result
    assert "effort: sprint-1" in result
    # Original key preserved
    assert "title: Test Note" in result


def test_update_frontmatter_no_existing_frontmatter():
    result = update_frontmatter("# Just a heading\n\nBody.", {"status": "raw"})
    assert result.startswith("---")
    assert "status: raw" in result
    assert "# Just a heading" in result


# ── replace_section ─────────────────────────────────────────────────


def test_replace_section_replaces_body():
    result, found = replace_section(_NOTE, "Details", "New detail content.")
    assert found
    assert "New detail content." in result
    assert "Detail paragraph one." not in result
    # Heading preserved
    assert "# Details" in result
    # Adjacent sections untouched
    assert "Some overview text." in result
    assert "[[other-note]]" in result


def test_replace_section_not_found():
    result, found = replace_section(_NOTE, "Nonexistent", "x")
    assert not found
    assert result == _NOTE


# ── append_to_section ───────────────────────────────────────────────


def test_append_to_section():
    result, found = append_to_section(_NOTE, "Details", "Appended line.")
    assert found
    assert "Detail paragraph two." in result
    assert "Appended line." in result
    # Appended content comes after existing detail
    detail_pos = result.index("Detail paragraph two.")
    append_pos = result.index("Appended line.")
    assert append_pos > detail_pos


def test_append_to_section_not_found():
    result, found = append_to_section(_NOTE, "Missing", "x")
    assert not found


# ── prepend_to_section ──────────────────────────────────────────────


def test_prepend_to_section():
    result, found = prepend_to_section(_NOTE, "Details", "Prepended line.")
    assert found
    # Prepended content comes before existing detail
    prepend_pos = result.index("Prepended line.")
    detail_pos = result.index("Detail paragraph one.")
    assert prepend_pos < detail_pos


# ── replace_lines ───────────────────────────────────────────────────


def test_replace_lines_basic():
    text = "line1\nline2\nline3\nline4\nline5"
    result, err = replace_lines(text, 2, 4, "replaced")
    assert err is None
    assert result == "line1\nreplaced\nline4\nline5"


def test_replace_lines_invalid_range():
    text = "line1\nline2"
    _, err = replace_lines(text, 5, 6, "x")
    assert err is not None
    assert "Invalid" in err


def test_replace_lines_delete():
    text = "line1\nline2\nline3"
    result, err = replace_lines(text, 2, 3, "")
    assert err is None
    assert result == "line1\nline3"


# ── find_replace ────────────────────────────────────────────────────


def test_find_replace_all():
    text, n = find_replace("foo bar foo baz foo", "foo", "qux")
    assert n == 3
    assert text == "qux bar qux baz qux"


def test_find_replace_count():
    text, n = find_replace("foo foo foo", "foo", "bar", count=2)
    assert n == 2
    assert text == "bar bar foo"


def test_find_replace_regex():
    text, n = find_replace("status: draft", r"status:\s+\w+", "status: current", regex=True)
    assert n == 1
    assert text == "status: current"


def test_find_replace_no_match():
    text, n = find_replace("hello world", "xyz", "abc")
    assert n == 0
    assert text == "hello world"


def test_find_replace_invalid_regex_returns_error():
    """Invalid regex must return an error tuple, not raise."""
    text, n = find_replace("some text", r"(invalid[regex", "replace", regex=True)
    assert n == -1  # sentinel for error
    assert "Invalid regex" in text


def test_find_replace_valid_regex_still_works():
    text, n = find_replace("hello world", r"w\w+", "there", regex=True)
    assert n == 1
    assert text == "hello there"


# ── insert_wikilink ─────────────────────────────────────────────────


def test_insert_wikilink_to_end():
    text = "Some content."
    result, inserted = insert_wikilink(text, "new-note")
    assert inserted
    assert "[[new-note]]" in result


def test_insert_wikilink_already_exists():
    text = "See [[existing-note]] for details."
    result, inserted = insert_wikilink(text, "existing-note")
    assert not inserted
    assert result == text


def test_insert_wikilink_to_section():
    result, inserted = insert_wikilink(_NOTE, "new-ref", context_heading="References")
    assert inserted
    assert "[[new-ref]]" in result
    # Inserted in the References section
    ref_pos = result.index("# References")
    link_pos = result.index("[[new-ref]]")
    assert link_pos > ref_pos
