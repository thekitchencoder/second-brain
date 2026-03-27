"""Shared brain service layer.

Handler functions and helpers used by both the MCP server and the REST API.
"""
import os
import re
import subprocess
from datetime import datetime
from typing import Optional

import numpy as np

from lib.config import Config
from lib.db import delete_file_chunks
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

_PREVIEW_LENGTH = 400       # chars of content shown per result
_CANDIDATE_MULTIPLIER = 10  # raw candidates before deduping by file
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
_SAFE_PARAM_RE = re.compile(r'^[a-zA-Z0-9\-_]+$')


def _validate_query_param(name: str, value: str) -> Optional[str]:
    """Return an error string if value contains unsafe characters, else None."""
    if not _SAFE_PARAM_RE.match(value):
        return f"Invalid {name}: must contain only letters, digits, hyphens and underscores"
    return None


def _check_within_brain(path: str, brain_path: str, label: str = "path") -> Optional[str]:
    """Return an error string if *path* is outside *brain_path*, else None."""
    brain_real = os.path.realpath(brain_path)
    try:
        target_real = os.path.realpath(os.path.abspath(path))
    except Exception:
        return f"Invalid {label}: {path}"
    if not (target_real == brain_real or target_real.startswith(brain_real + "/")):
        return f"Error: {label} is outside the brain: {path}"
    return None


def _format_results(results: list[dict]) -> str:
    if not results:
        return "No results found."
    lines: list[str] = []
    for r in results:
        tags = ", ".join(r.get("tags") or [])
        lines += [
            f"### {r.get('title') or r['filepath']}",
            f"- **File:** {r['filepath']}",
            f"- **Type:** {r.get('type', '-')}  **Status:** {r.get('status', '-')}",
            f"- **Created:** {r.get('created', '-')}  **Tags:** {tags or '-'}",
            "",
            r.get("content", "")[:_PREVIEW_LENGTH].strip(),
            "",
            "---",
            "",
        ]
    return "\n".join(lines)


def _resolve_path(filepath: str, brain_path: str) -> str:
    """Resolve *filepath* to an absolute path within the brain."""
    return filepath if filepath.startswith("/") else os.path.join(brain_path, filepath)


def _relative_path(full_path: str, brain_path: str) -> str:
    """Return path relative to *brain_path*, or the original path if outside."""
    try:
        rel = os.path.relpath(full_path, brain_path)
    except ValueError:
        return full_path  # Windows: different drives
    if rel.startswith(".."):
        return full_path  # outside brain_path — return unchanged
    return rel


# ── Handlers ─────────────────────────────────────────────────────────


def handle_brain_search(query: str, limit: int, db_path: str) -> str:
    from lib.embeddings import get_embedding, EmbeddingError

    try:
        embedding = get_embedding(query)
    except EmbeddingError as e:
        return f"Error: embedding service unavailable — {e}"
    from lib.db import search_chunks
    results = search_chunks(db_path, embedding, limit=limit)
    return _format_results(results)


def handle_brain_related(filepath: str, limit: int, db_path: str, brain_path: str) -> str:
    from lib.db import get_chunk_embeddings, search_chunks

    full_path = _resolve_path(filepath, brain_path)
    vectors = get_chunk_embeddings(db_path, full_path)
    if not vectors:
        vectors = get_chunk_embeddings(db_path, filepath)
    if not vectors:
        return f"No embeddings found for {filepath}. Has it been indexed?"
    mean_vec = list(np.mean(vectors, axis=0))
    candidates = search_chunks(db_path, mean_vec, limit=limit * _CANDIDATE_MULTIPLIER)
    seen: set[str] = set()
    deduped: list[dict] = []
    for r in candidates:
        fp = r["filepath"]
        if fp in (full_path, filepath) or fp in seen:
            continue
        seen.add(fp)
        deduped.append(r)
        if len(deduped) == limit:
            break
    return _format_results(deduped)


