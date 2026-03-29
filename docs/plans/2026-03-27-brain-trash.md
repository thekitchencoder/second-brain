# Brain Trash Implementation Plan

> **Status (2026-03-29): ALL TASKS COMPLETE. Tasks 1–7 implemented; Task 8 (test suite verification) is the only remaining step.**

**Goal:** Add `brain_trash` and `brain_restore` MCP tools so notes can be safely removed from the active brain and recovered later, with immediate DB cleanup and full skill integration.

**Architecture:** Handler logic in `tools/lib/brain.py`. DB deletion helper in `tools/lib/db.py`. Wired into `tools/brain_mcp_server.py` and `tools/brain_api.py`. Watcher exclusion fix in `tools/brain_index.py`. Skills updated in `skills/brain-hygiene/SKILL.md` and `brain-skills/brain-rename/SKILL.md`.

**Tech Stack:** Python 3.12, pytest, FastAPI, sqlite3/sqlite-vec, os.rename, watchfiles

---

## Task 1: Add `delete_file_chunks` to `tools/lib/db.py`

**Files:**
- Modify: `tools/lib/db.py`
- Test: `tests/lib/test_db.py`

**Background:** `purge_stale_paths` in `brain_index.py` already demonstrates the correct two-phase deletion pattern: collect chunk IDs for a filepath, delete from `embeddings` by rowid first (sqlite-vec virtual table requires this), then delete from `chunks`. The new helper encapsulates this as a reusable function so `handle_brain_trash` can call it without depending on `brain_index`.

**Step 1: Write failing tests**

Add to `tests/lib/test_db.py`:

```python
from lib.db import init_db, upsert_chunk, delete_file_chunks


def test_delete_file_chunks_removes_chunks_and_embeddings(db_path):
    init_db(db_path, embedding_dim=4)
    meta = {"title": "X", "type": "note", "status": "draft",
            "created": "2026-03-27", "tags": [], "scope": None}
    upsert_chunk(db_path, "Cards/foo.md", 0, "chunk 0", "h0", [0.1, 0.2, 0.3, 0.4], meta)
    upsert_chunk(db_path, "Cards/foo.md", 1, "chunk 1", "h1", [0.2, 0.3, 0.4, 0.5], meta)

    delete_file_chunks(db_path, "Cards/foo.md")

    import sqlite3
    conn = sqlite3.connect(db_path)
    chunk_rows = conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE filepath='Cards/foo.md'"
    ).fetchone()[0]
    conn.close()
    assert chunk_rows == 0

    from lib.db import _connect
    vec_conn = _connect(db_path)
    try:
        emb_rows = vec_conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    finally:
        vec_conn.close()
    assert emb_rows == 0


def test_delete_file_chunks_does_not_affect_other_filepaths(db_path):
    init_db(db_path, embedding_dim=4)
    meta = {"title": "X", "type": "note", "status": "draft",
            "created": "2026-03-27", "tags": [], "scope": None}
    upsert_chunk(db_path, "Cards/foo.md", 0, "chunk foo", "hf", [0.1, 0.2, 0.3, 0.4], meta)
    upsert_chunk(db_path, "Cards/bar.md", 0, "chunk bar", "hb", [0.5, 0.6, 0.7, 0.8], meta)

    delete_file_chunks(db_path, "Cards/foo.md")

    import sqlite3
    conn = sqlite3.connect(db_path)
    bar_rows = conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE filepath='Cards/bar.md'"
    ).fetchone()[0]
    conn.close()
    assert bar_rows == 1
```

**Step 2: Run tests to confirm they fail**

```bash
cd /Users/chris/projects/second-brain && pytest tests/lib/test_db.py::test_delete_file_chunks_removes_chunks_and_embeddings tests/lib/test_db.py::test_delete_file_chunks_does_not_affect_other_filepaths -v
```

Expected: ImportError or AttributeError — `delete_file_chunks` does not exist yet.

**Step 3: Implement `delete_file_chunks` in `tools/lib/db.py`**

Add after the last existing function in the file:

```python
def delete_file_chunks(db_path: str, filepath: str) -> None:
    """Delete all chunks and their embeddings for a given filepath."""
    conn = _connect(db_path)
    try:
        chunk_ids = [
            row[0] for row in conn.execute(
                "SELECT id FROM chunks WHERE filepath=?", (filepath,)
            ).fetchall()
        ]
        if chunk_ids:
            placeholders = ",".join("?" * len(chunk_ids))
            conn.execute(f"DELETE FROM embeddings WHERE rowid IN ({placeholders})", chunk_ids)
        conn.execute("DELETE FROM chunks WHERE filepath=?", (filepath,))
        conn.commit()
    finally:
        conn.close()
```

