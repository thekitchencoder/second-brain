import sys
import pytest


def test_module_imports_without_psycopg(monkeypatch):
    monkeypatch.setitem(sys.modules, "psycopg", None)
    import importlib
    import lib.retrieval_log
    importlib.reload(lib.retrieval_log)   # must not raise


def test_constructor_without_psycopg_raises_actionable(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("psycopg"):
            raise ImportError("nope")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    from lib.retrieval_log import PgRetrievalLog
    with pytest.raises(RuntimeError, match=":full"):
        PgRetrievalLog("postgresql://u:p@h/brain")


def test_safe_log_off_touches_nothing(monkeypatch):
    monkeypatch.delenv("BRAIN_RETRIEVAL_LOG", raising=False)
    import lib.retrieval_log as rl
    monkeypatch.setattr(rl, "_logs", {}, raising=True)
    rl.safe_log_reads("owner", "brain_search", "query", ["a.md"])
    rl.safe_log_write("owner", "write", "a.md")
    rl.safe_log_admin("owner", "role_set", "role x")
    assert rl._logs == {}                 # no store ever constructed


def test_safe_log_failure_warns_not_raises(monkeypatch, capsys):
    monkeypatch.setenv("BRAIN_RETRIEVAL_LOG", "postgres")
    monkeypatch.setenv("BRAIN_DATABASE_URL", "postgresql://u:p@h:5432/brain")
    import lib.retrieval_log as rl

    class _Boom:
        def log_reads(self, *a, **k):
            raise ConnectionError("db down")
    monkeypatch.setattr(rl, "get_retrieval_log", lambda dsn: _Boom())
    rl.safe_log_reads("fenn-desk", "brain_search", "q", ["a.md"])   # must not raise
    assert "retrieval log" in capsys.readouterr().err.lower()


def test_safe_log_accepts_principal_object(monkeypatch):
    monkeypatch.setenv("BRAIN_RETRIEVAL_LOG", "postgres")
    monkeypatch.setenv("BRAIN_DATABASE_URL", "postgresql://u:p@h:5432/brain")
    import lib.retrieval_log as rl
    calls = []

    class _Fake:
        def log_reads(self, principal_id, tool, subject, filepaths, request_id=None):
            calls.append(principal_id)
    monkeypatch.setattr(rl, "get_retrieval_log", lambda dsn: _Fake())

    class _P:
        id = "fenn-desk"
    rl.safe_log_reads(_P(), "brain_search", "q", ["a.md"])
    assert calls == ["fenn-desk"]


def test_safe_log_reads_empty_filepaths_noop(monkeypatch):
    monkeypatch.setenv("BRAIN_RETRIEVAL_LOG", "postgres")
    monkeypatch.setenv("BRAIN_DATABASE_URL", "postgresql://u:p@h:5432/brain")
    import lib.retrieval_log as rl
    monkeypatch.setattr(rl, "get_retrieval_log",
                        lambda dsn: (_ for _ in ()).throw(AssertionError("must not resolve")))
    rl.safe_log_reads("owner", "brain_search", "q", [])   # no store touch


def test_check_config_fail_loud(monkeypatch):
    import lib.retrieval_log as rl
    monkeypatch.setenv("BRAIN_RETRIEVAL_LOG", "postgres")
    monkeypatch.delenv("BRAIN_DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="BRAIN_DATABASE_URL"):
        rl.check_retrieval_log_config()
    monkeypatch.setenv("BRAIN_RETRIEVAL_LOG", "syslog")
    with pytest.raises(RuntimeError, match="syslog"):
        rl.check_retrieval_log_config()
    monkeypatch.setenv("BRAIN_RETRIEVAL_LOG", "off")
    rl.check_retrieval_log_config()       # fine
    monkeypatch.delenv("BRAIN_RETRIEVAL_LOG", raising=False)
    rl.check_retrieval_log_config()       # fine


@pytest.fixture(scope="session")
def pg_dsn():
    tc = pytest.importorskip("testcontainers.postgres")
    with tc.PostgresContainer("pgvector/pgvector:pg17") as pg:
        # psycopg DSN (testcontainers returns a SQLAlchemy-style URL)
        yield pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")


@pytest.mark.integration
class TestPgRetrievalLogLive:
    @pytest.fixture
    def log(self, pg_dsn):
        from lib.retrieval_log import PgRetrievalLog
        lg = PgRetrievalLog(pg_dsn)
        with lg._pool.connection() as conn:
            conn.execute("DROP TABLE IF EXISTS retrieval_log")
        lg.init()
        yield lg
        lg.close()

    def test_log_reads_one_row_per_note_and_query_filters(self, log):
        log.log_reads("fenn-desk", "brain_search", "the vaults", ["a.md", "b.md"],
                      request_id="r1")
        log.log_reads("oz-desk", "brain_read", "c.md", ["c.md"])
        log.log_write("fenn-desk", "edit", "a.md", subject="find_replace")
        log.log_admin("maker", "role_set", "set role maker (abc1234)")

        assert len(log.query()) == 5
        fenn = log.query(principal="fenn-desk")
        assert len(fenn) == 3
        assert {r["kind"] for r in fenn} == {"read", "write"}
        assert len(log.query(kind="admin")) == 1
        assert len(log.query(tool="brain_search")) == 2
        assert len(log.query(path="a.md")) == 2           # substring match: the read row + the write row for a.md
        assert log.query(limit=2) and len(log.query(limit=2)) == 2
        r = log.query(principal="fenn-desk", kind="read")[0]
        assert set(r) >= {"ts", "principal_id", "kind", "tool", "subject",
                          "filepath", "request_id"}

    def test_query_since_until(self, log):
        log.log_reads("p", "brain_search", "q", ["a.md"])
        assert len(log.query(since="2000-01-01")) == 1
        assert log.query(until="2000-01-01") == []
