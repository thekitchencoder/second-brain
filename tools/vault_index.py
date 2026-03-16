"""vault-index: index vault notes into sqlite-vec for semantic search.

Usage:
  vault-index run    Full reindex of all markdown files
  vault-index watch  Watch for changes and reindex incrementally
"""
import hashlib
import os
import sqlite3
import sys
from pathlib import Path

from openai import OpenAI, NotFoundError, APIConnectionError, InternalServerError

from lib.clean import chunk_text, clean_content, extract_frontmatter
from lib.config import Config
from lib.db import init_db, upsert_chunk

_cfg = Config()
_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            base_url=_cfg.embedding_base_url,
            api_key=os.environ.get("OPENAI_API_KEY", "local")
        )
    return _client


def get_embedding(text: str, max_chars: int = 1500) -> list[float]:
    """Get embedding, halving input on token-limit errors until it fits."""
    try:
        response = _get_client().embeddings.create(
            input=text[:max_chars],
            model=_cfg.embedding_model,
        )
        return response.data[0].embedding
    except InternalServerError as e:
        if "too large" in str(e) and max_chars > 100:
            return get_embedding(text, max_chars // 2)
        raise
    except NotFoundError:
        print(f"\nError: embedding model '{_cfg.embedding_model}' not found.", file=sys.stderr)
        print(f"  Endpoint: {_cfg.embedding_base_url}", file=sys.stderr)
        print(f"  Check that the model is loaded and EMBEDDING_MODEL is set correctly.", file=sys.stderr)
        sys.exit(1)
    except APIConnectionError:
        print(f"\nError: cannot connect to embedding endpoint.", file=sys.stderr)
        print(f"  Endpoint: {_cfg.embedding_base_url}", file=sys.stderr)
        print(f"  Is Docker Model Runner (or your configured LLM server) running?", file=sys.stderr)
        sys.exit(1)


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
        embedding = get_embedding(chunk)
        upsert_chunk(
            db_path=db_path,
            filepath=filepath,
            chunk_index=i,
            content=chunk,
            content_hash=content_hash,
            embedding=embedding,
            meta=meta,
        )


def detect_embedding_dim() -> int:
    """Call the embedding API once to get the actual output dimension."""
    print(f"Detecting embedding dimension for {_cfg.embedding_model}...", file=sys.stderr)
    vec = get_embedding("dimension probe")
    dim = len(vec)
    print(f"  → {dim} dimensions", file=sys.stderr)
    return dim


def index_vault(vault_path: str, db_path: str) -> None:
    dim = detect_embedding_dim()
    try:
        init_db(db_path, embedding_dim=dim, model=_cfg.embedding_model)
    except ValueError as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)
    for root, dirs, files in os.walk(vault_path):
        # Skip hidden directories (.obsidian, .zk, .ai, .git)
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fname in files:
            if not fname.endswith(".md"):
                continue
            filepath = os.path.join(root, fname)
            print(f"Indexing {filepath}", file=sys.stderr)
            index_file(filepath, db_path)


def watch_vault(vault_path: str, db_path: str) -> None:
    from watchfiles import watch
    print(f"Watching {vault_path} for changes...", file=sys.stderr)
    for changes in watch(vault_path):
        for change_type, path in changes:
            if path.endswith(".md") and ".ai" not in Path(path).parts:
                print(f"Reindexing {path}", file=sys.stderr)
                index_file(path, db_path)


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    vault_path = _cfg.vault_path
    db_path = _cfg.db_path

    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    if cmd == "run":
        index_vault(vault_path, db_path)
        print("Indexing complete.", file=sys.stderr)
    elif cmd == "watch":
        index_vault(vault_path, db_path)
        watch_vault(vault_path, db_path)
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)
