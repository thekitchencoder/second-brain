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