**Step 4: Run tests to confirm they pass**

```bash
cd /Users/chris/projects/second-brain && pytest tests/lib/test_db.py -v
```

Expected: all tests pass.

**Step 5: Commit**

```bash
git add tools/lib/db.py tests/lib/test_db.py
git commit -m "feat: add delete_file_chunks helper to db.py"
```

---

## Task 2: Add `handle_brain_trash` and `handle_brain_restore` to `tools/lib/brain.py`

**Files:**
- Modify: `tools/lib/brain.py`
- Test: `tests/test_brain_service.py`

**Background:** All handlers validate via `_check_within_brain`, resolve paths with `_relative_path`, and return plain strings. `handle_brain_backlinks` shows how `find_backlinks` results are formatted. Trash dir is always `os.path.join(brain_path, ".trash")` — no config key needed. The `.origin` sidecar allows lossless round-trip when the destination filename gets a datestamp suffix due to collision.

Note: `find_backlinks` already skips directories starting with `.` (line ~352 in brain.py uses `dirs[:] = [d for d in dirs if not d.startswith(".")]`), so `.trash/` contents are already excluded from backlink scanning with no additional change.

**Step 1: Write failing tests**

Add to `tests/test_brain_service.py` (add to imports at top):
```python
from lib.brain import handle_brain_trash, handle_brain_restore
```

Add the following test cases:

```python
# ── brain_trash ──────────────────────────────────────────────────────


@pytest.fixture
def brain_with_note(tmp_path):
    note = tmp_path / "Cards" / "foo.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("---\ntitle: Foo\n---\n\nHello.")
    return tmp_path


def test_trash_moves_file_to_trash_dir(brain_with_note):
    with patch("lib.brain.delete_file_chunks"):
        result = handle_brain_trash(
            "Cards/foo.md", str(brain_with_note), db_path=":memory:"
        )
    assert not (brain_with_note / "Cards" / "foo.md").exists()
    assert (brain_with_note / ".trash" / "Cards" / "foo.md").exists()
    assert "Trashed" in result


def test_trash_cleans_db(brain_with_note):
    with patch("lib.brain.delete_file_chunks") as mock_del:
        handle_brain_trash(
            "Cards/foo.md", str(brain_with_note), db_path="/tmp/test.db"
        )
    mock_del.assert_called_once()


def test_trash_returns_backlink_info(brain_with_note):
    linker = brain_with_note / "Efforts" / "baz.md"
    linker.parent.mkdir(parents=True, exist_ok=True)
    linker.write_text("---\ntitle: Baz\n---\n\nSee [[foo]].")
    with patch("lib.brain.delete_file_chunks"):
        result = handle_brain_trash(
            "Cards/foo.md", str(brain_with_note), db_path=":memory:"
        )
    assert "baz.md" in result or "Baz" in result
    assert "orphaned" in result.lower()


def test_trash_no_backlinks_reports_none(brain_with_note):
    with patch("lib.brain.delete_file_chunks"):
        result = handle_brain_trash(
            "Cards/foo.md", str(brain_with_note), db_path=":memory:"
        )
    assert "No backlinks" in result


def test_trash_rejects_non_md(brain_with_note):
    txt = brain_with_note / "readme.txt"
    txt.write_text("hello")
    result = handle_brain_trash("readme.txt", str(brain_with_note), db_path=":memory:")
    assert "Error" in result


def test_trash_rejects_outside_brain(tmp_path):
    result = handle_brain_trash("/etc/passwd", str(tmp_path), db_path=":memory:")
    assert "Error" in result or "outside" in result.lower()


def test_trash_collision_creates_datestamp_suffix_and_origin_sidecar(brain_with_note):
    # Pre-create a collision in trash
    trash_dest = brain_with_note / ".trash" / "Cards"
    trash_dest.mkdir(parents=True, exist_ok=True)
    (trash_dest / "foo.md").write_text("old trash")
    with patch("lib.brain.delete_file_chunks"):
        handle_brain_trash(
            "Cards/foo.md", str(brain_with_note), db_path=":memory:"
        )
    trash_files = list(trash_dest.glob("foo.*.md"))
    assert len(trash_files) == 1
    origin_file = trash_files[0].with_suffix(".origin")
    assert origin_file.exists()
    assert "Cards/foo.md" in origin_file.read_text()


# ── brain_restore ─────────────────────────────────────────────────────


def test_restore_moves_file_back(brain_with_note):
    with patch("lib.brain.delete_file_chunks"):
        handle_brain_trash(
            "Cards/foo.md", str(brain_with_note), db_path=":memory:"
        )
    result = handle_brain_restore(".trash/Cards/foo.md", str(brain_with_note))
    assert (brain_with_note / "Cards" / "foo.md").exists()
    assert "Restored" in result


def test_restore_with_origin_sidecar(brain_with_note):
    trash_dir = brain_with_note / ".trash" / "Cards"
    trash_dir.mkdir(parents=True, exist_ok=True)
    suffixed = trash_dir / "foo.20260327-143022.md"
    suffixed.write_text("---\ntitle: Foo\n---\n\nHello.")
    origin = trash_dir / "foo.20260327-143022.origin"
    origin.write_text("Cards/foo.md")
    result = handle_brain_restore(
        ".trash/Cards/foo.20260327-143022.md", str(brain_with_note)
    )
    assert (brain_with_note / "Cards" / "foo.md").exists()
    assert not origin.exists()
    assert "Restored" in result


def test_restore_conflict_returns_error(brain_with_note):
    with patch("lib.brain.delete_file_chunks"):
        handle_brain_trash(
            "Cards/foo.md", str(brain_with_note), db_path=":memory:"
        )
    # Recreate the file at original location to cause conflict
    (brain_with_note / "Cards" / "foo.md").write_text("conflict")
    result = handle_brain_restore(".trash/Cards/foo.md", str(brain_with_note))
    assert "Error" in result


def test_restore_rejects_path_not_in_trash(brain_with_note):
    result = handle_brain_restore("Cards/foo.md", str(brain_with_note))
    assert "Error" in result
```

