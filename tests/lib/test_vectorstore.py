# tests/lib/test_vectorstore.py
import sys
from unittest.mock import MagicMock
if "sqlite_vec" not in sys.modules:
    sys.modules["sqlite_vec"] = MagicMock()


def test_store_delegates_to_db(monkeypatch):
    import lib.vectorstore as vs
    calls = {}
    monkeypatch.setattr(vs, "_db_search", lambda db, emb, limit: calls.setdefault("search", (db, limit)) or [])
    store = vs.SqliteVecStore("/tmp/x.db")
    store.search([0.1, 0.2], k=5)
    assert calls["search"] == ("/tmp/x.db", 5)


def test_store_init_delegates(monkeypatch):
    import lib.vectorstore as vs
    calls = {}
    monkeypatch.setattr("lib.vectorstore._db_init",
                        lambda path, embedding_dim, model="": calls.update(
                            path=path, dim=embedding_dim, model=model))
    vs.SqliteVecStore("/tmp/x.db").init(1024, model="mxbai")
    assert calls == {"path": "/tmp/x.db", "dim": 1024, "model": "mxbai"}


def test_store_stored_dim_delegates(monkeypatch):
    import lib.vectorstore as vs
    monkeypatch.setattr("lib.vectorstore._db_stored_dim", lambda path: 768)
    assert vs.SqliteVecStore("/tmp/x.db").stored_dim() == 768


def test_store_file_hashes_delegates(monkeypatch):
    import lib.vectorstore as vs
    monkeypatch.setattr("lib.vectorstore._db_file_hashes",
                        lambda path, fp: {0: "h"})
    assert vs.SqliteVecStore("/tmp/x.db").get_file_hashes("a.md") == {0: "h"}


def test_store_prune_delegates(monkeypatch):
    import lib.vectorstore as vs
    calls = {}
    monkeypatch.setattr("lib.vectorstore._db_prune",
                        lambda path, fp, keep_below: calls.update(fp=fp, kb=keep_below))
    vs.SqliteVecStore("/tmp/x.db").prune_file_chunks("a.md", 3)
    assert calls == {"fp": "a.md", "kb": 3}


def test_store_list_filepaths_delegates(monkeypatch):
    import lib.vectorstore as vs
    monkeypatch.setattr("lib.vectorstore._db_list_paths", lambda path: ["a.md"])
    assert vs.SqliteVecStore("/tmp/x.db").list_filepaths() == ["a.md"]


import pytest
import lib.vectorstore as vs
from lib.vectorstore import get_store


def test_get_store_default_is_sqlite(monkeypatch):
    monkeypatch.delenv("BRAIN_VECTOR_STORE", raising=False)
    store = get_store("/tmp/x.db")
    assert isinstance(store, vs.SqliteVecStore)
    assert store.db_path == "/tmp/x.db"


def test_get_store_explicit_sqlite(monkeypatch):
    monkeypatch.setenv("BRAIN_VECTOR_STORE", "sqlite")
    assert isinstance(get_store("/tmp/x.db"), vs.SqliteVecStore)


def test_get_store_pgvector_without_dsn_fails_loud(monkeypatch):
    monkeypatch.setenv("BRAIN_VECTOR_STORE", "pgvector")
    monkeypatch.delenv("BRAIN_DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="BRAIN_DATABASE_URL"):
        get_store("/tmp/x.db")


def test_get_store_unknown_backend_fails_loud(monkeypatch):
    monkeypatch.setenv("BRAIN_VECTOR_STORE", "qdrant")
    with pytest.raises(RuntimeError, match="qdrant"):
        get_store("/tmp/x.db")


def test_get_store_pgvector_missing_module_fails_loud(monkeypatch):
    monkeypatch.setenv("BRAIN_VECTOR_STORE", "pgvector")
    monkeypatch.setenv("BRAIN_DATABASE_URL", "postgresql://u:p@h:5432/brain")
    monkeypatch.setitem(sys.modules, "lib.pgstore", None)  # forces ImportError
    with pytest.raises(RuntimeError, match="pgvector backend not available"):
        get_store("/tmp/x.db")


def test_get_store_pgvector_memoizes_pool_per_dsn(monkeypatch):
    import sys
    import types

    created = []

    class _StubPg:
        def __init__(self, dsn):
            created.append(dsn)

    stub = types.ModuleType("lib.pgstore")
    stub.PgVectorStore = _StubPg
    monkeypatch.setenv("BRAIN_VECTOR_STORE", "pgvector")
    monkeypatch.setenv("BRAIN_DATABASE_URL", "postgresql://u:p@h:5432/brain")
    monkeypatch.setitem(sys.modules, "lib.pgstore", stub)
    monkeypatch.setattr("lib.vectorstore._pg_stores", {}, raising=True)

    a = get_store("/tmp/x.db")
    b = get_store("/tmp/y.db")
    assert a is b
    assert created == ["postgresql://u:p@h:5432/brain"]
