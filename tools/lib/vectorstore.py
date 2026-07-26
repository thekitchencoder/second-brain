"""Vector-store port — the seam between the engine and the embedding store.

SqliteVecStore is the embedded backend used by the single-image tiers. The
RBAC/full-stack tier swaps in a server-backed store (Qdrant/pgvector) behind
this same interface, without touching enforcement or handler code.
"""
from __future__ import annotations

from typing import Protocol

from lib.db import (
    search_chunks as _db_search,
    search_chunks_in_layers as _db_search_layers,   # added in Task 5
    get_chunk_embeddings as _db_get_embeddings,
    upsert_chunk as _db_upsert,
    delete_file_chunks as _db_delete,
)


class VectorStore(Protocol):
    def search(self, query_embedding, k: int, allowed_layers=None) -> list: ...
    def get_chunk_embeddings(self, filepath: str) -> list: ...
    def upsert_chunk(self, **kwargs) -> None: ...
    def delete_file_chunks(self, filepath: str) -> None: ...


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


def get_store(db_path: str) -> SqliteVecStore:
    return SqliteVecStore(db_path)
