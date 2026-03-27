# tests/test_brain_api.py
"""Unit tests for the brain REST API."""
import os
import sys
import textwrap

import pytest
from unittest.mock import patch, MagicMock

# Stub out native-only deps before anything imports them
if "sqlite_vec" not in sys.modules:
    sys.modules["sqlite_vec"] = MagicMock()
if "openai" not in sys.modules:
    sys.modules["openai"] = MagicMock()

from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def brain_env(tmp_path):
    """Point brain at a temporary directory for every test."""
    brain_dir = tmp_path / "brain"
    brain_dir.mkdir()
    ai_dir = brain_dir / ".ai"
    ai_dir.mkdir()
    tpl_dir = brain_dir / ".zk" / "templates"
    tpl_dir.mkdir(parents=True)
    (tpl_dir / "default.md").write_text("---\ntitle: {{title}}\n---\n")
    (tpl_dir / "project.md").write_text("---\ntitle: {{title}}\ntype: project\n---\n")

    with patch.dict(os.environ, {"BRAIN_PATH": str(brain_dir)}):
        # Re-import to pick up patched env
        import importlib
        import lib.config
        importlib.reload(lib.config)
        import brain_api
        importlib.reload(brain_api)
        brain_api._cfg = lib.config.Config()
        yield brain_dir, brain_api


@pytest.fixture
def client(brain_env):
    _, api_module = brain_env
    return TestClient(api_module.app)


