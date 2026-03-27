# tests/test_brain_service.py
"""Tests for lib.brain — shared service layer (edit, backlinks, helpers)."""
import os
import sys
import textwrap

import pytest
from unittest.mock import MagicMock, patch

# Stub native-only deps
if "sqlite_vec" not in sys.modules:
    sys.modules["sqlite_vec"] = MagicMock()
if "openai" not in sys.modules:
    sys.modules["openai"] = MagicMock()

from lib.brain import (
    _check_within_brain,
    _format_results,
    _relative_path,
    _resolve_path,
    extract_wikilinks,
    find_backlinks,
    handle_brain_backlinks,
    handle_brain_create,
    handle_brain_edit,
    handle_brain_query,
    handle_brain_read,
    handle_brain_restore,
    handle_brain_search,
    handle_brain_trash,
    handle_brain_write,
)
from lib.embeddings import EmbeddingError


# ── Helpers ──────────────────────────────────────────────────────────


def test_check_within_brain_ok(tmp_path):
    assert _check_within_brain(str(tmp_path / "note.md"), str(tmp_path)) is None


def test_check_within_brain_outside(tmp_path):
    result = _check_within_brain("/etc/passwd", str(tmp_path))
    assert "outside the brain" in result


def test_resolve_path_relative(tmp_path):
    assert _resolve_path("foo.md", str(tmp_path)) == os.path.join(str(tmp_path), "foo.md")


def test_resolve_path_absolute(tmp_path):
    p = str(tmp_path / "note.md")
    assert _resolve_path(p, str(tmp_path)) == p


def test_relative_path(tmp_path):
    assert _relative_path(str(tmp_path / "sub" / "note.md"), str(tmp_path)) == "sub/note.md"


def test_relative_path_does_not_match_sibling_prefix():
    """_relative_path('/brain-backup/note.md', '/brain') must not strip the prefix."""
    result = _relative_path("/brain-backup/note.md", "/brain")
    # Should return the full path unchanged, not 'backup/note.md'
    assert result == "/brain-backup/note.md"


def test_format_results_empty():
    assert _format_results([]) == "No results found."


def test_extract_wikilinks():
    text = "See [[foo]] and [[bar|display text]]."
    links = extract_wikilinks(text)
    assert len(links) == 2
    assert links[0] == {"target": "foo"}
    assert links[1] == {"target": "bar", "alias": "display text"}


# ── brain_edit ───────────────────────────────────────────────────────


@pytest.fixture
def sample_note(tmp_path):
    note = tmp_path / "note.md"
    note.write_text(textwrap.dedent("""\
        ---
        title: Test
        status: draft
        ---

        # Overview

        Some content here.

        # Tasks

        - Task one
        - Task two

        # References

        - [[existing-link]]
    """))
    return str(note), str(tmp_path)


def test_edit_update_frontmatter(sample_note):
    filepath, brain_path = sample_note
    result = handle_brain_edit(filepath, "update_frontmatter", brain_path, frontmatter={"status": "current", "effort": "q1"})
    assert "Updated frontmatter" in result
    content = open(filepath).read()
    assert "status: current" in content
    assert "effort: q1" in content


def test_edit_replace_section(sample_note):
    filepath, brain_path = sample_note
    result = handle_brain_edit(filepath, "replace_section", brain_path, heading="Tasks", body="- All done!")
    assert "replace_section: Tasks" in result
    content = open(filepath).read()
    assert "- All done!" in content
    assert "- Task one" not in content


def test_edit_append_to_section(sample_note):
    filepath, brain_path = sample_note
    result = handle_brain_edit(filepath, "append_to_section", brain_path, heading="Tasks", body="- Task three")
    assert "append_to_section" in result
    content = open(filepath).read()
    assert "- Task three" in content
    assert "- Task two" in content


def test_edit_prepend_to_section(sample_note):
    filepath, brain_path = sample_note
    result = handle_brain_edit(filepath, "prepend_to_section", brain_path, heading="Tasks", body="- Task zero")
    assert "prepend_to_section" in result
    content = open(filepath).read()
    assert content.index("- Task zero") < content.index("- Task one")


