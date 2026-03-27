#!/usr/bin/env python3
"""brain-api: FastAPI REST layer for the second-brain.

Sits between the MCP server and the filesystem, reuses the same handler
functions, and adds structured responses + surgical edit support for a
web UI with wiki-link navigation.
"""
import os
from enum import Enum
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from lib.config import Config
from lib.clean import extract_frontmatter
from lib.edit import (
    append_to_section,
    find_replace,
    insert_wikilink,
    prepend_to_section,
    replace_lines,
    replace_section,
    update_frontmatter,
)
from lib.brain import (
    _check_within_brain,
    _list_template_names,
    _relative_path,
    extract_wikilinks,
    find_backlinks,
    handle_brain_create,
    handle_brain_query,
    handle_brain_related,
    handle_brain_search,
    handle_brain_templates,
)

_cfg = Config()

app = FastAPI(
    title="Second Brain API",
    version="0.1.0",
    description="REST API for reading, editing, and navigating a markdown brain.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cfg.cors_origins,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)


# ── Helpers ──────────────────────────────────────────────────────────


def _resolve(filepath: str) -> str:
    """Resolve filepath to absolute, validated path within the brain."""
    bp = _cfg.brain_path
    full = filepath if filepath.startswith("/") else os.path.join(bp, filepath)
    if err := _check_within_brain(full, bp):
        raise HTTPException(status_code=403, detail=err)
    return full


def _read_file(full_path: str) -> str:
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail=f"File not found: {full_path}")
    with open(full_path, "r", encoding="utf-8") as f:
        return f.read()


def _write_file(full_path: str, content: str) -> None:
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)


def _relative(full_path: str) -> str:
    """Return path relative to brain root."""
    return _relative_path(full_path, _cfg.brain_path)


def _parse_note(filepath: str, raw: str) -> dict:
    """Parse a raw markdown file into structured note dict."""
    meta, body = extract_frontmatter(raw)
    return {
        "filepath": filepath,
        "frontmatter": meta,
        "body": body,
        "wikilinks": extract_wikilinks(raw),
    }


def _find_backlinks(filepath: str) -> list[dict]:
    """Walk the brain and find notes that contain a [[wikilink]] to filepath."""
    return find_backlinks(filepath, _cfg.brain_path)


# ── Request / Response models ────────────────────────────────────────


class NoteResponse(BaseModel):
    filepath: str
    frontmatter: dict = Field(default_factory=dict)
    body: str = ""
    wikilinks: list[dict] = Field(default_factory=list)


class SearchResult(BaseModel):
    filepath: str
    title: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = None
    created: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    content_preview: str = ""
    distance: Optional[float] = None


class CreateRequest(BaseModel):
    template: str
    title: str
    directory: Optional[str] = None


class WriteRequest(BaseModel):
    content: str


class EditOp(str, Enum):
    update_frontmatter = "update_frontmatter"
    replace_section = "replace_section"
    append_to_section = "append_to_section"
    prepend_to_section = "prepend_to_section"
    replace_lines = "replace_lines"
    find_replace = "find_replace"
    insert_wikilink = "insert_wikilink"


class EditRequest(BaseModel):
    op: EditOp
    # update_frontmatter
    frontmatter: Optional[dict] = None
    # section operations
    heading: Optional[str] = None
    body: Optional[str] = None
    # replace_lines
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    replacement: Optional[str] = None
    # find_replace
    find: Optional[str] = None
    replace: Optional[str] = None
    regex: bool = False
    count: int = 0  # 0 = all
    # insert_wikilink
    target: Optional[str] = None
    context_heading: Optional[str] = None


class EditResponse(BaseModel):
    filepath: str
    success: bool
    detail: str


class BacklinkEntry(BaseModel):
    filepath: str
    title: str


# ── Endpoints ────────────────────────────────────────────────────────


@app.get("/api/search", response_model=list[SearchResult])
def search_notes(
    q: str = Query(..., description="Semantic search query"),
    limit: int = Query(5, ge=1, le=50),
):
    """Semantic vector search across all brain notes."""
    from lib.db import search_chunks
    from lib.embeddings import get_embedding, EmbeddingError

    try:
        embedding = get_embedding(q)
    except EmbeddingError as e:
        raise HTTPException(503, f"Embedding service unavailable: {e}")
    results = search_chunks(_cfg.db_path, embedding, limit=limit)
    return [
        SearchResult(
            filepath=r["filepath"],
            title=r.get("title"),
            type=r.get("type"),
            status=r.get("status"),
            created=r.get("created"),
            tags=r.get("tags") or [],
            content_preview=r.get("content", "")[:400],
            distance=r.get("distance"),
        )
        for r in results
    ]


@app.get("/api/notes", response_model=list[str])
def list_notes(
    tag: Optional[str] = None,
    status: Optional[str] = None,
    type: Optional[str] = None,
):
    """List notes filtered by metadata (delegates to zk)."""
    result = handle_brain_query(
        tag=tag, status=status, note_type=type, brain_path=_cfg.brain_path
    )
    if result.startswith("No notes") or result.startswith("zk"):
        return []
    return [f.strip() for f in result.splitlines() if f.strip()]


