"""Agent-token credentials — the ONLY policy-adjacent state in Postgres.

Grants (who maps to which role) live in the profile repo; this table
holds only bearer-secret hashes and revocation state, because secrets
must never live in git and revocation must not wait for a pull.
"""
from __future__ import annotations

import hashlib
import secrets


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


_stores: dict = {}   # DSN -> PgCredentialStore; one pool per process


def get_credential_store(dsn: str) -> "PgCredentialStore":
    """Memoized per-DSN accessor — repeated calls share one pool."""
    if dsn not in _stores:
        _stores[dsn] = PgCredentialStore(dsn)
    return _stores[dsn]


class PgCredentialStore:
    def __init__(self, dsn: str):
        try:
            from psycopg_pool import ConnectionPool
        except ImportError as e:
            raise RuntimeError(
                "BRAIN_POLICY_CREDENTIALS=postgres requires psycopg — use the "
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
                CREATE TABLE IF NOT EXISTS agent_tokens (
                    principal_id TEXT NOT NULL,
                    token_hash   TEXT NOT NULL UNIQUE,
                    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
                    revoked_at   TIMESTAMPTZ
                )""")
        self._initialized = True

    def _ensure(self) -> None:
        if not self._initialized:
            self.init()

    def mint(self, principal_id: str) -> str:
        """Create a token for a principal; returns the plaintext EXACTLY once."""
        self._ensure()
        token = secrets.token_urlsafe(32)
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO agent_tokens (principal_id, token_hash) VALUES (%s, %s)",
                (principal_id, _hash_token(token)))
        return token

    def verify(self, token: str) -> str | None:
        # Plain SQL equality (not compare_digest) is fine here: this is an
        # exact index probe on the hash of random 256-bit material, not a
        # secret-vs-secret comparison — timing reveals nothing recoverable.
        self._ensure()
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT principal_id FROM agent_tokens "
                "WHERE token_hash = %s AND revoked_at IS NULL",
                (_hash_token(token),)).fetchone()
        return row[0] if row else None

    def revoke(self, principal_id: str) -> int:
        self._ensure()
        with self._pool.connection() as conn:
            cur = conn.execute(
                "UPDATE agent_tokens SET revoked_at = now() "
                "WHERE principal_id = %s AND revoked_at IS NULL",
                (principal_id,))
            return cur.rowcount

    def list_tokens(self) -> list:
        self._ensure()
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT principal_id, created_at, revoked_at FROM agent_tokens "
                "ORDER BY created_at").fetchall()
        return [{"principal_id": r[0], "created_at": str(r[1]),
                 "revoked_at": str(r[2]) if r[2] else None} for r in rows]
