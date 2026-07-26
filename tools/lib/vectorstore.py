"""Vector-store port — the seam between the engine and the embedding store.

SqliteVecStore is the embedded backend used by the single-image tiers. The
RBAC/full-stack tier swaps in a server-backed store (Qdrant/pgvector) behind
this same interface, without touching enforcement or handler code.
"""
from __future__ import annotations

import os
from typing import Protocol

from lib.db import (
    search_chunks as _db_search,
    search_chunks_in_layers as _db_search_layers,   # added in Task 5
    get_chunk_embeddings as _db_get_embeddings,
    upsert_chunk as _db_upsert,
    delete_file_chunks as _db_delete,
    init_db as _db_init,
    get_stored_dim as _db_stored_dim,
    get_file_hashes as _db_file_hashes,
    prune_file_chunks as _db_prune,
    list_filepaths as _db_list_paths,
)


_pg_stores: dict = {}   # DSN -> PgVectorStore; one pool per process


class VectorStore(Protocol):
    def init(self, embedding_dim: int, model: str = "") -> None: ...
    def stored_dim(self) -> int | None: ...
    def search(self, query_embedding, k: int, allowed_layers=None) -> list: ...
    def get_chunk_embeddings(self, filepath: str) -> list: ...
    def upsert_chunk(self, **kwargs) -> None: ...
    def delete_file_chunks(self, filepath: str) -> None: ...
    def get_file_hashes(self, filepath: str) -> dict: ...
    def prune_file_chunks(self, filepath: str, keep_below: int) -> None: ...
    def list_filepaths(self) -> list: ...


class SqliteVecStore:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def search(self, query_embedding, k: int, allowed_layers=None) -> list:
        # None = unconstrained (owner / non-RBAC). A tuple containing "*" =
        # unconstrained. An EMPTY tuple () = explicit deny-all → return nothing.
        # Never let () fall through to an unfiltered search (a forgotten fine-pass
        # downstream would then be a full leak).
        if allowed_layers is None or "*" in allowed_layers:
            return _db_search(self.db_path, query_embedding, limit=k)
        if not allowed_layers:
            return []
        return _db_search_layers(self.db_path, query_embedding, k=k,
                                 allowed_layers=list(allowed_layers))

    def get_chunk_embeddings(self, filepath: str) -> list:
        return _db_get_embeddings(self.db_path, filepath)

    def upsert_chunk(self, **kwargs) -> None:
        _db_upsert(self.db_path, **kwargs)

    def delete_file_chunks(self, filepath: str) -> None:
        _db_delete(self.db_path, filepath)

    def init(self, embedding_dim: int, model: str = "") -> None:
        _db_init(self.db_path, embedding_dim, model=model)

    def stored_dim(self) -> int | None:
        return _db_stored_dim(self.db_path)

    def get_file_hashes(self, filepath: str) -> dict:
        return _db_file_hashes(self.db_path, filepath)

    def prune_file_chunks(self, filepath: str, keep_below: int) -> None:
        _db_prune(self.db_path, filepath, keep_below)

    def list_filepaths(self) -> list:
        return _db_list_paths(self.db_path)


def get_store(db_path: str) -> "VectorStore":
    """Single construction point for the index store.

    db_path is where the embedded sqlite backend lives; the pgvector
    backend ignores it and connects to BRAIN_DATABASE_URL. Selection is
    env-driven so every call site (which passes a db path) picks up the
    configured backend without threading Config through the handlers.
    Fails loud on misconfiguration — never silently falls back to sqlite.
    """
    backend = os.environ.get("BRAIN_VECTOR_STORE", "sqlite")
    if backend == "sqlite":
        return SqliteVecStore(db_path)
    if backend == "pgvector":
        dsn = os.environ.get("BRAIN_DATABASE_URL", "")
        if not dsn:
            raise RuntimeError(
                "BRAIN_VECTOR_STORE=pgvector requires BRAIN_DATABASE_URL "
                "(e.g. postgresql://brain:secret@postgres:5432/brain)"
            )
        try:
            from lib.pgstore import PgVectorStore
        except ImportError as e:
            raise RuntimeError(
                "pgvector backend not available: lib.pgstore could not be "
                "imported (broken or incomplete install?)"
            ) from e
        if dsn not in _pg_stores:
            _pg_stores[dsn] = PgVectorStore(dsn)
        return _pg_stores[dsn]
    raise RuntimeError(
        f"Unknown BRAIN_VECTOR_STORE: {backend!r} (expected 'sqlite' or 'pgvector')"
    )