def test_edit_find_replace(sample_note):
    filepath, brain_path = sample_note
    result = handle_brain_edit(filepath, "find_replace", brain_path, find="Some content", replace="Updated content")
    assert "1 occurrence" in result
    assert "Updated content" in open(filepath).read()


def test_edit_replace_lines(sample_note):
    filepath, brain_path = sample_note
    result = handle_brain_edit(filepath, "replace_lines", brain_path, start_line=8, end_line=9, replacement="Replaced line.")
    assert "Replaced lines" in result
    assert "Replaced line." in open(filepath).read()


def test_edit_insert_wikilink(sample_note):
    filepath, brain_path = sample_note
    result = handle_brain_edit(filepath, "insert_wikilink", brain_path, target="new-note", context_heading="References")
    assert "Inserted [[new-note]]" in result
    assert "[[new-note]]" in open(filepath).read()


def test_edit_insert_wikilink_duplicate(sample_note):
    filepath, brain_path = sample_note
    result = handle_brain_edit(filepath, "insert_wikilink", brain_path, target="existing-link")
    assert "already present" in result


def test_edit_section_not_found(sample_note):
    filepath, brain_path = sample_note
    result = handle_brain_edit(filepath, "replace_section", brain_path, heading="Nonexistent", body="x")
    assert "Section not found" in result


def test_edit_unknown_op(sample_note):
    filepath, brain_path = sample_note
    result = handle_brain_edit(filepath, "unknown_op", brain_path)
    assert "Unknown edit operation" in result


def test_edit_file_not_found(tmp_path):
    result = handle_brain_edit("nonexistent.md", "find_replace", str(tmp_path), find="x", replace="y")
    assert "File not found" in result


def test_edit_outside_brain(tmp_path):
    result = handle_brain_edit("/etc/passwd", "find_replace", str(tmp_path), find="x", replace="y")
    assert "outside the brain" in result


def test_edit_missing_required_fields(sample_note):
    filepath, brain_path = sample_note
    assert "required" in handle_brain_edit(filepath, "update_frontmatter", brain_path).lower()
    assert "required" in handle_brain_edit(filepath, "replace_section", brain_path).lower()
    assert "required" in handle_brain_edit(filepath, "replace_lines", brain_path).lower()
    assert "required" in handle_brain_edit(filepath, "find_replace", brain_path).lower()
    assert "required" in handle_brain_edit(filepath, "insert_wikilink", brain_path).lower()


# ── brain_backlinks ──────────────────────────────────────────────────


def test_backlinks_found(tmp_path):
    target = tmp_path / "target.md"
    target.write_text("---\ntitle: Target\n---\n\nHello.")
    linker = tmp_path / "linker.md"
    linker.write_text("---\ntitle: Linker\n---\n\nSee [[target]] for details.")

    result = handle_brain_backlinks("target.md", str(tmp_path))
    assert "Linker" in result
    assert "linker.md" in result


def test_backlinks_none(tmp_path):
    target = tmp_path / "target.md"
    target.write_text("---\ntitle: Target\n---\n\nHello.")

    result = handle_brain_backlinks("target.md", str(tmp_path))
    assert "No backlinks" in result


def test_find_backlinks_returns_dicts(tmp_path):
    target = tmp_path / "target.md"
    target.write_text("---\ntitle: Target\n---\n\nHello.")
    linker = tmp_path / "sub" / "linker.md"
    linker.parent.mkdir()
    linker.write_text("---\ntitle: Sub Linker\n---\n\nSee [[target]].")

    backlinks = find_backlinks(str(target), str(tmp_path))
    assert len(backlinks) == 1
    assert backlinks[0]["title"] == "Sub Linker"
    assert backlinks[0]["filepath"] == "sub/linker.md"


