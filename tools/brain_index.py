"""brain-index: index brain notes into sqlite-vec for semantic search.

Usage:
  brain-index run    Full reindex of all markdown files
  brain-index watch  Watch for changes and reindex incrementally
"""
import hashlib
import os
import sys
from pathlib import Path

from lib.clean import chunk_text, clean_content, extract_frontmatter
from lib.config import Config
from lib.embeddings import get_embedding, EmbeddingError
from lib.vectorstore import get_store

_cfg = None


def _get_cfg() -> "Config":
    global _cfg
    if _cfg is None:
        _cfg = Config()
    return _cfg


def index_file(filepath: str, store) -> None:
    with open(filepath, "r", encoding="utf-8") as f:
        raw = f.read()

    meta, content = extract_frontmatter(raw)
    cleaned = clean_content(content)
    chunks = chunk_text(cleaned)

    existing_hashes = store.get_file_hashes(filepath)

    for i, chunk in enumerate(chunks):
        content_hash = hashlib.sha256(chunk.encode()).hexdigest()
        if existing_hashes.get(i) == content_hash:
            continue
        try:
            embedding = get_embedding(chunk)
        except EmbeddingError as e:
            print(f"Warning: skipping chunk {i} of {filepath}: {e}", file=sys.stderr)
            continue
        store.upsert_chunk(
            filepath=filepath,
            chunk_index=i,
            content=chunk,
            content_hash=content_hash,
            embedding=embedding,
            meta=meta,
        )

    # Prune chunks whose index is beyond the current chunk count (file shrank)
    store.prune_file_chunks(filepath, keep_below=len(chunks))


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


def purge_stale_paths(store) -> None:
    """Remove index entries for filepaths that no longer exist on disk."""
    for fp in store.list_filepaths():
        if not os.path.isfile(fp):
            store.delete_file_chunks(fp)
            print(f"Purged stale: {fp}", file=sys.stderr)


def index_brain(brain_path: str, store) -> None:
    dim = detect_embedding_dim()
    try:
        store.init(embedding_dim=dim, model=_get_cfg().embedding_model)
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
            index_file(filepath, store)
    purge_stale_paths(store)


def watch_brain(brain_path: str, store) -> None:
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
                        index_file(path, store)
                    else:
                        print(f"Purging deleted/renamed: {path}", file=sys.stderr)
                        purge_stale_paths(store)
                except Exception as e:
                    print(f"Error indexing {path}: {e}", file=sys.stderr)


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    brain_path = _get_cfg().brain_path
    db_path = _get_cfg().db_path

    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    store = get_store(db_path)

    if cmd == "run":
        index_brain(brain_path, store)
        print("Indexing complete.", file=sys.stderr)
    elif cmd == "watch":
        index_brain(brain_path, store)
        watch_brain(brain_path, store)
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)