def handle_brain_query(
    tag: Optional[str], status: Optional[str], note_type: Optional[str], brain_path: str
) -> str:
    for name, value in [("tag", tag), ("status", status), ("type", note_type)]:
        if value:
            if err := _validate_query_param(name, value):
                return err
    cmd = ["zk", "list", "--quiet", "--format", "{{path}}"]
    if tag:
        cmd += ["--tag", tag]
    if status:
        cmd += ["--match", f"status:{status}"]
    if note_type:
        cmd += ["--match", f"type:{note_type}"]
    try:
        result = subprocess.run(cmd, cwd=brain_path, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        return "zk is not installed or not on PATH. Is the container running?"
    except subprocess.TimeoutExpired:
        return "Error: zk timed out"
    if result.returncode != 0:
        return f"zk list failed: {result.stderr}"
    files = [f.strip() for f in result.stdout.splitlines() if f.strip()]
    if not files:
        return "No notes matched the query."
    return "\n".join(files)


def handle_brain_write(filepath: str, content: str, brain_path: str) -> str:
    """Write content to a file inside the brain."""
    full_path = _resolve_path(filepath, brain_path)
    if err := _check_within_brain(full_path, brain_path):
        return err
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    try:
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Written: {full_path}"
    except Exception as e:
        return f"Error writing {filepath}: {e}"


def handle_brain_read(filepath: str, brain_path: str) -> str:
    """Read a file from the brain and return its full content."""
    full_path = _resolve_path(filepath, brain_path)
    if err := _check_within_brain(full_path, brain_path):
        return err
    if not os.path.isfile(full_path):
        return f"File not found: {filepath}"
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error reading {filepath}: {e}"


def _list_template_names(brain_path: str) -> list[str]:
    """Return sorted list of template names (without .md extension)."""
    templates_dir = os.path.join(brain_path, ".zk", "templates")
    if not os.path.isdir(templates_dir):
        return []
    return sorted(
        os.path.splitext(f)[0]
        for f in os.listdir(templates_dir)
        if f.endswith(".md")
    )


def handle_brain_templates(brain_path: str) -> str:
    """List available zk templates."""
    names = _list_template_names(brain_path)
    if not names:
        templates_dir = os.path.join(brain_path, ".zk", "templates")
        if not os.path.isdir(templates_dir):
            return "No templates directory found. Has the brain been initialised with brain-init?"
        return "No templates found."
    return "Available templates (use these exact names with brain_create):\n" + "\n".join(
        f"  {n}" for n in names
    )


def handle_brain_create(
    template: str, title: str, brain_path: str, directory: Optional[str] = None
) -> str:
    # Validate template is a bare filename — no path separators or traversal
    if not title or not title.strip():
        return "Error: title is required"
    bare = template[:-3] if template.endswith(".md") else template
    if "/" in bare or "\\" in bare or ".." in bare:
        return "Invalid template name: must be a bare filename with no path separators"
    if not template.endswith(".md"):
        template = template + ".md"
    if directory:
        target_dir = directory if directory.startswith("/") else os.path.join(brain_path, directory)
        if err := _check_within_brain(target_dir, brain_path, label="directory"):
            return err
        os.makedirs(target_dir, exist_ok=True)
    else:
        target_dir = brain_path
    try:
        result = subprocess.run(
            [
                "zk", "new", "--working-dir", target_dir,
                "--template", template, "--title", title, "--print-path",
            ],
            cwd=brain_path, capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError:
        return "zk is not installed or not on PATH. Is the container running?"
    except subprocess.TimeoutExpired:
        return "Error: zk timed out"
    if result.returncode != 0:
        available = handle_brain_templates(brain_path)
        return f"zk new failed: {result.stderr.strip()}\n\n{available}"
    return result.stdout.strip()


def handle_brain_edit(filepath: str, op: str, brain_path: str, **kwargs) -> str:
    """Surgical edit on a note. Returns a status message.

    Supported ops: update_frontmatter, replace_section, append_to_section,
    prepend_to_section, replace_lines, find_replace, insert_wikilink.
    """
    full_path = _resolve_path(filepath, brain_path)
    if err := _check_within_brain(full_path, brain_path):
        return err
    if not os.path.isfile(full_path):
        return f"File not found: {filepath}"
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            text = f.read()
    except Exception as e:
        return f"Error reading {filepath}: {e}"

    if op == "update_frontmatter":
        frontmatter = kwargs.get("frontmatter")
        if not frontmatter:
            return "Error: 'frontmatter' dict required for update_frontmatter"
        text = update_frontmatter(text, frontmatter)
        detail = f"Updated frontmatter keys: {', '.join(frontmatter.keys())}"

    elif op in ("replace_section", "append_to_section", "prepend_to_section"):
        heading = kwargs.get("heading")
        if not heading:
            return f"Error: 'heading' required for {op}"
        body = kwargs.get("body", "")
        if op == "replace_section":
            text, found = replace_section(text, heading, body)
        elif op == "append_to_section":
            text, found = append_to_section(text, heading, body)
        else:
            text, found = prepend_to_section(text, heading, body)
        if not found:
            return f"Section not found: {heading}"
        detail = f"{op}: {heading}"

    elif op == "replace_lines":
        start_line = kwargs.get("start_line")
        end_line = kwargs.get("end_line")
        if start_line is None or end_line is None:
            return "Error: 'start_line' and 'end_line' required"
        text, err = replace_lines(text, start_line, end_line, kwargs.get("replacement", ""))
        if err:
            return f"Error: {err}"
        detail = f"Replaced lines [{start_line}, {end_line})"

    elif op == "find_replace":
        find_str = kwargs.get("find")
        if find_str is None:
            return "Error: 'find' required for find_replace"
        text, n = find_replace(
            text, find_str, kwargs.get("replace", ""),
            regex=kwargs.get("regex", False),
            count=kwargs.get("count", 0),
        )
        if n == -1:
            return text  # text is the error message
        detail = f"Replaced {n} occurrence(s)"

    elif op == "insert_wikilink":
        target = kwargs.get("target")
        if not target:
            return "Error: 'target' required for insert_wikilink"
        text, inserted = insert_wikilink(
            text, target, context_heading=kwargs.get("context_heading"),
        )
        if not inserted:
            return f"Link [[{target}]] already present"
        detail = f"Inserted [[{target}]]"

    else:
        return f"Unknown edit operation: {op}"

    try:
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception as e:
        return f"Error writing {filepath}: {e}"
    return detail


def handle_brain_backlinks(filepath: str, brain_path: str) -> str:
    """Find notes that link to *filepath* via [[wikilinks]]."""
    full_path = _resolve_path(filepath, brain_path)
    if err := _check_within_brain(full_path, brain_path):
        return err
    rel = _relative_path(full_path, brain_path)
    results = find_backlinks(full_path, brain_path)
    if not results:
        return "No backlinks found."
    lines = [f"- **{r['title']}** ({r['filepath']})" for r in results]
    return f"Backlinks to {rel}:\n" + "\n".join(lines)


def handle_brain_trash(filepath: str, brain_path: str, db_path: str) -> str:
    """Move a note to .trash/, clean from DB, report orphaned backlinks."""
    full_path = _resolve_path(filepath, brain_path)
    if err := _check_within_brain(full_path, brain_path):
        return err
    if not full_path.endswith(".md"):
        return f"Error: only .md files can be trashed, got: {filepath}"
    if not os.path.isfile(full_path):
        return f"Error: file not found: {filepath}"

    rel = _relative_path(full_path, brain_path)
    trash_root = os.path.join(brain_path, ".trash")
    dest_path = os.path.join(trash_root, rel)
    origin_sidecar: Optional[str] = None

    if os.path.exists(dest_path):
        stem, ext = os.path.splitext(os.path.basename(dest_path))
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        suffixed_name = f"{stem}.{stamp}{ext}"
        dest_path = os.path.join(os.path.dirname(dest_path), suffixed_name)
        origin_sidecar = os.path.splitext(dest_path)[0] + ".origin"

    backlinks = find_backlinks(full_path, brain_path)
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    os.rename(full_path, dest_path)

    if origin_sidecar:
        with open(origin_sidecar, "w", encoding="utf-8") as f:
            f.write(rel)

    if os.path.exists(db_path):
        delete_file_chunks(db_path, full_path)
    trash_rel = _relative_path(dest_path, brain_path)

    if backlinks:
        bl_paths = ", ".join(b["filepath"] for b in backlinks)
        bl_msg = f"{len(backlinks)} backlink(s) now orphaned: {bl_paths}."
    else:
        bl_msg = "No backlinks."

    return (
        f"Trashed {rel}. {bl_msg} "
        f"Restore with brain_restore('{trash_rel}')."
    )


def handle_brain_restore(trash_path: str, brain_path: str) -> str:
    """Restore a note from .trash/ back to its original location."""
    normalized = trash_path.lstrip("/")
    if not normalized.startswith(".trash/"):
        return "Error: trash_path must start with '.trash/' (e.g. '.trash/Cards/foo.md')"
    if not normalized.endswith(".md"):
        return f"Error: only .md files can be restored, got: {trash_path}"

    full_trash_path = _resolve_path(normalized, brain_path)
    if err := _check_within_brain(full_trash_path, brain_path):
        return err
    if not os.path.isfile(full_trash_path):
        return f"Error: file not found in trash: {trash_path}"

    origin_sidecar = os.path.splitext(full_trash_path)[0] + ".origin"
    if os.path.isfile(origin_sidecar):
        with open(origin_sidecar, "r", encoding="utf-8") as f:
            original_rel = f.read().strip()
    else:
        original_rel = normalized[len(".trash/"):]

    if original_rel.startswith("..") or original_rel.startswith("/"):
        return f"Error: original path in sidecar is invalid: {original_rel}"
    dest_path = os.path.join(brain_path, original_rel)
    if err := _check_within_brain(dest_path, brain_path):
        return f"Error: restore destination is outside the brain: {err}"
    if os.path.exists(dest_path):
        return (
            f"Error: {original_rel} already exists at the destination. "
            f"Resolve the conflict before restoring."
        )

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    os.rename(full_trash_path, dest_path)

    if os.path.isfile(origin_sidecar):
        os.remove(origin_sidecar)

    return (
        f"Restored {original_rel}. "
        f"The file watcher will re-index it shortly."
    )


def extract_wikilinks(text: str) -> list[dict]:
    """Extract [[wikilinks]] from text. Returns list of {target, alias?}."""
    links = []
    for m in _WIKILINK_RE.finditer(text):
        link: dict = {"target": m.group(1).strip()}
        if m.group(2):
            link["alias"] = m.group(2).strip()
        links.append(link)
    return links


def find_backlinks(filepath: str, brain_path: str) -> list[dict]:
    """Walk the brain and find notes that contain a [[wikilink]] to filepath.

    Returns list of {filepath, title} dicts for the REST API.
    """
    rel = _relative_path(filepath, brain_path)
    stem = os.path.splitext(os.path.basename(rel))[0]
    targets = {rel, os.path.splitext(rel)[0], stem}
    backlinks: list[dict] = []
    for root, dirs, files in os.walk(brain_path):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fname in files:
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(root, fname)
            if os.path.realpath(fpath) == os.path.realpath(filepath):
                continue
            try:
                content = open(fpath, "r", encoding="utf-8").read()
            except Exception:
                continue
            for m in _WIKILINK_RE.finditer(content):
                link_target = m.group(1).strip()
                if link_target in targets:
                    meta, _ = extract_frontmatter(content)
                    backlinks.append({
                        "filepath": _relative_path(fpath, brain_path),
                        "title": meta.get("title", fname),
                    })
                    break
    return backlinks
