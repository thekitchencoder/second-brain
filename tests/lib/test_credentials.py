import sys
import pytest


def test_module_imports_without_psycopg(monkeypatch):
    monkeypatch.setitem(sys.modules, "psycopg", None)
    import importlib
    import lib.credentials
    importlib.reload(lib.credentials)   # must not raise


def test_hash_is_sha256_hex():
    from lib.credentials import _hash_token
    assert _hash_token("abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


def test_constructor_without_psycopg_raises_actionable(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("psycopg"):
            raise ImportError("nope")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    from lib.credentials import PgCredentialStore
    with pytest.raises(RuntimeError, match=":full"):
        PgCredentialStore("postgresql://u:p@h/brain")


def test_get_credential_store_memoizes_pool_per_dsn(monkeypatch):
    import lib.credentials as credentials

    created = []

    class _StubPg:
        def __init__(self, dsn):
            created.append(dsn)

    monkeypatch.setattr(credentials, "PgCredentialStore", _StubPg)
    monkeypatch.setattr(credentials, "_stores", {}, raising=True)

    a = credentials.get_credential_store("postgresql://u:p@h:5432/brain")
    b = credentials.get_credential_store("postgresql://u:p@h:5432/brain")
    assert a is b
    assert created == ["postgresql://u:p@h:5432/brain"]


@pytest.fixture(scope="session")
def pg_dsn():
    tc = pytest.importorskip("testcontainers.postgres")
    with tc.PostgresContainer("pgvector/pgvector:pg17") as pg:
        # psycopg DSN (testcontainers returns a SQLAlchemy-style URL)
        yield pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")


@pytest.mark.integration
class TestPgCredentialStoreLive:
    @pytest.fixture
    def store(self, pg_dsn):
        from lib.credentials import PgCredentialStore
        s = PgCredentialStore(pg_dsn)
        with s._pool.connection() as conn:
            conn.execute("DROP TABLE IF EXISTS agent_tokens")
        s.init()
        yield s
        s.close()

    def test_mint_verify_roundtrip(self, store):
        tok = store.mint("fenn-desk")
        assert len(tok) >= 32
        assert store.verify(tok) == "fenn-desk"

    def test_verify_wrong_token_none(self, store):
        store.mint("fenn-desk")
        assert store.verify("not-a-token") is None

    def test_revoke_kills_all_principal_tokens(self, store):
        t1, t2 = store.mint("fenn-desk"), store.mint("fenn-desk")
        assert store.revoke("fenn-desk") == 2
        assert store.verify(t1) is None and store.verify(t2) is None

    def test_list_never_exposes_hashes(self, store):
        store.mint("fenn-desk")
        rows = store.list_tokens()
        assert rows and all("hash" not in k for r in rows for k in r)
