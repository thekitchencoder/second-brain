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
from lib.auth import OWNER
from lib.visibility import visible, can_write, can_write_transition
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


def _principal_unrestricted(principal) -> bool:
    """True for owner / non-RBAC callers (read_layers=("*",)) — the fast path that
    skips every visibility read below, keeping mode=none callers byte-for-byte
    unchanged (no extra disk I/O, no pagination, no behaviour change)."""
    layers = getattr(principal, "read_layers", None)
    return isinstance(layers, (tuple, list, set, frozenset)) and "*" in layers


def _principal_write_unrestricted(principal) -> bool:
    """True for owner / non-RBAC callers (write_layers=("*",)) — the WRITE-dimension
    fast path. Distinct from _principal_unrestricted (which keys on read_layers):
    a principal can be read-unrestricted (read=["*"]) while still being
    write-restricted (e.g. write=["fiction"]), and the two must never be
    conflated — doing so is exactly the reviewer-escalation this guards against."""
    layers = getattr(principal, "write_layers", None)
    return isinstance(layers, (tuple, list, set, frozenset)) and "*" in layers


def _meta_for_path(fp: str) -> dict:
    """Best-effort frontmatter read for a search-result path. Unreadable → {},
    which fails visible() closed for a restricted principal (deny-by-default on
    a missing/unknown layer) and is a no-op for an unrestricted one."""
    try:
        with open(fp, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return {}
    meta, _ = extract_frontmatter(content)
    return meta


def _template_layer(raw: str) -> Optional[str]:
    """Best-effort `layer` extraction from a zk template's frontmatter block.

    Templates commonly embed unrendered Jinja/Handlebars expressions (e.g.
    `date: {{format-date now "%Y-%m-%d"}}`) that make yaml.safe_load raise on
    the whole block, so extract_frontmatter silently returns {} for every
    bundled template — which would make can_write({"layer": None}, ...) deny
    every non-"*" writer regardless of the template's real layer. Fall back to
    a line-oriented regex scan for `layer: <value>` when full YAML parsing of
    the block fails."""
    meta, _ = extract_frontmatter(raw)
    if "layer" in meta:
        return meta.get("layer")
    if not raw.startswith("---"):
        return None
    end = raw.find("\n---", 3)
    if end == -1:
        return None
    block = raw[3:end]
    m = re.search(r'^layer:\s*(.+?)\s*$', block, re.MULTILINE)
    if not m:
        return None
    return m.group(1).strip().strip('"\'') or None


def _paginated_visible_search(store, vector, limit: int, principal, fields, *,
                               exclude=None, initial_k=None) -> list[dict]:
    """Search the vector store (coarse allowed_layers wall already applied by the
    store), then filter to principal-visible results by reading each candidate's
    own frontmatter (fine). Grows k, doubling, until `limit` visible results are
    collected or the store is exhausted — bounded so a pathological store can't
    spin this forever."""
    exclude = set(exclude or ())
    k = initial_k or limit
    out: list[dict] = []
    for _ in range(6):
        raw = store.search(vector, k=k, allowed_layers=principal.read_layers)
        out = []
        seen: set[str] = set(exclude)
        for r in raw:
            fp = r["filepath"]
            if fp in seen:
                continue
            seen.add(fp)
            if not visible(_meta_for_path(fp), principal, fields):
                continue
            out.append(r)
            if len(out) == limit:
                return out
        if len(raw) < k:
            break  # store exhausted at this k — no more candidates exist
        k *= 2
    return out


# ── Handlers ─────────────────────────────────────────────────────────


def handle_brain_search(query: str, limit: int, db_path: str, *,
                        principal=OWNER, fields=None) -> str:
    from lib.embeddings import get_embedding, EmbeddingError

    try:
        embedding = get_embedding(query)
    except EmbeddingError as e:
        return f"Error: embedding service unavailable — {e}"
    from lib.vectorstore import get_store
    store = get_store(db_path)
    if _principal_unrestricted(principal):
        results = store.search(embedding, k=limit, allowed_layers=principal.read_layers)
    else:
        results = _paginated_visible_search(store, embedding, limit, principal, fields)
    return _format_results(results)


def handle_brain_related(filepath: str, limit: int, db_path: str, brain_path: str, *,
                         principal=OWNER, fields=None) -> str:
    from lib.vectorstore import get_store

    store = get_store(db_path)
    full_path = _resolve_path(filepath, brain_path)
    if not _principal_unrestricted(principal) and os.path.isfile(full_path):
        # Oracle-safety on the TARGET: a forbidden-but-indexed note must return
        # the exact same string as a genuinely-absent one below, or a restricted
        # caller could learn "it's indexed" just from asking what's related to it.
        if not visible(_meta_for_path(full_path), principal, fields):
            return f"No embeddings found for {filepath}. Has it been indexed?"
    vectors = store.get_chunk_embeddings(full_path)
    if not vectors:
        vectors = store.get_chunk_embeddings(filepath)
    if not vectors:
        return f"No embeddings found for {filepath}. Has it been indexed?"
    mean_vec = list(np.mean(vectors, axis=0))
    exclude = {full_path, filepath}
    if _principal_unrestricted(principal):
        candidates = store.search(mean_vec, k=limit * _CANDIDATE_MULTIPLIER,
                                  allowed_layers=principal.read_layers)
        seen: set[str] = set()
        deduped: list[dict] = []
        for r in candidates:
            fp = r["filepath"]
            if fp in exclude or fp in seen:
                continue
            seen.add(fp)
            deduped.append(r)
            if len(deduped) == limit:
                break
        return _format_results(deduped)
    deduped = _paginated_visible_search(
        store, mean_vec, limit, principal, fields,
        exclude=exclude, initial_k=limit * _CANDIDATE_MULTIPLIER,
    )
    return _format_results(deduped)


def _walk_brain_files(brain_path: str) -> list[str]:
    """Walk all markdown files in the brain, skipping dot-directories and templates."""
    candidates = []
    for root, dirs, fnames in os.walk(brain_path):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "templates"]
        candidates += [os.path.join(root, f) for f in fnames if f.endswith(".md")]
    return candidates


