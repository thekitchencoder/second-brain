"""Per-principal retrieval/audit log — slice 3 of the A pass.

Append-only record of what the archive showed each principal (one row per
note surfaced), what they wrote, and what the admin plane changed. Lives
in the slice-1 Postgres; default-off (BRAIN_RETRIEVAL_LOG unset) costs one
env check per hook. Best-effort + loud: a failed log write warns to
stderr and never fails the request — observational history, not the
Guardian's journal. INSERT-only by design; no UPDATE/DELETE here.
"""
from __future__ import annotations

import os
import sys

_VALID = ("", "off", "postgres")


def enabled() -> bool:
    return os.environ.get("BRAIN_RETRIEVAL_LOG", "") == "postgres"


def check_retrieval_log_config() -> None:
    """Fail loud at server startup on misconfiguration (never mid-request)."""
    flag = os.environ.get("BRAIN_RETRIEVAL_LOG", "")
    if flag not in _VALID:
        raise RuntimeError(
            f"Unknown BRAIN_RETRIEVAL_LOG: {flag!r} (expected 'off' or 'postgres')")
    if flag == "postgres" and not os.environ.get("BRAIN_DATABASE_URL", ""):
        raise RuntimeError(
            "BRAIN_RETRIEVAL_LOG=postgres requires BRAIN_DATABASE_URL")


_logs: dict = {}   # DSN -> PgRetrievalLog; one pool per process


def get_retrieval_log(dsn: str) -> "PgRetrievalLog":
    """Memoized per-DSN accessor — repeated calls share one pool."""
    if dsn not in _logs:
        _logs[dsn] = PgRetrievalLog(dsn)
    return _logs[dsn]


# ── safe hooks (the only thing call sites touch) ─────────────────────


def _pid(principal) -> str | None:
    if principal is None:
        return None
    return getattr(principal, "id", None) or (
        principal if isinstance(principal, str) else None)


def _warn(e: Exception) -> None:
    print(f"Warning: retrieval log write failed ({e}) — continuing",
          file=sys.stderr)


def safe_log_reads(principal, tool, subject, filepaths) -> None:
    if not enabled():
        return
    pid = _pid(principal)
    if not pid or not filepaths:
        return
    try:
        get_retrieval_log(os.environ["BRAIN_DATABASE_URL"]).log_reads(
            pid, tool, subject, list(filepaths))
    except Exception as e:                      # noqa: BLE001 — best-effort by design
        _warn(e)


def safe_log_write(principal, tool, filepath, subject=None) -> None:
    if not enabled():
        return
    pid = _pid(principal)
    if not pid or not filepath:
        return
    try:
        get_retrieval_log(os.environ["BRAIN_DATABASE_URL"]).log_write(
            pid, tool, filepath, subject=subject)
    except Exception as e:                      # noqa: BLE001
        _warn(e)


def safe_log_admin(principal, tool, subject) -> None:
    if not enabled():
        return
    pid = _pid(principal)
    if not pid:
        return
    try:
        get_retrieval_log(os.environ["BRAIN_DATABASE_URL"]).log_admin(
            pid, tool, subject)
    except Exception as e:                      # noqa: BLE001
        _warn(e)


# ── the store ────────────────────────────────────────────────────────


class PgRetrievalLog:
    def __init__(self, dsn: str):
        try:
            from psycopg_pool import ConnectionPool
        except ImportError as e:
            raise RuntimeError(
                "BRAIN_RETRIEVAL_LOG=postgres requires psycopg — use the "
                "kitchencoder/second-brain:full image (or pip install "
                "'psycopg[binary,pool]')."
            ) from e
        self._pool = ConnectionPool(dsn, min_size=1, max_size=2, open=True)
        self._initialized = False

    def close(self) -> None:
        self._pool.close()

    def init(self) -> None:
        with self._pool.connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS retrieval_log (
                    id BIGSERIAL PRIMARY KEY,
                    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
                    principal_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    subject TEXT,
                    filepath TEXT,
                    request_id TEXT
                )""")
            conn.execute("""
                CREATE INDEX IF NOT EXISTS retrieval_log_principal_ts
                    ON retrieval_log (principal_id, ts)""")
        self._initialized = True

    def _ensure(self) -> None:
        if not self._initialized:
            self.init()

    def log_reads(self, principal_id, tool, subject, filepaths,
                  request_id=None) -> None:
        self._ensure()
        rows = [(principal_id, "read", tool, subject, fp, request_id)
                for fp in filepaths]
        if not rows:
            return
        with self._pool.connection() as conn:
            conn.cursor().executemany(
                "INSERT INTO retrieval_log "
                "(principal_id, kind, tool, subject, filepath, request_id) "
                "VALUES (%s, %s, %s, %s, %s, %s)", rows)

    def log_write(self, principal_id, tool, filepath, subject=None) -> None:
        self._ensure()
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO retrieval_log "
                "(principal_id, kind, tool, subject, filepath) "
                "VALUES (%s, 'write', %s, %s, %s)",
                (principal_id, tool, subject, filepath))

    def log_admin(self, principal_id, tool, subject) -> None:
        self._ensure()
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO retrieval_log (principal_id, kind, tool, subject) "
                "VALUES (%s, 'admin', %s, %s)",
                (principal_id, tool, subject))

    def query(self, principal=None, kind=None, tool=None, since=None,
              until=None, path=None, limit=100) -> list:
        self._ensure()
        clauses, params = [], []
        if principal:
            clauses.append("principal_id = %s"); params.append(principal)
        if kind:
            clauses.append("kind = %s"); params.append(kind)
        if tool:
            clauses.append("tool = %s"); params.append(tool)
        if since:
            clauses.append("ts >= %s::timestamptz"); params.append(since)
        if until:
            clauses.append("ts < %s::timestamptz"); params.append(until)
        if path:
            clauses.append("filepath LIKE %s"); params.append(f"%{path}%")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        with self._pool.connection() as conn:
            rows = conn.execute(
                f"SELECT ts, principal_id, kind, tool, subject, filepath, "
                f"request_id FROM retrieval_log {where} "
                f"ORDER BY ts DESC, id DESC LIMIT %s", params).fetchall()
        keys = ["ts", "principal_id", "kind", "tool", "subject", "filepath",
                "request_id"]
        return [dict(zip(keys, (str(r[0]), *r[1:]))) for r in rows]
