"""brain-index: index brain notes into sqlite-vec for semantic search.

Usage:
  brain-index run    Full reindex of all markdown files
  brain-index watch  Watch for changes and reindex incrementally
"""
import hashlib
import os
import sqlite3
import sys
from pathlib import Path

from lib.clean import chunk_text, clean_content, extract_frontmatter
from lib.config import Config
from lib.db import init_db, upsert_chunk
from lib.embeddings import get_embedding, EmbeddingError

_cfg = None


def _get_cfg() -> "Config":
    global _cfg
    if _cfg is None:
        _cfg = Config()
    return _cfg


def index_file(filepath: str, db_path: str) -> None:
    with open(filepath, "r", encoding="utf-8") as f:
        raw = f.read()

    meta, content = extract_frontmatter(raw)
    cleaned = clean_content(content)
    chunks = chunk_text(cleaned)

    # Read existing hashes upfront, then close connection
    conn = sqlite3.connect(db_path)
    try:
        existing_hashes = {
            row[0]: row[1]
            for row in conn.execute(
                "SELECT chunk_index, content_hash FROM chunks WHERE filepath=?",
                (filepath,)
            ).fetchall()
        }
    finally:
        conn.close()

    for i, chunk in enumerate(chunks):
        content_hash = hashlib.sha256(chunk.encode()).hexdigest()
        if existing_hashes.get(i) == content_hash:
            continue
        try:
            embedding = get_embedding(chunk)
        except EmbeddingError as e:
            print(f"Warning: skipping chunk {i} of {filepath}: {e}", file=sys.stderr)
            continue
        upsert_chunk(
            db_path=db_path,
            filepath=filepath,
            chunk_index=i,
            content=chunk,
            content_hash=content_hash,
            embedding=embedding,
            meta=meta,
        )

    # Prune chunks whose index is beyond the current chunk count (file shrank)
    from lib.db import _connect as _vec_connect
    vec_conn = _vec_connect(db_path)
    try:
        stale_ids = [
            row[0] for row in vec_conn.execute(
                "SELECT id FROM chunks WHERE filepath=? AND chunk_index >= ?",
                (filepath, len(chunks))
            ).fetchall()
        ]
        if stale_ids:
            placeholders = ",".join("?" * len(stale_ids))
            vec_conn.execute(f"DELETE FROM embeddings WHERE rowid IN ({placeholders})", stale_ids)
            vec_conn.execute(f"DELETE FROM chunks WHERE id IN ({placeholders})", stale_ids)
            vec_conn.commit()
    finally:
        vec_conn.close()


def detect_embedding_dim() -> int:
    """Call the embedding API once to get the actual output dimension."""
    print(f"Detecting embedding dimension for {_get_cfg().embedding_model}...", file=sys.stderr)
    try:
        vec = get_embedding("dimension probe")
    except EmbeddingError as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)
    dim = len(vec)
    print(f"  → {dim} dimensions", file=sys.stderr)
    return dim


def purge_stale_paths(db_path: str) -> None:
    """Remove DB entries for filepaths that no longer exist on disk."""
    from lib.db import _connect as _vec_connect
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT DISTINCT filepath FROM chunks").fetchall()
        stale = [fp for (fp,) in rows if not os.path.isfile(fp)]
    finally:
        conn.close()
    for fp in stale:
        vec_conn = _vec_connect(db_path)
        try:
            stale_ids = [
                row[0] for row in vec_conn.execute(
                    "SELECT id FROM chunks WHERE filepath=?", (fp,)
                ).fetchall()
            ]
            if stale_ids:
                placeholders = ",".join("?" * len(stale_ids))
                vec_conn.execute(f"DELETE FROM embeddings WHERE rowid IN ({placeholders})", stale_ids)
            vec_conn.execute("DELETE FROM chunks WHERE filepath=?", (fp,))
            vec_conn.commit()
            print(f"Purged stale: {fp}", file=sys.stderr)
        finally:
            vec_conn.close()


def index_brain(brain_path: str, db_path: str) -> None:
    dim = detect_embedding_dim()
    try:
        init_db(db_path, embedding_dim=dim, model=_get_cfg().embedding_model)
    except ValueError as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)
    for root, dirs, files in os.walk(brain_path):
        # Skip hidden directories (.obsidian, .zk, .ai, .git, .trash) and templates
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "templates"]
        for fname in files:
            if not fname.endswith(".md"):
                continue
            filepath = os.path.join(root, fname)
            print(f"Indexing {filepath}", file=sys.stderr)
            index_file(filepath, db_path)
    purge_stale_paths(db_path)


def watch_brain(brain_path: str, db_path: str) -> None:
    from watchfiles import watch
    print(f"Watching {brain_path} for changes...", file=sys.stderr)
    # force_polling=True is required when /brain is a Docker volume mount from macOS.
    # inotify events don't propagate through the volume into the container, so
    # without polling the watcher runs but never fires.
    for changes in watch(brain_path, force_polling=True):
        for change_type, path in changes:
            if path.endswith(".md") and ".ai" not in Path(path).parts and "templates" not in Path(path).parts and ".trash" not in Path(path).parts:
                try:
                    if os.path.isfile(path):
                        print(f"Reindexing {path}", file=sys.stderr)
                        index_file(path, db_path)
                    else:
                        print(f"Purging deleted/renamed: {path}", file=sys.stderr)
                        purge_stale_paths(db_path)
                except Exception as e:
                    print(f"Error indexing {path}: {e}", file=sys.stderr)


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    brain_path = _get_cfg().brain_path
    db_path = _get_cfg().db_path

    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    if cmd == "run":
        index_brain(brain_path, db_path)
        print("Indexing complete.", file=sys.stderr)
    elif cmd == "watch":
        index_brain(brain_path, db_path)
        watch_brain(brain_path, db_path)
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)