def _collect_field_values(brain_path: str, field: str, *,
                          principal=OWNER, fields=None) -> set[str]:
    """Scan all VISIBLE notes and return the set of distinct values for a frontmatter
    field — restricted to `principal`-visible notes so a no-match hint can never
    enumerate a value that only exists on a forbidden note."""
    values: set[str] = set()
    for fpath in _walk_brain_files(brain_path):
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue
        meta, _ = extract_frontmatter(content)
        if not visible(meta, principal, fields):
            continue
        val = meta.get(field)
        if isinstance(val, str) and val:
            values.add(val)
        elif isinstance(val, list):
            values.update(str(v) for v in val if v)
    return values


def _no_match_hint(filters: dict[str, Optional[str]], brain_path: str, *,
                   principal=OWNER, fields=None) -> str:
    """Build a helpful 'no matches' message listing existing values for filtered
    fields — computed only over notes visible to `principal`."""
    parts = ["No notes matched the query."]
    for field in filters:
        existing = sorted(_collect_field_values(brain_path, field, principal=principal, fields=fields))
        if existing:
            parts.append(f"Existing {field} values: {', '.join(existing)}")
    return "\n".join(parts)


def handle_brain_query(
    brain_path: str,
    *,
    tag: Optional[str] = None,
    fields: Optional[dict] = None,
    where: Optional[dict] = None,
    created_after: Optional[str] = None,
    created_before: Optional[str] = None,
    field_specs: Optional[list] = None,
    principal=OWNER,
) -> str:
    # `fields` here is the pre-existing "promoted field values" filter dict (e.g.
    # {"status": "draft"}) — unrelated to the profile Field *specs* used for the
    # visibility predicate, which travel separately as `field_specs` (already
    # threaded through by both callers). Guarded with isinstance so a caller that
    # passes field specs here by mistake degrades to "no promoted filters" rather
    # than crashing on `.items()`.
    field_filters = ({k: v for k, v in fields.items() if v}
                     if isinstance(fields, dict) else {})
    where = {k: v for k, v in (where or {}).items() if v}

    collision = set(field_filters) & set(where)
    if collision:
        return ("Invalid filter: " + ", ".join(sorted(collision)) +
                " given both as a promoted field and in 'where'")

    all_filters = {**field_filters, **where}
    kind_of = {f.name: f.kind for f in (field_specs or [])}

    if tag:
        if err := _validate_query_param("tag", tag):
            return err
    for name in where:
        if err := _validate_query_param(name, name):
            return err
    for name, value in all_filters.items():
        if err := _validate_query_param(name, value):
            return err

    # Validate date params
    for name, value in [("created_after", created_after), ("created_before", created_before)]:
        if value:
            try:
                datetime.strptime(value, "%Y-%m-%d")
            except ValueError:
                return f"Invalid {name}: expected YYYY-MM-DD format"

    # Frontmatter filters require walking files directly — zk's FTS won't match them.
    # tag uses zk's native --tag filter, which is index-backed and correct.
    # A restricted principal ALSO forces this branch (even with zero filters): it's
    # the one that reads each candidate's frontmatter, so it's where visible() gets
    # applied. This deliberately routes restricted queries away from the "list
    # everything via zk" path below, which never reads frontmatter and would
    # otherwise leak notes the caller isn't allowed to see.
    restricted = not _principal_unrestricted(principal)
    has_frontmatter_filter = bool(all_filters) or bool(created_after or created_before) or restricted

    if has_frontmatter_filter:
        # Collect candidates via zk if a tag filter is also present, otherwise all files
        if tag:
            # Refresh zk index first so tag filter is current
            try:
                subprocess.run(
                    ["zk", "index", "--quiet"],
                    cwd=brain_path, capture_output=True, text=True, timeout=60
                )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass
            try:
                result = subprocess.run(
                    ["zk", "list", "--quiet", "--format", "{{path}}", "--tag", tag],
                    cwd=brain_path, capture_output=True, text=True, timeout=30
                )
            except FileNotFoundError:
                return "zk is not installed or not on PATH. Is the container running?"
            except subprocess.TimeoutExpired:
                return "Error: zk timed out"
            if result.returncode != 0:
                return f"zk list failed: {result.stderr}"
            candidates = [
                os.path.join(brain_path, f.strip())
                for f in result.stdout.splitlines() if f.strip()
            ]
        else:
            candidates = _walk_brain_files(brain_path)

        files = []
        for fpath in candidates:
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception:
                continue
            meta, _ = extract_frontmatter(content)
            if not visible(meta, principal, field_specs):
                continue
            skip = False
            for field, value in all_filters.items():
                mv = meta.get(field)
                if value == "unset":
                    if mv:
                        skip = True
                        break
                elif kind_of.get(field, "scalar") == "list":
                    mvlist = mv if isinstance(mv, list) else ([mv] if mv else [])
                    if value not in mvlist:
                        skip = True
                        break
                else:
                    if mv != value:
                        skip = True
                        break
            if skip:
                continue
            if created_after or created_before:
                created = meta.get("created") or meta.get("date") or ""
                if isinstance(created, str):
                    created_str = created[:10]  # handle datetime strings
                else:
                    created_str = str(created)[:10]
                if not created_str:
                    continue
                if created_after and created_str < created_after:
                    continue
                if created_before and created_str > created_before:
                    continue
            files.append(os.path.relpath(fpath, brain_path))

        if not files:
            return _no_match_hint(all_filters, brain_path, principal=principal, fields=field_specs)
        return "\n".join(sorted(files))

    # tag-only query: use zk with index refresh. Only unrestricted (owner /
    # non-RBAC) principals ever reach this branch — `restricted` above forces
    # anyone else into the frontmatter-reading branch — but the visible() gate
    # is applied here too, defensively, in case that routing ever changes.
    try:
        subprocess.run(
            ["zk", "index", "--quiet"],
            cwd=brain_path, capture_output=True, text=True, timeout=60
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    cmd = ["zk", "list", "--quiet", "--format", "{{path}}"]
    if tag:
        cmd += ["--tag", tag]
    try:
        result = subprocess.run(cmd, cwd=brain_path, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        return "zk is not installed or not on PATH. Is the container running?"
    except subprocess.TimeoutExpired:
        return "Error: zk timed out"
    if result.returncode != 0:
        return f"zk list failed: {result.stderr}"
    files = [f.strip() for f in result.stdout.splitlines() if f.strip()]
    if not _principal_unrestricted(principal):
        visible_files = []
        for f in files:
            full = os.path.join(brain_path, f)
            try:
                with open(full, "r", encoding="utf-8") as fh:
                    content = fh.read()
            except Exception:
                continue
            meta, _ = extract_frontmatter(content)
            if visible(meta, principal, field_specs):
                visible_files.append(f)
        files = visible_files
    if not files:
        return "No notes matched the query."
    return "\n".join(files)


def handle_brain_write(filepath: str, content: str, brain_path: str, *,
                       principal=OWNER, fields=None) -> str:
    """Write content to a file inside the brain."""
    full_path = _resolve_path(filepath, brain_path)
    if err := _check_within_brain(full_path, brain_path):
        return err
    new_meta, _ = extract_frontmatter(content)
    if os.path.isfile(full_path):
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                existing_content = f.read()
        except Exception as e:
            return f"Error reading {filepath}: {e}"
        old_meta, _ = extract_frontmatter(existing_content)
        if not visible(old_meta, principal, fields):
            # Oracle-safe: can't even see the target being overwritten.
            return f"File not found: {filepath}"
    else:
        old_meta = new_meta  # brand-new path — only the incoming layer gates
    if not can_write_transition(old_meta, new_meta, principal):
        return f"Not authorized to write {filepath}"
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    try:
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Written: {full_path}"
    except Exception as e:
        return f"Error writing {filepath}: {e}"


def handle_brain_read(filepath: str, brain_path: str, *,
                      principal=OWNER, fields=None) -> str:
    """Read a file from the brain and return its full content."""
    full_path = _resolve_path(filepath, brain_path)
    if err := _check_within_brain(full_path, brain_path):
        return err
    if not os.path.isfile(full_path):
        return "File not found"
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return f"Error reading {filepath}: {e}"
    meta, _ = extract_frontmatter(content)
    if not visible(meta, principal, fields):
        # Oracle-safe: a fixed string, carrying no path-specific detail, so a
        # forbidden note is byte-for-byte indistinguishable from an absent one —
        # even across two DIFFERENT requested paths, not just the same one.
        return "File not found"
    return content


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
    template: str, title: str, brain_path: str, directory: Optional[str] = None, *,
    principal=OWNER, fields=None,
) -> str:
    # Validate template is a bare filename — no path separators or traversal
    if not title or not title.strip():
        return "Error: title is required"
    bare = template[:-3] if template.endswith(".md") else template
    if "/" in bare or "\\" in bare or ".." in bare:
        return "Invalid template name: must be a bare filename with no path separators"
    if not template.endswith(".md"):
        template = template + ".md"
    tpl_path = os.path.join(brain_path, ".zk", "templates", template)
    tpl_layer = None
    if os.path.isfile(tpl_path):
        try:
            with open(tpl_path, "r", encoding="utf-8") as f:
                tpl_layer = _template_layer(f.read())
        except Exception:
            tpl_layer = None
    if not can_write({"layer": tpl_layer}, principal):
        return f"Not authorized to create from template: {template}"
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


def handle_brain_edit(filepath: str, op: str, brain_path: str, *,
                      principal=OWNER, fields=None, **kwargs) -> str:
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

    old_meta, _ = extract_frontmatter(text)
    if not visible(old_meta, principal, fields):
        # Oracle-safe: can't even see the target being edited.
        return f"File not found: {filepath}"

    # Apply the edit op to produce the candidate text IN MEMORY first — never
    # persist before authorizing. The post-edit frontmatter is authoritative
    # for every op (including update_frontmatter): a raw-text op like
    # find_replace/replace_lines can rewrite the `layer:` line just as surely
    # as update_frontmatter can, so gating on a stale `new_meta = old_meta`
    # would let those ops smuggle a layer escalation past the check.
    if op == "update_frontmatter":
        frontmatter = kwargs.get("frontmatter")
        if not frontmatter:
            return "Error: 'frontmatter' dict required for update_frontmatter"
        candidate = update_frontmatter(text, frontmatter)
        detail = f"Updated frontmatter keys: {', '.join(frontmatter.keys())}"

    elif op in ("replace_section", "append_to_section", "prepend_to_section"):
        heading = kwargs.get("heading")
        if not heading:
            return f"Error: 'heading' required for {op}"
        body = kwargs.get("body", "")
        if op == "replace_section":
            candidate, found = replace_section(text, heading, body)
        elif op == "append_to_section":
            candidate, found = append_to_section(text, heading, body)
        else:
            candidate, found = prepend_to_section(text, heading, body)
        if not found:
            return f"Section not found: {heading}"
        detail = f"{op}: {heading}"

    elif op == "replace_lines":
        start_line = kwargs.get("start_line")
        end_line = kwargs.get("end_line")
        if start_line is None or end_line is None:
            return "Error: 'start_line' and 'end_line' required"
        candidate, err = replace_lines(text, start_line, end_line, kwargs.get("replacement", ""))
        if err:
            return f"Error: {err}"
        detail = f"Replaced lines [{start_line}, {end_line})"

    elif op == "find_replace":
        find_str = kwargs.get("find")
        if find_str is None:
            return "Error: 'find' required for find_replace"
        candidate, n = find_replace(
            text, find_str, kwargs.get("replace", ""),
            regex=kwargs.get("regex", False),
            count=kwargs.get("count", 0),
        )
        if n == -1:
            return candidate  # candidate is the error message
        detail = f"Replaced {n} occurrence(s)"

    elif op == "insert_wikilink":
        target = kwargs.get("target")
        if not target:
            return "Error: 'target' required for insert_wikilink"
        candidate, inserted = insert_wikilink(
            text, target, context_heading=kwargs.get("context_heading"),
        )
        if not inserted:
            return f"Link [[{target}]] already present"
        detail = f"Inserted [[{target}]]"

    else:
        return f"Unknown edit operation: {op}"

    new_meta, _ = extract_frontmatter(candidate)
    if not can_write_transition(old_meta, new_meta, principal):
        return f"Not authorized to write {filepath}"

    try:
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(candidate)
    except Exception as e:
        return f"Error writing {filepath}: {e}"
    return detail


def handle_brain_backlinks(filepath: str, brain_path: str, *,
                           principal=OWNER, fields=None) -> str:
    """Find notes that link to *filepath* via [[wikilinks]]."""
    full_path = _resolve_path(filepath, brain_path)
    if err := _check_within_brain(full_path, brain_path):
        return err
    rel = _relative_path(full_path, brain_path)
    results = find_backlinks(full_path, brain_path)
    if not _principal_unrestricted(principal):
        visible_results = []
        for r in results:
            src_full = os.path.join(brain_path, r["filepath"])
            try:
                with open(src_full, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception:
                continue  # unreadable source note — never surface it (fail closed)
            meta, _ = extract_frontmatter(content)
            if visible(meta, principal, fields):
                visible_results.append(r)
        results = visible_results
    if not results:
        return "No backlinks found."
    lines = [f"- **{r['title']}** ({r['filepath']})" for r in results]
    return f"Backlinks to {rel}:\n" + "\n".join(lines)


def handle_brain_trash(filepath: str, brain_path: str, db_path: str, *,
                       principal=OWNER, fields=None) -> str:
    """Move a note to .trash/, clean from DB, report orphaned backlinks."""
    full_path = _resolve_path(filepath, brain_path)
    if err := _check_within_brain(full_path, brain_path):
        return err
    if not full_path.endswith(".md"):
        return f"Error: only .md files can be trashed, got: {filepath}"
    if not os.path.isfile(full_path):
        return f"Error: file not found: {filepath}"

    try:
        with open(full_path, "r", encoding="utf-8") as f:
            existing_content = f.read()
    except Exception as e:
        return f"Error reading {filepath}: {e}"
    old_meta, _ = extract_frontmatter(existing_content)
    if not visible(old_meta, principal, fields):
        # Oracle-safe: can't even see the target being trashed.
        return f"File not found: {filepath}"
    if not can_write(old_meta, principal):
        return f"Not authorized to write {filepath}"

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
    if backlinks and not _principal_unrestricted(principal):
        # M3: don't leak paths of invisible notes to a restricted trasher via
        # the orphaned-backlinks report.
        backlinks = [
            b for b in backlinks
            if visible(_meta_for_path(os.path.join(brain_path, b["filepath"])), principal, fields)
        ]
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


def handle_brain_restore(trash_path: str, brain_path: str, *,
                         principal=OWNER, fields=None) -> str:
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

    try:
        with open(full_trash_path, "r", encoding="utf-8") as f:
            existing_content = f.read()
    except Exception as e:
        return f"Error reading {trash_path}: {e}"
    old_meta, _ = extract_frontmatter(existing_content)
    if not visible(old_meta, principal, fields):
        # Oracle-safe: identical to the genuinely-absent-from-trash branch
        # above — a restricted caller can neither resurrect nor enumerate it.
        return f"Error: file not found in trash: {trash_path}"
    if not can_write(old_meta, principal):
        return f"Not authorized to write {trash_path}"

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