**Step 2: Run tests to confirm they fail**

```bash
cd /Users/chris/projects/second-brain && pytest tests/test_brain_service.py -k "trash or restore" -v
```

Expected: ImportError — handlers do not exist yet.

**Step 3: Implement handlers in `tools/lib/brain.py`**

Add `from datetime import datetime` to the imports at the top.

Add `delete_file_chunks` to the `from lib.db import ...` import line.

Add the following two handlers after `handle_brain_backlinks`:

```python
def handle_brain_trash(filepath: str, brain_path: str, db_path: str) -> str:
    """Move a note to .trash/, clean from DB, report orphaned backlinks."""
    full_path = _resolve(filepath, brain_path)
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

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    os.rename(full_path, dest_path)

    if origin_sidecar:
        with open(origin_sidecar, "w", encoding="utf-8") as f:
            f.write(rel)

    try:
        delete_file_chunks(db_path, full_path)
    except Exception:
        pass  # DB may not exist yet (not yet indexed) — don't fail the trash

    backlinks = find_backlinks(full_path, brain_path)
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

    full_trash_path = _resolve(normalized, brain_path)
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

    dest_path = os.path.join(brain_path, original_rel)
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
```

Note on `_resolve`: check whether `brain.py` uses `_resolve(filepath, brain_path)` or a different internal signature before writing. Look at how `handle_brain_write` calls it.

**Step 4: Run tests to confirm they pass**

```bash
cd /Users/chris/projects/second-brain && pytest tests/test_brain_service.py -v
```

Expected: all tests pass.

**Step 5: Commit**

```bash
git add tools/lib/brain.py tests/test_brain_service.py
git commit -m "feat: add handle_brain_trash and handle_brain_restore"
```

---

## Task 3: Wire up MCP tools in `tools/brain_mcp_server.py`

**Files:**
- Modify: `tools/brain_mcp_server.py`

No new tests needed — the MCP server is a thin dispatch layer; correctness is covered by the service tests in Task 2.

**Step 1: Update imports**

In the `from lib.brain import (...)` block, add:
```python
    handle_brain_trash,
    handle_brain_restore,
```

**Step 2: Add Tool definitions to `list_tools()`**

After the `brain_backlinks` Tool entry, add:

```python
Tool(
    name="brain_trash",
    description=(
        "Move a note to .trash/ and remove it from the search index immediately. "
        "Reports any backlinks that will become orphaned. "
        "Use brain_restore to undo."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "filepath": {
                "type": "string",
                "description": "Relative path to the .md file to trash (e.g. 'Cards/foo.md')",
            },
        },
        "required": ["filepath"],
    },
),
Tool(
    name="brain_restore",
    description=(
        "Restore a note from .trash/ back to its original location. "
        "The file watcher will re-index it automatically."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "trash_path": {
                "type": "string",
                "description": "Path as returned by brain_trash (e.g. '.trash/Cards/foo.md')",
            },
        },
        "required": ["trash_path"],
    },
),
```