def test_backlinks_skips_hidden_dirs(tmp_path):
    target = tmp_path / "target.md"
    target.write_text("---\ntitle: Target\n---\n\nHello.")
    hidden = tmp_path / ".hidden" / "note.md"
    hidden.parent.mkdir()
    hidden.write_text("---\ntitle: Hidden\n---\n\n[[target]]")

    backlinks = find_backlinks(str(target), str(tmp_path))
    assert len(backlinks) == 0


def test_handle_brain_backlinks_consistent_with_find_backlinks(tmp_path):
    """handle_brain_backlinks must return the same notes as find_backlinks."""
    target = tmp_path / "target.md"
    target.write_text("---\ntitle: Target\n---\n\nHello.")
    linker = tmp_path / "linker.md"
    linker.write_text("---\ntitle: Linker Note\n---\n\nSee [[target]] here.")

    formatted = handle_brain_backlinks("target.md", str(tmp_path))
    structured = find_backlinks(str(target), str(tmp_path))

    assert len(structured) == 1
    assert "Linker Note" in formatted
    assert structured[0]["title"] == "Linker Note"
    assert structured[0]["filepath"] == "linker.md"


# ── brain_query input validation ─────────────────────────────────────


def test_brain_query_rejects_invalid_tag(tmp_path):
    result = handle_brain_query(tag="foo; bar", status=None, note_type=None, brain_path=str(tmp_path))
    assert "invalid" in result.lower()

def test_brain_query_rejects_invalid_status(tmp_path):
    result = handle_brain_query(tag=None, status="draft\ninjected", note_type=None, brain_path=str(tmp_path))
    assert "invalid" in result.lower()

def test_brain_query_rejects_invalid_type(tmp_path):
    result = handle_brain_query(tag=None, status=None, note_type="../etc/passwd", brain_path=str(tmp_path))
    assert "invalid" in result.lower()

def test_brain_query_accepts_valid_params(tmp_path):
    # Should not fail on input validation (may fail on zk not found — that's fine)
    result = handle_brain_query(tag="my-effort", status="draft", note_type="discovery", brain_path=str(tmp_path))
    assert "invalid" not in result.lower()


# ── EmbeddingError handling ───────────────────────────────────────────


def test_handle_brain_search_returns_error_on_embedding_failure(tmp_path):
    """handle_brain_search must not propagate EmbeddingError — return error string."""
    with patch("lib.embeddings.get_embedding", side_effect=EmbeddingError("model not found")):
        result = handle_brain_search("test query", 5, ":memory:")
    assert "error" in result.lower() or "embedding" in result.lower()


# ── brain_create template validation ─────────────────────────────────


def test_brain_create_rejects_path_traversal_template(tmp_path):
    result = handle_brain_create("../../../etc/passwd", "Test", str(tmp_path))
    assert "invalid" in result.lower() or "template" in result.lower()

def test_brain_create_rejects_template_with_slash(tmp_path):
    result = handle_brain_create("subdir/template", "Test", str(tmp_path))
    assert "invalid" in result.lower() or "template" in result.lower()

def test_brain_create_accepts_valid_template(tmp_path):
    # Valid name — should not fail on input validation (may fail on zk not found)
    result = handle_brain_create("effort", "My Project", str(tmp_path))
    assert "invalid" not in result.lower() or "zk" in result.lower()


# ── brain_trash ──────────────────────────────────────────────────────

@pytest.fixture
def brain_with_note(tmp_path):
    note = tmp_path / "Cards" / "foo.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("---\ntitle: Foo\n---\n\nHello.")
    return tmp_path


def test_trash_moves_file_to_trash_dir(brain_with_note):
    with patch("lib.brain.delete_file_chunks"):
        result = handle_brain_trash(
            "Cards/foo.md", str(brain_with_note), db_path=":memory:"
        )
    assert not (brain_with_note / "Cards" / "foo.md").exists()
    assert (brain_with_note / ".trash" / "Cards" / "foo.md").exists()
    assert "Trashed" in result


def test_trash_cleans_db(brain_with_note):
    with patch("lib.brain.delete_file_chunks") as mock_del:
        handle_brain_trash(
            "Cards/foo.md", str(brain_with_note), db_path="/tmp/test.db"
        )
    mock_del.assert_called_once()


