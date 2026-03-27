# tests/lib/test_db.py
import json
import sqlite3
import pytest
from lib.db import init_db, upsert_chunk, search_chunks, get_chunk_embeddings, delete_file_chunks, _connect


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


def test_init_db_creates_tables(db_path):
    init_db(db_path, embedding_dim=4)
    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "chunks" in tables
    conn.close()


def test_upsert_chunk_inserts(db_path):
    init_db(db_path, embedding_dim=4)
    upsert_chunk(
        db_path=db_path,
        filepath="notes/foo.md",
        chunk_index=0,
        content="Some content here.",
        content_hash="abc123",
        embedding=[0.1, 0.2, 0.3, 0.4],
        meta={"title": "Foo", "type": "note", "status": "draft",
              "created": "2026-03-16", "tags": ["a"], "scope": None},
    )
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT filepath, title, type FROM chunks").fetchone()
    assert row == ("notes/foo.md", "Foo", "note")
    conn.close()


def test_upsert_chunk_updates_on_conflict(db_path):
    init_db(db_path, embedding_dim=4)
    meta = {"title": "Foo", "type": "note", "status": "draft",
            "created": "2026-03-16", "tags": [], "scope": None}
    upsert_chunk(db_path, "notes/foo.md", 0, "Original.", "hash1", [0.1]*4, meta)
    upsert_chunk(db_path, "notes/foo.md", 0, "Updated.", "hash2", [0.2]*4, meta)
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT content FROM chunks WHERE filepath='notes/foo.md'").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "Updated."
    conn.close()


def test_search_chunks_returns_results(db_path):
    init_db(db_path, embedding_dim=4)
    meta = {"title": "Foo", "type": "note", "status": "current",
            "created": "2026-03-16", "tags": ["test"], "scope": "testing"}
    upsert_chunk(db_path, "notes/foo.md", 0, "Content about foo.", "h1", [1.0, 0.0, 0.0, 0.0], meta)
    upsert_chunk(db_path, "notes/bar.md", 0, "Content about bar.", "h2", [0.0, 1.0, 0.0, 0.0], meta)

    results = search_chunks(db_path, query_embedding=[1.0, 0.0, 0.0, 0.0], limit=1)
    assert len(results) == 1
    assert results[0]["filepath"] == "notes/foo.md"
    assert results[0]["title"] == "Foo"
    assert results[0]["type"] == "note"
    assert results[0]["status"] == "current"
    assert "distance" in results[0]


def test_get_chunk_embeddings_returns_vectors(db_path):
    init_db(db_path, embedding_dim=4)
    meta = {"title": "X", "type": "note", "status": "draft",
            "created": "2026-03-16", "tags": [], "scope": None}
    upsert_chunk(db_path, "notes/x.md", 0, "text", "h1", [0.1, 0.2, 0.3, 0.4], meta)
    upsert_chunk(db_path, "notes/x.md", 1, "more", "h2", [0.5, 0.6, 0.7, 0.8], meta)

    vectors = get_chunk_embeddings(db_path, "notes/x.md")
    assert len(vectors) == 2
    assert len(vectors[0]) == 4


def test_init_db_rejects_non_positive_dim(db_path):
    with pytest.raises(ValueError, match="positive integer"):
        init_db(db_path, embedding_dim=0)


def test_init_db_rejects_negative_dim(db_path):
    with pytest.raises(ValueError, match="positive integer"):
        init_db(db_path, embedding_dim=-1)


def test_init_db_stores_embedding_dim_in_meta(db_path):
    """meta table should record embedding_dim as a string value."""
    init_db(db_path, embedding_dim=4)
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT value FROM meta WHERE key='embedding_dim'").fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "4"


def test_init_db_rejects_bool_dim(db_path):
    with pytest.raises(ValueError, match="positive integer"):
        init_db(db_path, embedding_dim=True)


def test_delete_file_chunks_removes_chunks_and_embeddings(db_path):
    init_db(db_path, embedding_dim=4)
    meta = {"title": "X", "type": "note", "status": "draft",
            "created": "2026-03-27", "tags": [], "scope": None}
    upsert_chunk(db_path, "Cards/foo.md", 0, "chunk 0", "h0", [0.1, 0.2, 0.3, 0.4], meta)
    upsert_chunk(db_path, "Cards/foo.md", 1, "chunk 1", "h1", [0.2, 0.3, 0.4, 0.5], meta)

    delete_file_chunks(db_path, "Cards/foo.md")

    conn = sqlite3.connect(db_path)
    chunk_rows = conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE filepath='Cards/foo.md'"
    ).fetchone()[0]
    conn.close()
    assert chunk_rows == 0

    vec_conn = _connect(db_path)
    try:
        emb_rows = vec_conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    finally:
        vec_conn.close()
    assert emb_rows == 0


def test_delete_file_chunks_does_not_affect_other_filepaths(db_path):
    init_db(db_path, embedding_dim=4)
    meta = {"title": "X", "type": "note", "status": "draft",
            "created": "2026-03-27", "tags": [], "scope": None}
    upsert_chunk(db_path, "Cards/foo.md", 0, "chunk foo", "hf", [0.1, 0.2, 0.3, 0.4], meta)
    upsert_chunk(db_path, "Cards/bar.md", 0, "chunk bar", "hb", [0.5, 0.6, 0.7, 0.8], meta)

    delete_file_chunks(db_path, "Cards/foo.md")

    conn = sqlite3.connect(db_path)
    bar_rows = conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE filepath='Cards/bar.md'"
    ).fetchone()[0]
    conn.close()
    assert bar_rows == 1
