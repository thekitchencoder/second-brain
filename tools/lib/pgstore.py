"""PostgreSQL + pgvector index store — the full-stack tier backend.

Selected via BRAIN_VECTOR_STORE=pgvector + BRAIN_DATABASE_URL. Requires
psycopg (shipped in the :full image); the import is lazy so this module
loads everywhere and only *constructing* the store needs the driver.

Search is an exact scan (ORDER BY embedding <-> query LIMIT k): at brain
scale that is milliseconds with perfect filtered recall, so the layer
predicate is a plain WHERE — no paginate-to-fill needed on this backend.
When a deployment outgrows exact scans, add an HNSW index:
    CREATE INDEX ON chunks USING hnsw (embedding vector_l2_ops);
(and rely on pgvector >= 0.8 iterative scans for filtered recall).
"""
from __future__ import annotations

import json

_RESULT_COLS = ("filepath, chunk_index, content, title, type, status, "
                "created, tags, scope, layer")


def _vec_literal(embedding) -> str:
    """pgvector text format for a float list — json.dumps emits exactly it."""
    return json.dumps([float(x) for x in embedding])


def _row_to_dict(row, with_distance: bool) -> dict:
    keys = ["filepath", "chunk_index", "content", "title", "type",
            "status", "created", "tags", "scope", "layer"]
    if with_distance:
        keys.append("distance")
    r = dict(zip(keys, row))
    r["tags"] = json.loads(r["tags"] or "[]")
    return r


class PgVectorStore:
    def __init__(self, dsn: str):
        try:
            from psycopg_pool import ConnectionPool
        except ImportError as e:
            raise RuntimeError(
                "BRAIN_VECTOR_STORE=pgvector requires psycopg — use the "
                "kitchencoder/second-brain:full image (or pip install "
                "'psycopg[binary,pool]')."
            ) from e
        self._pool = ConnectionPool(dsn, min_size=1, max_size=4, open=True)

    def close(self) -> None:
        """Release the connection pool (tests / graceful shutdown)."""
        self._pool.close()

    # ── lifecycle ────────────────────────────────────────────────────

    def stored_dim(self) -> int | None:
        with self._pool.connection() as conn:
            exists = conn.execute(
                "SELECT 1 FROM information_schema.tables WHERE table_name = 'meta'"
            ).fetchone()
            if not exists:
                return None
            row = conn.execute(
                "SELECT value FROM meta WHERE key = 'embedding_dim'"
            ).fetchone()
            return int(row[0]) if row else None

    def init(self, embedding_dim: int, model: str = "") -> None:
        if isinstance(embedding_dim, bool) or not isinstance(embedding_dim, int) \
                or embedding_dim <= 0:
            raise ValueError(
                f"embedding_dim must be a positive integer, got {embedding_dim!r}")
        stored = self.stored_dim()
        if stored is not None and stored != embedding_dim:
            raise ValueError(
                f"Dimension mismatch: existing index uses {stored}-dim embeddings "
                f"but current model produces {embedding_dim}-dim embeddings.\n"
                f"To switch models, drop the index tables and reindex:\n"
                f"  psql $BRAIN_DATABASE_URL -c 'DROP TABLE chunks, meta;'\n"
                f"  brain-index run")
        with self._pool.connection() as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS chunks (
                    id BIGSERIAL PRIMARY KEY,
                    filepath TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    title TEXT, type TEXT, status TEXT, created TEXT,
                    tags TEXT, scope TEXT, layer TEXT,
                    embedding vector({embedding_dim}) NOT NULL,
                    UNIQUE (filepath, chunk_index)
                )""")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
            conn.execute(
                "INSERT INTO meta VALUES ('embedding_dim', %s) "
                "ON CONFLICT (key) DO NOTHING", (str(embedding_dim),))
            if model:
                conn.execute(
                    "INSERT INTO meta VALUES ('embedding_model', %s) "
                    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                    (model,))

    # ── write path ───────────────────────────────────────────────────

    def upsert_chunk(self, *, filepath, chunk_index, content, content_hash,
                     embedding, meta) -> None:
        tags_json = json.dumps(meta.get("tags") or [])
        with self._pool.connection() as conn:
            conn.execute("""
                INSERT INTO chunks (filepath, chunk_index, content, content_hash,
                                    title, type, status, created, tags, scope,
                                    layer, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
                ON CONFLICT (filepath, chunk_index) DO UPDATE SET
                    content = EXCLUDED.content,
                    content_hash = EXCLUDED.content_hash,
                    title = EXCLUDED.title,
                    type = EXCLUDED.type,
                    status = EXCLUDED.status,
                    created = EXCLUDED.created,
                    tags = EXCLUDED.tags,
                    scope = EXCLUDED.scope,
                    layer = EXCLUDED.layer,
                    embedding = EXCLUDED.embedding
            """, (filepath, chunk_index, content, content_hash,
                  meta.get("title"), meta.get("type"), meta.get("status"),
                  meta.get("created"), tags_json, meta.get("scope"),
                  meta.get("layer"), _vec_literal(embedding)))

    def delete_file_chunks(self, filepath: str) -> None:
        with self._pool.connection() as conn:
            conn.execute("DELETE FROM chunks WHERE filepath = %s", (filepath,))

    def prune_file_chunks(self, filepath: str, keep_below: int) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "DELETE FROM chunks WHERE filepath = %s AND chunk_index >= %s",
                (filepath, keep_below))

    # ── read path ────────────────────────────────────────────────────

    def get_file_hashes(self, filepath: str) -> dict:
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT chunk_index, content_hash FROM chunks WHERE filepath = %s",
                (filepath,)).fetchall()
        return {r[0]: r[1] for r in rows}

    def list_filepaths(self) -> list:
        with self._pool.connection() as conn:
            rows = conn.execute("SELECT DISTINCT filepath FROM chunks").fetchall()
        return [r[0] for r in rows]

    def get_chunk_embeddings(self, filepath: str) -> list:
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT embedding::text FROM chunks WHERE filepath = %s "
                "ORDER BY chunk_index", (filepath,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def search(self, query_embedding, k: int, allowed_layers=None) -> list:
        # Same semantics as SqliteVecStore.search (Plan E invariant):
        # None or "*" ∈ layers = unconstrained; empty = deny-all → [].
        if allowed_layers is None or "*" in allowed_layers:
            vec = _vec_literal(query_embedding)
            with self._pool.connection() as conn:
                # L2 distance, not cosine: matches the embedded sqlite-vec
                # backend's default metric so top-k ordering stays consistent
                # across backends for identical data.
                rows = conn.execute(f"""
                    SELECT {_RESULT_COLS}, embedding <-> %s::vector AS distance
                    FROM chunks
                    ORDER BY distance
                    LIMIT %s
                """, (vec, k)).fetchall()
            return [_row_to_dict(r, with_distance=True) for r in rows]
        if not allowed_layers:
            return []
        vec = _vec_literal(query_embedding)
        with self._pool.connection() as conn:
            rows = conn.execute(f"""
                SELECT {_RESULT_COLS}, embedding <-> %s::vector AS distance
                FROM chunks
                WHERE layer = ANY(%s)
                ORDER BY distance
                LIMIT %s
            """, (vec, list(allowed_layers), k)).fetchall()
        return [_row_to_dict(r, with_distance=True) for r in rows]
