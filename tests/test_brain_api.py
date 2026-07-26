# tests/test_brain_api.py
"""Unit tests for the brain REST API."""
import json
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

    profile_dir = brain_dir / ".brain"
    profile_dir.mkdir(parents=True)
    (profile_dir / "profile.toml").write_text(textwrap.dedent('''\
        name = "ace"
        folders = ["Atlas", "Efforts", "Cards", "Calendar", "Sources"]
        [plugin]
        name = "second-brain"
        author = "kitchencoder"
        marker = "brain"
        mcp_server = "brain"
        [fields.status]
        kind = "scalar"
        label = "Note status"
        [fields.type]
        kind = "scalar"
        label = "Note type"
        [fields.intensity]
        kind = "scalar"
        label = "Effort intensity"
        query_desc = "Filter by effort intensity (focus, ongoing, simmering)."
        [fields.effort]
        kind = "scalar"
        label = "Effort"
        query_desc = "Filter by effort field in frontmatter."
        [skills]
        global = []
        vault = []
        [auth]
        mode = "none"
    '''))

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
    note_path = brain_dir / "Efforts" / "test-effort.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(textwrap.dedent("""\
        ---
        title: Test Effort
        type: effort
        status: active
        intensity: focus
        tags: [python, api]
        ---

        # Overview

        A test effort for API validation.

        # Tasks

        - Build API layer
        - Write tests

        # References

        - [[other-note]]
        - [[design-doc]]
    """))
    return "Efforts/test-effort.md"


# ── Read ────────────────────────────────────────────────────────────


def test_read_note(client, sample_note):
    resp = client.get(f"/api/notes/{sample_note}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["filepath"] == sample_note
    assert data["frontmatter"]["title"] == "Test Effort"
    assert data["frontmatter"]["type"] == "effort"
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
    assert "A test effort for API validation." in content


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
    linker.write_text("---\ntitle: Linker\n---\n\nSee [[test-effort]] for details.")

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


def test_list_templates_returns_clean_list(tmp_path, monkeypatch, brain_env):
    """list_templates endpoint must return plain names, not parsed formatted string."""
    import brain_api as _brain_api
    templates_dir = tmp_path / ".zk" / "templates"
    templates_dir.mkdir(parents=True)
    (templates_dir / "effort.md").write_text("")
    (templates_dir / "discovery.md").write_text("")
    monkeypatch.setattr(_brain_api, "_cfg", type("C", (), {"brain_path": str(tmp_path)})())

    result = _brain_api.list_templates()
    assert isinstance(result, list)
    assert "effort" in result
    assert "discovery" in result
    assert not any("Available" in item for item in result)
    assert not any(item.startswith(" ") for item in result)


# ── List / Query ────────────────────────────────────────────────────


def test_list_notes_delegates_to_zk(client):
    with patch("brain_api.handle_brain_query", return_value="Efforts/a.md\nCards/b.md\n"):
        resp = client.get("/api/notes", params={"tag": "python"})
    assert resp.status_code == 200
    assert resp.json() == ["Efforts/a.md", "Cards/b.md"]


def test_list_notes_empty(client):
    with patch("brain_api.handle_brain_query", return_value="No notes matched the query."):
        resp = client.get("/api/notes")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_notes_invalid_param_returns_400(client):
    """Validation errors from handle_brain_query must surface as HTTP 400, not 200 with error text."""
    with patch("brain_api.handle_brain_query", return_value="Invalid tag: must contain only letters, digits, hyphens and underscores"):
        resp = client.get("/api/notes", params={"tag": "bad tag!"})
    assert resp.status_code == 400
    assert "Invalid tag" in resp.json()["detail"]


def test_list_notes_filters_promoted_field(client, brain_env):
    """GET /api/notes?intensity=focus returns only notes with intensity: focus."""
    brain_dir, _ = brain_env
    efforts = brain_dir / "Efforts"
    efforts.mkdir(parents=True, exist_ok=True)
    (efforts / "a.md").write_text("---\ntitle: A\nintensity: focus\n---\n\nBody A.\n")
    (efforts / "b.md").write_text("---\ntitle: B\nintensity: simmering\n---\n\nBody B.\n")

    resp = client.get("/api/notes", params={"intensity": "focus"})
    assert resp.status_code == 200
    data = resp.json()
    assert "Efforts/a.md" in data
    assert "Efforts/b.md" not in data


def test_list_notes_where_escape_hatch(client, brain_env):
    """GET /api/notes?where={"layer":"deep-canon"} filters an un-promoted frontmatter key."""
    brain_dir, _ = brain_env
    atlas = brain_dir / "Atlas"
    atlas.mkdir(parents=True, exist_ok=True)
    (atlas / "deep.md").write_text("---\ntitle: Deep\nlayer: deep-canon\n---\n\nBody.\n")
    (atlas / "surface.md").write_text("---\ntitle: Surface\nlayer: surface\n---\n\nBody.\n")

    resp = client.get("/api/notes", params={"where": json.dumps({"layer": "deep-canon"})})
    assert resp.status_code == 200
    data = resp.json()
    assert "Atlas/deep.md" in data
    assert "Atlas/surface.md" not in data


def test_list_notes_where_nonstring_value_returns_400(client):
    """A non-string where value must fail loud (400), not crash the regex validator (500)."""
    resp = client.get("/api/notes", params={"where": json.dumps({"count": 5})})
    assert resp.status_code == 400


def test_list_notes_where_non_object_json_returns_400(client):
    """Valid JSON that isn't an object (e.g. a bare number) must fail loud (400), not 500 on .items()."""
    resp = client.get("/api/notes", params={"where": "5"})
    assert resp.status_code == 400