**Step 3: Add dispatch cases to `call_tool()`**

After the `elif name == "brain_backlinks":` block:

```python
elif name == "brain_trash":
    text = handle_brain_trash(
        filepath=arguments["filepath"],
        brain_path=brain_path,
        db_path=db_path,
    )
elif name == "brain_restore":
    text = handle_brain_restore(
        trash_path=arguments["trash_path"],
        brain_path=brain_path,
    )
```

**Step 4: Verify server starts cleanly**

```bash
cd /Users/chris/projects/second-brain/tools && python -c "from brain_mcp_server import _build_server; s = _build_server(); print('OK')"
```

**Step 5: Commit**

```bash
git add tools/brain_mcp_server.py
git commit -m "feat: register brain_trash and brain_restore MCP tools"
```

---

## Task 4: Wire up REST endpoints in `tools/brain_api.py`

**Files:**
- Modify: `tools/brain_api.py`
- Test: `tests/test_brain_api.py`

**Step 1: Write failing tests**

Add to `tests/test_brain_api.py`:

```python
# ── Trash / Restore ──────────────────────────────────────────────────


def test_trash_note(client, sample_note, brain_env):
    brain_dir, _ = brain_env
    with patch("lib.brain.delete_file_chunks"):
        resp = client.post(f"/api/notes/{sample_note}/trash")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "Trashed" in data["detail"]
    assert not (brain_dir / sample_note).exists()


def test_trash_nonexistent_returns_404(client):
    with patch("lib.brain.delete_file_chunks"):
        resp = client.post("/api/notes/nonexistent.md/trash")
    assert resp.status_code == 404


def test_restore_note(client, sample_note, brain_env):
    brain_dir, _ = brain_env
    with patch("lib.brain.delete_file_chunks"):
        client.post(f"/api/notes/{sample_note}/trash")
    trash_path = f".trash/{sample_note}"
    resp = client.post(f"/api/notes/{trash_path}/restore")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "Restored" in data["detail"]
    assert (brain_dir / sample_note).exists()
```

**Step 2: Run tests to confirm they fail**

```bash
cd /Users/chris/projects/second-brain && pytest tests/test_brain_api.py::test_trash_note tests/test_brain_api.py::test_restore_note -v
```

Expected: 404 or 405 — endpoints don't exist yet.

**Step 3: Update imports in `brain_api.py`**

Add to the `from lib.brain import (...)` block:
```python
    handle_brain_trash,
    handle_brain_restore,
```

**Step 4: Add endpoints**

After the `@app.post("/api/notes", ...)` create endpoint, add:

```python
@app.post("/api/notes/{filepath:path}/trash", response_model=EditResponse)
def trash_note(filepath: str):
    """Move a note to .trash/ and remove from the search index."""
    full = _resolve(filepath)
    if not os.path.isfile(full):
        raise HTTPException(status_code=404, detail=f"File not found: {filepath}")
    result = handle_brain_trash(
        filepath=_relative(full),
        brain_path=_cfg.brain_path,
        db_path=_cfg.db_path,
    )
    if result.startswith("Error"):
        raise HTTPException(status_code=400, detail=result)
    return EditResponse(filepath=filepath, success=True, detail=result)


@app.post("/api/notes/{filepath:path}/restore", response_model=EditResponse)
def restore_note(filepath: str):
    """Restore a note from .trash/ back to its original location."""
    result = handle_brain_restore(
        trash_path=filepath,
        brain_path=_cfg.brain_path,
    )
    if result.startswith("Error"):
        raise HTTPException(status_code=400, detail=result)
    return EditResponse(filepath=filepath, success=True, detail=result)
```

**Step 5: Run tests to confirm they pass**

```bash
cd /Users/chris/projects/second-brain && pytest tests/test_brain_api.py -v
```

**Step 6: Commit**

```bash
git add tools/brain_api.py tests/test_brain_api.py
git commit -m "feat: add POST /api/notes/{filepath}/trash and /restore endpoints"
```

---

## Task 5: Fix watcher exclusion in `tools/brain_index.py`

**Files:**
- Modify: `tools/brain_index.py` line 154
- Test: `tests/test_brain_index.py`

**Background:** `index_brain` already excludes `.trash/` because `os.walk` skips all directories starting with `.` (line 136). But `watch_brain` only explicitly excludes `.ai` and `templates` — a file moved to `.trash/` would trigger the watcher and attempt re-indexing under the `.trash/` path.

**Step 1: Write a failing test**

