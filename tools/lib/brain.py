"""Shared brain service layer.

Handler functions and helpers used by both the MCP server and the REST API.
"""
import os
import re
import subprocess
from typing import Optional

import numpy as np

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

_PREVIEW_LENGTH = 400       # chars of content shown per result
_CANDIDATE_MULTIPLIER = 10  # raw candidates before deduping by file
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


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
    """Return path relative to *brain_path*."""
    if full_path.startswith(brain_path):
        return full_path[len(brain_path):].lstrip("/")
    return full_path


# ── Handlers ─────────────────────────────────────────────────────────


def handle_brain_search(query: str, limit: int, db_path: str) -> str:
    from lib.db import search_chunks
    from lib.embeddings import get_embedding

    embedding = get_embedding(query)
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
    cmd = ["zk", "list", "--quiet", "--format", "{{path}}"]
    if tag:
        cmd += ["--tag", tag]
    if status:
        cmd += ["--match", f"status:{status}"]
    if note_type:
        cmd += ["--match", f"type:{note_type}"]
    try:
        result = subprocess.run(cmd, cwd=brain_path, capture_output=True, text=True)
    except FileNotFoundError:
        return "zk is not installed or not on PATH. Is the container running?"
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


def handle_brain_templates(brain_path: str) -> str:
    """List available zk templates."""
    templates_dir = os.path.join(brain_path, ".zk", "templates")
    if not os.path.isdir(templates_dir):
        return "No templates directory found. Has the brain been initialised with brain-init?"
    names = sorted(
        os.path.splitext(f)[0]
        for f in os.listdir(templates_dir)
        if f.endswith(".md")
    )
    if not names:
        return "No templates found."
    return "Available templates (use these exact names with brain_create):\n" + "\n".join(
        f"  {n}" for n in names
    )


def handle_brain_create(
    template: str, title: str, brain_path: str, directory: Optional[str] = None
) -> str:
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
            cwd=brain_path, capture_output=True, text=True,
        )
    except FileNotFoundError:
        return "zk is not installed or not on PATH. Is the container running?"
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
    stem = os.path.splitext(os.path.basename(rel))[0]
    targets = {rel, os.path.splitext(rel)[0], stem}
    backlinks: list[str] = []
    for root, dirs, files in os.walk(brain_path):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fname in files:
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(root, fname)
            if os.path.realpath(fpath) == os.path.realpath(full_path):
                continue
            try:
                content = open(fpath, "r", encoding="utf-8").read()
            except Exception:
                continue
            for m in _WIKILINK_RE.finditer(content):
                link_target = m.group(1).strip()
                if link_target in targets:
                    meta, _ = extract_frontmatter(content)
                    rel_link = _relative_path(fpath, brain_path)
                    title = meta.get("title", fname)
                    backlinks.append(f"- **{title}** ({rel_link})")
                    break
    if not backlinks:
        return "No backlinks found."
    return f"Backlinks to {rel}:\n" + "\n".join(backlinks)


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