@pytest.fixture
def sample_note(brain_env):
    brain_dir, _ = brain_env
    note_path = brain_dir / "Projects" / "test-project.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(textwrap.dedent("""\
        ---
        title: Test Project
        type: project
        status: current
        tags: [python, api]
        ---

        # Overview

        A test project for API validation.

        # Tasks

        - Build API layer
        - Write tests

        # References

        - [[other-note]]
        - [[design-doc]]
    """))
    return "Projects/test-project.md"


# ── Read ────────────────────────────────────────────────────────────


def test_read_note(client, sample_note):
    resp = client.get(f"/api/notes/{sample_note}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["filepath"] == sample_note
    assert data["frontmatter"]["title"] == "Test Project"
    assert data["frontmatter"]["type"] == "project"
    assert data["body"].startswith("# Overview")
    assert len(data["wikilinks"]) == 2
    assert data["wikilinks"][0]["target"] == "other-note"


def test_read_note_not_found(client):
    resp = client.get("/api/notes/nonexistent.md")
    assert resp.status_code == 404


def test_read_note_path_traversal(client, brain_env):
    brain_dir, _ = brain_env
    # Starlette normalises ../../ in URLs, so use an absolute path outside brain
    resp = client.get("/api/notes//etc/passwd")
    # Either 403 (path outside brain) or 404 (normalised away) is acceptable
    assert resp.status_code in (403, 404)


# ── Write (PUT) ─────────────────────────────────────────────────────


def test_write_note(client, brain_env):
    brain_dir, _ = brain_env
    resp = client.put(
        "/api/notes/Cards/new-card.md",
        json={"content": "---\ntitle: New Card\n---\n\nHello."},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert (brain_dir / "Cards" / "new-card.md").read_text() == "---\ntitle: New Card\n---\n\nHello."


def test_write_note_overwrites(client, sample_note, brain_env):
    brain_dir, _ = brain_env
    client.put(f"/api/notes/{sample_note}", json={"content": "replaced"})
    assert (brain_dir / sample_note).read_text() == "replaced"


# ── Surgical Edit (PATCH) ──────────────────────────────────────────


def test_patch_update_frontmatter(client, sample_note, brain_env):
    brain_dir, _ = brain_env
    resp = client.patch(
        f"/api/notes/{sample_note}",
        json={"op": "update_frontmatter", "frontmatter": {"status": "archived", "effort": "q1"}},
    )
    assert resp.status_code == 200
    content = (brain_dir / sample_note).read_text()
    assert "status: archived" in content
    assert "effort: q1" in content
    # Body intact
    assert "A test project for API validation." in content


def test_patch_replace_section(client, sample_note, brain_env):
    brain_dir, _ = brain_env
    resp = client.patch(
        f"/api/notes/{sample_note}",
        json={"op": "replace_section", "heading": "Tasks", "body": "- All done!"},
    )
    assert resp.status_code == 200
    content = (brain_dir / sample_note).read_text()
    assert "- All done!" in content
    assert "- Build API layer" not in content


def test_patch_append_to_section(client, sample_note, brain_env):
    brain_dir, _ = brain_env
    resp = client.patch(
        f"/api/notes/{sample_note}",
        json={"op": "append_to_section", "heading": "Tasks", "body": "- Deploy to prod"},
    )
    assert resp.status_code == 200
    content = (brain_dir / sample_note).read_text()
    assert "- Deploy to prod" in content
    assert "- Write tests" in content  # original preserved


def test_patch_prepend_to_section(client, sample_note, brain_env):
    brain_dir, _ = brain_env
    resp = client.patch(
        f"/api/notes/{sample_note}",
        json={"op": "prepend_to_section", "heading": "Tasks", "body": "- First thing"},
    )
    assert resp.status_code == 200
    content = (brain_dir / sample_note).read_text()
    first_pos = content.index("- First thing")
    build_pos = content.index("- Build API layer")
    assert first_pos < build_pos


def test_patch_replace_lines(client, sample_note, brain_env):
    brain_dir, _ = brain_env
    resp = client.patch(
        f"/api/notes/{sample_note}",
        json={"op": "replace_lines", "start_line": 1, "end_line": 2, "replacement": "---"},
    )
    assert resp.status_code == 200


def test_patch_find_replace(client, sample_note, brain_env):
    brain_dir, _ = brain_env
    resp = client.patch(
        f"/api/notes/{sample_note}",
        json={"op": "find_replace", "find": "API validation", "replace": "REST testing"},
    )
    assert resp.status_code == 200
    content = (brain_dir / sample_note).read_text()
    assert "REST testing" in content
    assert "API validation" not in content


def test_patch_insert_wikilink(client, sample_note, brain_env):
    brain_dir, _ = brain_env
    resp = client.patch(
        f"/api/notes/{sample_note}",
        json={"op": "insert_wikilink", "target": "new-reference", "context_heading": "References"},
    )
    assert resp.status_code == 200
    content = (brain_dir / sample_note).read_text()
    assert "[[new-reference]]" in content


def test_patch_insert_wikilink_duplicate(client, sample_note):
    resp = client.patch(
        f"/api/notes/{sample_note}",
        json={"op": "insert_wikilink", "target": "other-note"},
    )
    assert resp.status_code == 200
    assert "already present" in resp.json()["detail"]


def test_patch_section_not_found(client, sample_note):
    resp = client.patch(
        f"/api/notes/{sample_note}",
        json={"op": "replace_section", "heading": "Nonexistent", "body": "x"},
    )
    assert resp.status_code == 404


def test_patch_missing_required_field(client, sample_note):
    resp = client.patch(
        f"/api/notes/{sample_note}",
        json={"op": "update_frontmatter"},
    )
    assert resp.status_code == 400


# ── Backlinks ───────────────────────────────────────────────────────


def test_backlinks(client, sample_note, brain_env):
    brain_dir, _ = brain_env
    # Create a note that links to our sample
    linker = brain_dir / "Cards" / "linker.md"
    linker.parent.mkdir(parents=True, exist_ok=True)
    linker.write_text("---\ntitle: Linker\n---\n\nSee [[test-project]] for details.")

    resp = client.get(f"/api/notes/{sample_note}/backlinks")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "Linker"


def test_backlinks_empty(client, sample_note):
    resp = client.get(f"/api/notes/{sample_note}/backlinks")
    assert resp.status_code == 200
    assert resp.json() == []


# ── Templates ───────────────────────────────────────────────────────


def test_list_templates(client):
    resp = client.get("/api/templates")
    assert resp.status_code == 200
    data = resp.json()
    assert "default" in data
    assert "project" in data


# ── List / Query ────────────────────────────────────────────────────


def test_list_notes_delegates_to_zk(client):
    with patch("brain_api.handle_brain_query", return_value="Projects/a.md\nCards/b.md\n"):
        resp = client.get("/api/notes", params={"tag": "python"})
    assert resp.status_code == 200
    assert resp.json() == ["Projects/a.md", "Cards/b.md"]


def test_list_notes_empty(client):
    with patch("brain_api.handle_brain_query", return_value="No notes matched the query."):
        resp = client.get("/api/notes")
    assert resp.status_code == 200
    assert resp.json() == []


# ── Search ──────────────────────────────────────────────────────────


def test_search_returns_structured(client):
    mock_results = [
        {
            "filepath": "Cards/test.md",
            "content": "Some content.",
            "title": "Test Card",
            "type": "note",
            "status": "current",
            "created": "2026-03-16",
            "tags": ["testing"],
            "distance": 0.15,
        }
    ]
    with patch("lib.embeddings.get_embedding", return_value=[0.1] * 1024), \
         patch("lib.db.search_chunks", return_value=mock_results):
        resp = client.get("/api/search", params={"q": "test"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["filepath"] == "Cards/test.md"
    assert data[0]["title"] == "Test Card"
    assert data[0]["tags"] == ["testing"]
    assert data[0]["distance"] == 0.15