def test_list_notes_unknown_field_returns_400(client):
    """A typo'd or un-promoted query param fails loud instead of returning every note."""
    resp = client.get("/api/notes", params={"intnsity": "focus"})
    assert resp.status_code == 400
    assert "unknown filter field" in resp.json()["detail"].lower()


def test_list_notes_malformed_where_returns_400(client):
    resp = client.get("/api/notes", params={"where": "not-json"})
    assert resp.status_code == 400


def test_create_note_traversal_template_returns_400(client):
    """Template path traversal must return HTTP 400, not 200 success."""
    with patch("brain_api.handle_brain_create", return_value="Invalid template name: must be a bare filename with no path separators"):
        resp = client.post("/api/notes", json={"template": "../../../etc/passwd", "title": "Hack"})
    assert resp.status_code == 400
    assert "Invalid template name" in resp.json()["detail"]


# ── Trash / Restore ──────────────────────────────────────────────────


def test_trash_note(client, sample_note, brain_env):
    brain_dir, _ = brain_env
    with patch("lib.vectorstore.SqliteVecStore.delete_file_chunks"):
        resp = client.post(f"/api/notes/{sample_note}/trash")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "Trashed" in data["detail"]
    assert not (brain_dir / sample_note).exists()


def test_trash_nonexistent_returns_404(client):
    with patch("lib.vectorstore.SqliteVecStore.delete_file_chunks"):
        resp = client.post("/api/notes/nonexistent.md/trash")
    assert resp.status_code == 404


def test_restore_note(client, sample_note, brain_env):
    brain_dir, _ = brain_env
    with patch("lib.vectorstore.SqliteVecStore.delete_file_chunks"):
        client.post(f"/api/notes/{sample_note}/trash")
    trash_path = f".trash/{sample_note}"
    resp = client.post(f"/api/notes/{trash_path}/restore")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "Restored" in data["detail"]
    assert (brain_dir / sample_note).exists()


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
         patch("lib.vectorstore._db_search", return_value=mock_results):
        resp = client.get("/api/search", params={"q": "test"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["filepath"] == "Cards/test.md"
    assert data[0]["title"] == "Test Card"
    assert data[0]["tags"] == ["testing"]
    assert data[0]["distance"] == 0.15
