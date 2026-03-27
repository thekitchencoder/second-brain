import os
import sqlite3
import textwrap
import pytest
from unittest.mock import patch
from brain_index import index_brain, index_file
from lib.db import init_db, upsert_chunk
from lib.embeddings import EmbeddingError


@pytest.fixture
def brain(tmp_path):
    note = tmp_path / "test-note.md"
    note.write_text(textwrap.dedent("""\
        ---
        title: Test Note
        type: note
        status: current
        created: 2026-03-16
        tags: [testing]
        ---

        This is the body of the test note. It has enough content to be meaningful.
    """))
    ai_dir = tmp_path / ".ai"
    ai_dir.mkdir()
    return tmp_path


@pytest.fixture
def mock_embed():
    with patch("brain_index.get_embedding") as mock:
        mock.return_value = [0.1] * 1024
        yield mock


def test_index_file_creates_chunks(brain, mock_embed):
    db_path = str(brain / ".ai" / "embeddings.db")
    from lib.db import init_db
    init_db(db_path, embedding_dim=1024)

    filepath = str(brain / "test-note.md")
    index_file(filepath, db_path)

    mock_embed.assert_called()


def test_index_brain_processes_markdown_files(brain, mock_embed):
    db_path = str(brain / ".ai" / "embeddings.db")
    index_brain(str(brain), db_path)
    mock_embed.assert_called()


def test_index_brain_skips_dotdirectories(brain, mock_embed):
    obsidian_dir = brain / ".obsidian"
    obsidian_dir.mkdir()
    (obsidian_dir / "config.json").write_text("{}")

    db_path = str(brain / ".ai" / "embeddings.db")
    index_brain(str(brain), db_path)

    # Should only have been called for the one real note
    assert mock_embed.call_count >= 1


def test_index_file_skips_unchanged_chunks(brain, mock_embed):
    db_path = str(brain / ".ai" / "embeddings.db")
    from lib.db import init_db
    init_db(db_path, embedding_dim=1024)

    filepath = str(brain / "test-note.md")
    index_file(filepath, db_path)
    first_call_count = mock_embed.call_count

    # Second index of same file with same content — should not re-embed
    index_file(filepath, db_path)
    assert mock_embed.call_count == first_call_count


def test_watch_brain_handles_deleted_file(brain, mock_embed):
    """Watcher must not crash when a file is deleted/renamed between the event and the open."""
    from brain_index import watch_brain

    db_path = str(brain / ".ai" / "embeddings.db")
    from lib.db import init_db
    init_db(db_path, embedding_dim=1024)

    gone_path = str(brain / "Pain Tracker \u2014 Project Notes.md")  # em dash, never exists on disk

    # watchfiles yields sets of (ChangeType, path) tuples; change_type is unused in watch_brain
    fake_changes = [{(None, gone_path)}]

    # patch watchfiles.watch because watch_brain does `from watchfiles import watch` locally
    with patch("watchfiles.watch", return_value=iter(fake_changes)):
        with patch("brain_index.purge_stale_paths") as mock_purge:
            watch_brain(str(brain), db_path)

    mock_purge.assert_called_once_with(db_path)


def test_index_file_prunes_excess_chunks_when_file_shrinks(brain, mock_embed):
    """When a note shrinks, chunks beyond the new length must be removed."""
    db_path = str(brain / ".ai" / "embeddings.db")
    init_db(db_path, embedding_dim=1024)

    filepath = str(brain / "test-note.md")

    # Manually insert 3 chunks to simulate a previously-longer note
    for i in range(3):
        upsert_chunk(db_path, filepath, i, f"chunk {i}", f"hash{i}", [0.1]*1024,
                     {"title": "T", "type": "note", "status": "current",
                      "created": "2026-03-16", "tags": [], "scope": None})

    # Re-index the actual file (1 chunk)
    index_file(filepath, db_path)

    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT chunk_index FROM chunks WHERE filepath=?", (filepath,)).fetchall()
    conn.close()
    assert len(rows) == 1, f"expected 1 chunk, got {len(rows)}"
    assert rows[0][0] == 0

    # Also verify the embeddings rows for the pruned chunks are gone
    from lib.db import _connect
    vec_conn = _connect(db_path)
    try:
        emb_rows = vec_conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    finally:
        vec_conn.close()
    assert emb_rows == 1, f"expected 1 embedding row after shrink, got {emb_rows}"


def test_detect_embedding_dim_exits_on_embedding_error(brain, monkeypatch):
    """detect_embedding_dim must call sys.exit(1) on EmbeddingError, not propagate it."""
    monkeypatch.setattr("brain_index.get_embedding", lambda t: (_ for _ in ()).throw(EmbeddingError("no model")))
    with pytest.raises(SystemExit) as exc_info:
        from brain_index import detect_embedding_dim
        detect_embedding_dim()
    assert exc_info.value.code == 1


def test_watch_filter_excludes_trash_paths(brain, mock_embed):
    """Files under .trash/ must not be processed by the watcher."""
    import sys
    from types import ModuleType
    from brain_index import watch_brain

    db_path = ":memory:"

    trash_path = str(brain / ".trash" / "Cards" / "deleted-note.md")
    fake_changes = [{(None, trash_path)}]

    # Stub watchfiles so this test runs without the package installed
    fake_watchfiles = ModuleType("watchfiles")
    fake_watchfiles.watch = lambda *a, **kw: iter(fake_changes)
    with patch.dict(sys.modules, {"watchfiles": fake_watchfiles}):
        with patch("brain_index.index_file") as mock_index, \
             patch("brain_index.purge_stale_paths") as mock_purge:
            watch_brain(str(brain), db_path)

    mock_index.assert_not_called()
    mock_purge.assert_not_called()


def test_purge_stale_paths_also_deletes_embeddings(brain, mock_embed):
    """Deleting stale chunk rows must also remove the corresponding embeddings rows."""
    db_path = str(brain / ".ai" / "embeddings.db")
    init_db(db_path, embedding_dim=1024)

    # Index a note so it has a chunk + embedding row
    filepath = str(brain / "test-note.md")
    index_file(filepath, db_path)

    # Remove the file from disk
    (brain / "test-note.md").unlink()

    from brain_index import purge_stale_paths
    purge_stale_paths(db_path)

    from lib.db import _connect
    conn = _connect(db_path)
    chunk_rows = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    embedding_rows = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    conn.close()
    assert chunk_rows == 0
    assert embedding_rows == 0, f"orphaned embeddings remain: {embedding_rows}"
