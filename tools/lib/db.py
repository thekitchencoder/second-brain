import json
import sqlite3
import struct
import sqlite_vec


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str, embedding_dim: int) -> None:
    """Create tables if they don't exist. Idempotent."""
    conn = _connect(db_path)
    try:
        conn.executescript(f"""
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY,
                filepath TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                title TEXT,
                type TEXT,
                status TEXT,
                created TEXT,
                tags TEXT,
                scope TEXT,
                UNIQUE(filepath, chunk_index)
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS embeddings USING vec0(
                embedding float[{embedding_dim}]
            );
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            INSERT OR IGNORE INTO meta VALUES ('embedding_dim', '{embedding_dim}');
        """)
        conn.commit()
    finally:
        conn.close()


def upsert_chunk(
    db_path: str,
    filepath: str,
    chunk_index: int,
    content: str,
    content_hash: str,
    embedding: list[float],
    meta: dict,
) -> None:
    conn = _connect(db_path)
    try:
        tags_json = json.dumps(meta.get("tags") or [])
        conn.execute("BEGIN")
        conn.execute("""
            INSERT INTO chunks (filepath, chunk_index, content, content_hash, title, type, status, created, tags, scope)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(filepath, chunk_index) DO UPDATE SET
                content=excluded.content,
                content_hash=excluded.content_hash,
                title=excluded.title,
                type=excluded.type,
                status=excluded.status,
                created=excluded.created,
                tags=excluded.tags,
                scope=excluded.scope
        """, (filepath, chunk_index, content, content_hash, meta.get("title"),
              meta.get("type"), meta.get("status"), meta.get("created"),
              tags_json, meta.get("scope")))
        chunk_id = conn.execute(
            "SELECT id FROM chunks WHERE filepath=? AND chunk_index=?",
            (filepath, chunk_index)
        ).fetchone()[0]
        conn.execute("DELETE FROM embeddings WHERE rowid=?", (chunk_id,))
        conn.execute(
            "INSERT INTO embeddings(rowid, embedding) VALUES (?, ?)",
            (chunk_id, sqlite_vec.serialize_float32(embedding))
        )
        conn.commit()
    finally:
        conn.close()


def search_chunks(db_path: str, query_embedding: list[float], limit: int = 5) -> list[dict]:
    conn = _connect(db_path)
    try:
        rows = conn.execute("""
            SELECT c.filepath, c.chunk_index, c.content, c.title, c.type,
                   c.status, c.created, c.tags, c.scope, e.distance
            FROM embeddings e
            JOIN chunks c ON c.id = e.rowid
            WHERE e.embedding MATCH ?
              AND k = ?
            ORDER BY e.distance
        """, (sqlite_vec.serialize_float32(query_embedding), limit)).fetchall()
    finally:
        conn.close()
    results = []
    for row in rows:
        r = dict(row)
        r["tags"] = json.loads(r["tags"] or "[]")
        results.append(r)
    return results


def get_chunk_embeddings(db_path: str, filepath: str) -> list[list[float]]:
    """Return all embedding vectors for a given filepath."""
    conn = _connect(db_path)
    try:
        rows = conn.execute("""
            SELECT e.embedding
            FROM embeddings e
            JOIN chunks c ON c.id = e.rowid
            WHERE c.filepath = ?
        """, (filepath,)).fetchall()
    finally:
        conn.close()
    return [list(struct.unpack(f"{len(row[0]) // 4}f", row[0])) for row in rows]