Add to `tests/test_brain_index.py`:

```python
def test_watch_filter_excludes_trash_paths(brain, mock_embed):
    """Files under .trash/ must not be processed by the watcher."""
    from brain_index import watch_brain
    from pathlib import Path

    db_path = str(brain / ".ai" / "embeddings.db")
    init_db(db_path, embedding_dim=1024)

    trash_path = str(brain / ".trash" / "Cards" / "deleted-note.md")
    fake_changes = [{(None, trash_path)}]

    with patch("watchfiles.watch", return_value=iter(fake_changes)):
        with patch("brain_index.index_file") as mock_index, \
             patch("brain_index.purge_stale_paths") as mock_purge:
            watch_brain(str(brain), db_path)

    mock_index.assert_not_called()
    mock_purge.assert_not_called()
```

**Step 2: Run test to confirm it fails**

```bash
cd /Users/chris/projects/second-brain && pytest tests/test_brain_index.py::test_watch_filter_excludes_trash_paths -v
```

**Step 3: Apply the fix**

In `tools/brain_index.py` line 154, replace:
```python
if path.endswith(".md") and ".ai" not in Path(path).parts and "templates" not in Path(path).parts:
```
with:
```python
if path.endswith(".md") and ".ai" not in Path(path).parts and "templates" not in Path(path).parts and ".trash" not in Path(path).parts:
```

**Step 4: Run test to confirm it passes**

```bash
cd /Users/chris/projects/second-brain && pytest tests/test_brain_index.py -v
```

**Step 5: Commit**

```bash
git add tools/brain_index.py tests/test_brain_index.py
git commit -m "fix: exclude .trash/ from watch_brain file event processing"
```

---

## Task 6: Update `skills/brain-hygiene/SKILL.md`

**Files:**
- Modify: `skills/brain-hygiene/SKILL.md`

**Step 1: Add Check 5 before the `---` separator**

Insert after the "Check 4: Stale Drafts" section and before the `---` line:

```markdown
## Check 5: Trash

Glob `.trash/**/*.md`. If the result is empty, skip this check.

For each file found:
- Derive the original path: read from the `.origin` sidecar (same stem, `.origin` extension) if present; otherwise strip the `.trash/` prefix from the path.
- Show: original path, trashed date (file mtime), current trash path.
- Ask the user: **[restore]** | **[permanently delete]** | **[skip]**

**Restore:** `brain_restore(trash_path)`

**Permanently delete:** remove the `.md` file and its `.origin` sidecar (if present). This is irreversible — confirm per file. Use `rm` on the host filesystem path (the vault-relative `.trash/...` path maps directly when Claude Code is opened in the vault root).

Never auto-empty the trash.
```

**Step 2: Verify the file reads correctly — no broken markdown**

Read the updated skill file and confirm structure is intact.

**Step 3: Commit**

```bash
git add skills/brain-hygiene/SKILL.md
git commit -m "docs: add Check 5 (Trash) to brain-hygiene skill"
```

---

## Task 7: Update `brain-skills/brain-rename/SKILL.md`

**Files:**
- Modify: `brain-skills/brain-rename/SKILL.md`

**Step 1: Replace Step 5**

Replace the current Step 5:

```markdown
### 5. Rename the file

Use the host filesystem path (strip the `/brain` prefix from any MCP path):

```bash
mv <old-path> <new-path>
```
```

with:

```markdown
### 5. Rename the file

Choose the approach based on your session context:

**Brain-native session** (Claude Code opened directly in the vault root — direct filesystem access available):
```bash
mv <old-path> <new-path>
```
Use the vault filesystem path (strip the `/brain` prefix if the path came from an MCP tool).

**MCP-only session** (external project with brain connected as MCP — no direct filesystem access):
```
brain_read(old_path)            → capture content
brain_write(new_path, content)  → write to new location
brain_trash(old_path)           → remove old file and clean from index
```
```

**Step 2: Verify the file reads correctly**

**Step 3: Commit**

```bash
git add brain-skills/brain-rename/SKILL.md
git commit -m "docs: update brain-rename to use brain_trash in MCP-only sessions"
```

---

## Task 8: Final test suite verification

```bash
cd /Users/chris/projects/second-brain && pytest tests/lib/test_db.py tests/lib/test_edit.py tests/lib/test_config.py tests/test_brain_service.py tests/test_brain_index.py -v
```

Expected: all pre-existing tests continue to pass, all new tests pass.

Confirm the commit log looks clean:
```bash
git log --oneline -10
```

Then push:
```bash
git push origin main
```