@app.get("/api/notes/{filepath:path}/related", response_model=list[SearchResult])
def related_notes(filepath: str, limit: int = Query(5, ge=1, le=50)):
    """Find semantically related notes."""
    from lib.db import search_chunks, get_chunk_embeddings
    import numpy as np

    full = _resolve(filepath)
    vectors = get_chunk_embeddings(_cfg.db_path, full)
    if not vectors:
        vectors = get_chunk_embeddings(_cfg.db_path, filepath)
    if not vectors:
        raise HTTPException(404, f"No embeddings found for {filepath}")

    mean_vec = list(np.mean(vectors, axis=0))
    candidates = search_chunks(_cfg.db_path, mean_vec, limit=limit * 10)
    seen: set[str] = set()
    results = []
    for r in candidates:
        fp = r["filepath"]
        if fp in (full, filepath) or fp in seen:
            continue
        seen.add(fp)
        results.append(
            SearchResult(
                filepath=fp,
                title=r.get("title"),
                type=r.get("type"),
                status=r.get("status"),
                created=r.get("created"),
                tags=r.get("tags") or [],
                content_preview=r.get("content", "")[:400],
                distance=r.get("distance"),
            )
        )
        if len(results) == limit:
            break
    return results


@app.get("/api/notes/{filepath:path}/backlinks", response_model=list[BacklinkEntry])
def get_backlinks(filepath: str):
    """Find all notes that contain a [[wikilink]] to this note."""
    full = _resolve(filepath)
    return _find_backlinks(full)


@app.get("/api/notes/{filepath:path}", response_model=NoteResponse)
def read_note(filepath: str):
    """Read a note with parsed frontmatter and extracted wikilinks."""
    full = _resolve(filepath)
    raw = _read_file(full)
    return _parse_note(_relative(full), raw)


@app.put("/api/notes/{filepath:path}", response_model=EditResponse)
def write_note(filepath: str, req: WriteRequest):
    """Full file write (replace entire content)."""
    full = _resolve(filepath)
    _write_file(full, req.content)
    return EditResponse(filepath=_relative(full), success=True, detail="File written")


@app.patch("/api/notes/{filepath:path}", response_model=EditResponse)
def edit_note(filepath: str, req: EditRequest):
    """Surgical edit: modify a note without full-file replacement."""
    full = _resolve(filepath)
    text = _read_file(full)
    op = req.op

    if op == EditOp.update_frontmatter:
        if not req.frontmatter:
            raise HTTPException(400, "'frontmatter' dict required for update_frontmatter")
        text = update_frontmatter(text, req.frontmatter)
        detail = f"Updated frontmatter keys: {', '.join(req.frontmatter.keys())}"

    elif op in (EditOp.replace_section, EditOp.append_to_section, EditOp.prepend_to_section):
        if not req.heading:
            raise HTTPException(400, f"'heading' required for {op.value}")
        body = req.body or ""
        if op == EditOp.replace_section:
            text, found = replace_section(text, req.heading, body)
        elif op == EditOp.append_to_section:
            text, found = append_to_section(text, req.heading, body)
        else:
            text, found = prepend_to_section(text, req.heading, body)
        if not found:
            raise HTTPException(404, f"Section not found: {req.heading}")
        detail = f"{op.value}: {req.heading}"

    elif op == EditOp.replace_lines:
        if req.start_line is None or req.end_line is None:
            raise HTTPException(400, "'start_line' and 'end_line' required")
        text, err = replace_lines(text, req.start_line, req.end_line, req.replacement or "")
        if err:
            raise HTTPException(400, err)
        detail = f"Replaced lines [{req.start_line}, {req.end_line})"

    elif op == EditOp.find_replace:
        if req.find is None:
            raise HTTPException(400, "'find' required for find_replace")
        text, n = find_replace(
            text, req.find, req.replace or "", regex=req.regex, count=req.count
        )
        if n == -1:
            raise HTTPException(400, text)  # text is the error message
        detail = f"Replaced {n} occurrence(s)"

    elif op == EditOp.insert_wikilink:
        if not req.target:
            raise HTTPException(400, "'target' required for insert_wikilink")
        text, inserted = insert_wikilink(text, req.target, context_heading=req.context_heading)
        if not inserted:
            return EditResponse(filepath=_relative(full), success=True, detail="Link already present")
        detail = f"Inserted [[{req.target}]]"

    else:
        raise HTTPException(400, f"Unknown edit operation: {op}")

    _write_file(full, text)
    return EditResponse(filepath=_relative(full), success=True, detail=detail)


@app.post("/api/notes", response_model=EditResponse)
def create_note(req: CreateRequest):
    """Create a new note from a template."""
    result = handle_brain_create(
        template=req.template,
        title=req.title,
        brain_path=_cfg.brain_path,
        directory=req.directory,
    )
    if "failed" in result.lower():
        raise HTTPException(400, result)
    return EditResponse(filepath=_relative(result), success=True, detail=f"Created: {result}")


@app.get("/api/templates", response_model=list[str])
def list_templates():
    """List available note templates."""
    return _list_template_names(brain_path=_cfg.brain_path)


def main():
    import uvicorn

    host = os.environ.get("BRAIN_API_HOST", "0.0.0.0")
    port = int(os.environ.get("BRAIN_API_PORT", "7779"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
