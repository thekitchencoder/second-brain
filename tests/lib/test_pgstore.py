import builtins
import sys
import pytest


def test_module_imports_without_psycopg(monkeypatch):
    # Simulate psycopg absent: importing the module must succeed.
    monkeypatch.setitem(sys.modules, "psycopg", None)
    import importlib
    import lib.pgstore
    importlib.reload(lib.pgstore)  # must not raise


def test_constructor_without_psycopg_raises_actionable(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("psycopg"):
            raise ImportError("No module named 'psycopg'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    from lib.pgstore import PgVectorStore
    with pytest.raises(RuntimeError, match=":full"):
        PgVectorStore("postgresql://u:p@h/brain")


def test_vector_literal_format():
    from lib.pgstore import _vec_literal
    assert _vec_literal([0.5, -1.0, 2.25]) == "[0.5, -1.0, 2.25]"


def test_close_releases_pool():
    from lib.pgstore import PgVectorStore

    class _Pool:
        closed = False
        def close(self):
            self.closed = True

    store = PgVectorStore.__new__(PgVectorStore)
    store._pool = _Pool()
    store.close()
    assert store._pool.closed


def test_search_sql_uses_l2_distance():
    import inspect
    import lib.pgstore
    src = inspect.getsource(lib.pgstore)
    assert "<->" in src and "<=>" not in src


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows
    def fetchall(self):
        return self._rows
    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeConn:
    def __init__(self, log):
        self.log = log
    def execute(self, sql, params=None):
        self.log.append((" ".join(sql.split()), params))
        return _FakeCursor([])
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


class _FakePool:
    def __init__(self):
        self.log = []
    def connection(self):
        return _FakeConn(self.log)


def _store_with_fake_pool():
    from lib.pgstore import PgVectorStore
    store = PgVectorStore.__new__(PgVectorStore)   # skip __init__/psycopg
    store._pool = _FakePool()
    return store


def test_search_empty_layers_is_deny_all_without_touching_db():
    store = _store_with_fake_pool()
    assert store.search([0.1, 0.2], k=5, allowed_layers=()) == []
    assert store._pool.log == []          # deny-all never reaches SQL


def test_search_none_layers_runs_unfiltered_sql():
    store = _store_with_fake_pool()
    store.search([0.1, 0.2], k=5, allowed_layers=None)
    (sql, params), = store._pool.log
    assert "WHERE layer" not in sql


def test_search_wildcard_runs_unfiltered_sql():
    store = _store_with_fake_pool()
    store.search([0.1, 0.2], k=5, allowed_layers=("*",))
    (sql, params), = store._pool.log
    assert "WHERE layer" not in sql


def test_search_layers_filtered_sql_carries_layers():
    store = _store_with_fake_pool()
    store.search([0.1, 0.2], k=5, allowed_layers=("work", "shared"))
    (sql, params), = store._pool.log
    assert "WHERE layer = ANY" in sql
    assert ["work", "shared"] in list(params)
