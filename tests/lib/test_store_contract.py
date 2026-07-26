"""Backend-parameterised contract for the index-store port.

Runs against SqliteVecStore always (skipped automatically on hosts whose
sqlite lacks extension support, via conftest collect_ignore is NOT used
here — this file guards itself) and against PgVectorStore under
-m integration using a throwaway pgvector container.
"""
import sqlite3
import pytest

DIM = 4


def _sqlite_available():
    try:
        conn = sqlite3.connect(":memory:")
        conn.enable_load_extension(True)
        conn.close()
        return True
    except AttributeError:
        return False


@pytest.fixture(scope="session")
def pg_dsn():
    tc = pytest.importorskip("testcontainers.postgres")
    with tc.PostgresContainer("pgvector/pgvector:pg17") as pg:
        # psycopg DSN (testcontainers returns a SQLAlchemy-style URL)
        yield pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")


@pytest.fixture(params=[
    pytest.param("sqlite", marks=pytest.mark.skipif(
        not _sqlite_available(), reason="sqlite extension support unavailable")),
    pytest.param("pgvector", marks=pytest.mark.integration),
])
def store(request, tmp_path):
    if request.param == "sqlite":
        from lib.vectorstore import SqliteVecStore
        s = SqliteVecStore(str(tmp_path / "contract.db"))
    else:
        from lib.pgstore import PgVectorStore
        dsn = request.getfixturevalue("pg_dsn")
        s = PgVectorStore(dsn)
        # isolate: wipe tables between tests
        with s._pool.connection() as conn:
            conn.execute("DROP TABLE IF EXISTS chunks")
            conn.execute("DROP TABLE IF EXISTS meta")
    s.init(embedding_dim=DIM)
    yield s
    if request.param == "pgvector":
        close = getattr(s, "close", None)
        if close is not None:
            close()


def _put(store, fp, i, vec, layer="work", content=None):
    store.upsert_chunk(
        filepath=fp, chunk_index=i, content=content or f"{fp}#{i}",
        content_hash=f"h-{fp}-{i}", embedding=vec,
        meta={"title": fp, "type": "note", "status": None,
              "created": "2026-07-26", "tags": ["t"], "scope": None,
              "layer": layer},
    )


def test_init_is_idempotent(store):
    store.init(embedding_dim=DIM)          # second call, same dim: fine
    assert store.stored_dim() == DIM


def test_init_dim_mismatch_raises(store):
    with pytest.raises(ValueError, match="[Dd]imension"):
        store.init(embedding_dim=DIM + 1)


def test_upsert_and_search_roundtrip(store):
    _put(store, "a.md", 0, [1.0, 0.0, 0.0, 0.0])
    results = store.search([1.0, 0.0, 0.0, 0.0], k=5)
    assert len(results) == 1
    r = results[0]
    assert r["filepath"] == "a.md"
    assert r["tags"] == ["t"]
    assert "distance" in r


def test_upsert_updates_on_conflict(store):
    _put(store, "a.md", 0, [1.0, 0.0, 0.0, 0.0], content="old")
    _put(store, "a.md", 0, [1.0, 0.0, 0.0, 0.0], content="new")
    results = store.search([1.0, 0.0, 0.0, 0.0], k=5)
    assert [r["content"] for r in results] == ["new"]


def test_search_ranks_by_distance(store):
    _put(store, "near.md", 0, [1.0, 0.0, 0.0, 0.0])
    _put(store, "far.md", 0, [0.0, 1.0, 0.0, 0.0])
    results = store.search([1.0, 0.1, 0.0, 0.0], k=2)
    assert [r["filepath"] for r in results] == ["near.md", "far.md"]


def test_layer_filter_recall_not_truncated_by_forbidden_neighbours(store):
    # 5 forbidden chunks closer to the query than the 3 visible ones:
    # a naive fixed-k post-filter would return < 3 visible results.
    for i in range(5):
        _put(store, f"secret{i}.md", 0, [1.0, 0.0, 0.0, 0.0], layer="fiction")
    for i in range(3):
        _put(store, f"work{i}.md", 0, [0.0, 1.0, 0.0, 0.0], layer="work")
    results = store.search([1.0, 0.0, 0.0, 0.0], k=3, allowed_layers=("work",))
    assert len(results) == 3
    assert all(r["layer"] == "work" for r in results)


def test_layer_deny_all_returns_empty(store):
    _put(store, "a.md", 0, [1.0, 0.0, 0.0, 0.0])
    assert store.search([1.0, 0.0, 0.0, 0.0], k=5, allowed_layers=()) == []


def test_layer_wildcard_unconstrained(store):
    _put(store, "a.md", 0, [1.0, 0.0, 0.0, 0.0], layer="fiction")
    results = store.search([1.0, 0.0, 0.0, 0.0], k=5, allowed_layers=("*",))
    assert len(results) == 1


def test_file_hashes_prune_list_delete(store):
    for i in range(4):
        _put(store, "a.md", i, [float(i), 0.0, 0.0, 0.0])
    _put(store, "b.md", 0, [0.0, 0.0, 1.0, 0.0])

    assert set(store.get_file_hashes("a.md")) == {0, 1, 2, 3}
    store.prune_file_chunks("a.md", keep_below=2)
    assert set(store.get_file_hashes("a.md")) == {0, 1}
    assert sorted(store.list_filepaths()) == ["a.md", "b.md"]
    store.delete_file_chunks("a.md")
    assert store.list_filepaths() == ["b.md"]
    assert store.get_file_hashes("a.md") == {}


def test_get_chunk_embeddings_roundtrip(store):
    _put(store, "a.md", 0, [0.25, 0.5, -1.0, 2.0])
    vecs = store.get_chunk_embeddings("a.md")
    assert len(vecs) == 1
    assert vecs[0] == pytest.approx([0.25, 0.5, -1.0, 2.0])