def test_trash_returns_backlink_info(brain_with_note):
    linker = brain_with_note / "Efforts" / "baz.md"
    linker.parent.mkdir(parents=True, exist_ok=True)
    linker.write_text("---\ntitle: Baz\n---\n\nSee [[foo]].")
    with patch("lib.brain.delete_file_chunks"):
        result = handle_brain_trash(
            "Cards/foo.md", str(brain_with_note), db_path=":memory:"
        )
    assert "baz.md" in result or "Baz" in result
    assert "orphaned" in result.lower()


def test_trash_no_backlinks_reports_none(brain_with_note):
    with patch("lib.brain.delete_file_chunks"):
        result = handle_brain_trash(
            "Cards/foo.md", str(brain_with_note), db_path=":memory:"
        )
    assert "No backlinks" in result


def test_trash_rejects_non_md(brain_with_note):
    txt = brain_with_note / "readme.txt"
    txt.write_text("hello")
    result = handle_brain_trash("readme.txt", str(brain_with_note), db_path=":memory:")
    assert "Error" in result


def test_trash_rejects_outside_brain(tmp_path):
    result = handle_brain_trash("/etc/passwd", str(tmp_path), db_path=":memory:")
    assert "Error" in result or "outside" in result.lower()


def test_trash_collision_creates_datestamp_suffix_and_origin_sidecar(brain_with_note):
    # Pre-create a collision in trash
    trash_dest = brain_with_note / ".trash" / "Cards"
    trash_dest.mkdir(parents=True, exist_ok=True)
    (trash_dest / "foo.md").write_text("old trash")
    with patch("lib.brain.delete_file_chunks"):
        handle_brain_trash(
            "Cards/foo.md", str(brain_with_note), db_path=":memory:"
        )
    trash_files = list(trash_dest.glob("foo.*.md"))
    assert len(trash_files) == 1
    origin_file = trash_files[0].with_suffix(".origin")
    assert origin_file.exists()
    assert "Cards/foo.md" in origin_file.read_text()


# ── brain_restore ─────────────────────────────────────────────────────

def test_restore_moves_file_back(brain_with_note):
    with patch("lib.brain.delete_file_chunks"):
        handle_brain_trash(
            "Cards/foo.md", str(brain_with_note), db_path=":memory:"
        )
    result = handle_brain_restore(".trash/Cards/foo.md", str(brain_with_note))
    assert (brain_with_note / "Cards" / "foo.md").exists()
    assert "Restored" in result


def test_restore_with_origin_sidecar(brain_with_note):
    trash_dir = brain_with_note / ".trash" / "Cards"
    trash_dir.mkdir(parents=True, exist_ok=True)
    suffixed = trash_dir / "foo.20260327-143022.md"
    suffixed.write_text("---\ntitle: Foo\n---\n\nHello.")
    origin = trash_dir / "foo.20260327-143022.origin"
    origin.write_text("Cards/foo.md")
    # Remove original so restore can place it back
    (brain_with_note / "Cards" / "foo.md").unlink()
    result = handle_brain_restore(
        ".trash/Cards/foo.20260327-143022.md", str(brain_with_note)
    )
    assert (brain_with_note / "Cards" / "foo.md").exists()
    assert not origin.exists()
    assert "Restored" in result


def test_restore_conflict_returns_error(brain_with_note):
    with patch("lib.brain.delete_file_chunks"):
        handle_brain_trash(
            "Cards/foo.md", str(brain_with_note), db_path=":memory:"
        )
    # Recreate the file at original location to cause conflict
    (brain_with_note / "Cards" / "foo.md").write_text("conflict")
    result = handle_brain_restore(".trash/Cards/foo.md", str(brain_with_note))
    assert "Error" in result


def test_restore_rejects_path_not_in_trash(brain_with_note):
    result = handle_brain_restore("Cards/foo.md", str(brain_with_note))
    assert "Error" in result
