# Security and Bug Fixes Implementation Plan

> **Status (2026-03-29): Tasks 1–12 COMPLETE. Task 13 partially done — see note below.**

**Goal:** Fix all Critical/High/Medium/Low issues identified in the full codebase review, with tests written before each fix.

**Architecture:** Work in strict priority order: Critical → High → Medium → Low. Each bug gets a failing test first, then the minimal fix to make it pass. Significant refactors (backlinks deduplication, list_templates, module-level Config) come after their surrounding code is test-covered.

**Tech Stack:** Python 3.12, pytest, FastAPI, sqlite3/sqlite-vec, subprocess (zk), watchfiles

---

## CRITICAL

### Task 1: Test + fix `init_db` SQL injection via executescript f-string

**Files:**
- Modify: `tools/lib/db.py:50–73`
- Test: `tests/lib/test_db.py`

**Background:** `init_db` uses `executescript(f"...INSERT OR IGNORE INTO meta VALUES ('embedding_dim', '{embedding_dim}')...")`. `executescript` does not support parameterised queries, but the INSERT can be split out to a regular `conn.execute` call which does. The DDL line `float[{embedding_dim}]` must remain an f-string (no alternative) — defend it by validating `embedding_dim` is a positive int before use.

**Step 1: Write the failing tests**

Add to `tests/lib/test_db.py`:

```python
def test_init_db_rejects_non_positive_dim(db_path):
    with pytest.raises(ValueError, match="positive integer"):
        init_db(db_path, embedding_dim=0)

def test_init_db_rejects_negative_dim(db_path):
    with pytest.raises(ValueError, match="positive integer"):
        init_db(db_path, embedding_dim=-1)

def test_init_db_meta_row_uses_param_not_fstring(db_path):
    """meta INSERT should go through parameterised execute, not executescript."""
    init_db(db_path, embedding_dim=4)
    import sqlite3
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT value FROM meta WHERE key='embedding_dim'").fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "4"
```

**Step 2: Run to confirm they fail**
```bash
cd /Users/chris/projects/second-brain && pytest tests/lib/test_db.py::test_init_db_rejects_non_positive_dim tests/lib/test_db.py::test_init_db_rejects_negative_dim -v
```
Expected: FAIL (no ValueError raised)

**Step 3: Fix `tools/lib/db.py`**

In `init_db`, before the `conn = _connect(db_path)` line, add:
```python
if not isinstance(embedding_dim, int) or embedding_dim <= 0:
    raise ValueError(f"embedding_dim must be a positive integer, got {embedding_dim!r}")
```

Then split the `executescript` — remove the `INSERT OR IGNORE INTO meta VALUES` line from the f-string, and add it as a separate parameterised call after `executescript`:

```python
conn.executescript(f"""
    CREATE TABLE IF NOT EXISTS chunks (
        id INTEGER PRIMARY KEY,
        filepath TEXT NOT NULL,
        chunk_index INTEGER NOT NULL,
        content TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        title TEXT,
        type TEXT,
        status TEXT,
        created TEXT,
        tags TEXT,
        scope TEXT,
        UNIQUE(filepath, chunk_index)
    );
    CREATE VIRTUAL TABLE IF NOT EXISTS embeddings USING vec0(
        embedding float[{embedding_dim}]
    );
    CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT
    );
""")
conn.execute(
    "INSERT OR IGNORE INTO meta VALUES (?, ?)", ("embedding_dim", str(embedding_dim))
)
```

**Step 4: Run all db tests**
```bash
pytest tests/lib/test_db.py -v
```
Expected: all PASS

**Step 5: Commit**
```bash
git add tools/lib/db.py tests/lib/test_db.py
git commit -m "fix: validate embedding_dim and move meta INSERT to parameterised query"
```

---

### Task 2: Test + fix orphaned embeddings — stale chunks and shrinking files

**Files:**
- Modify: `tools/brain_index.py:42–55` (index_file) and `tools/brain_index.py:67–80` (purge_stale_paths)
- Test: `tests/test_brain_index.py`

**Background:** Two related bugs:
1. `index_file` only upserts chunks at current indices — if a note shrinks from 3 chunks to 1, chunks at index 1 and 2 are never deleted.
2. `purge_stale_paths` deletes from `chunks` but leaves orphaned rows in the `embeddings` virtual table (no FK cascade on sqlite-vec). The embeddings rows must be deleted explicitly before deleting chunks.

**Step 1: Write the failing tests**

Add to `tests/test_brain_index.py`:

```python
import sqlite3
from lib.db import init_db, upsert_chunk


def test_index_file_prunes_excess_chunks_when_file_shrinks(brain, mock_embed):
    """When a note shrinks, chunks beyond the new length must be removed."""
    db_path = str(brain / ".ai" / "embeddings.db")
    init_db(db_path, embedding_dim=1024)

    filepath = str(brain / "test-note.md")

    # Manually insert 3 chunks to simulate a previously-longer note
    for i in range(3):
        upsert_chunk(db_path, filepath, i, f"chunk {i}", f"hash{i}", [0.1]*1024,
                     {"title": "T", "type": "note", "status": "current",
                      "created": "2026-03-16", "tags": [], "scope": None})

    # Re-index the actual file (1 chunk)
    index_file(filepath, db_path)

    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT chunk_index FROM chunks WHERE filepath=?", (filepath,)).fetchall()
    conn.close()
    assert len(rows) == 1, f"expected 1 chunk, got {len(rows)}"
    assert rows[0][0] == 0


def test_purge_stale_paths_also_deletes_embeddings(brain, mock_embed):
    """Deleting stale chunk rows must also remove the corresponding embeddings rows."""
    db_path = str(brain / ".ai" / "embeddings.db")
    init_db(db_path, embedding_dim=1024)

    # Index a note so it has a chunk + embedding row
    filepath = str(brain / "test-note.md")
    index_file(filepath, db_path)

    # Remove the file from disk
    (brain / "test-note.md").unlink()

    from brain_index import purge_stale_paths
    purge_stale_paths(db_path)

    from lib.db import _connect
    conn = _connect(db_path)
    chunk_rows = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    embedding_rows = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    conn.close()
    assert chunk_rows == 0
    assert embedding_rows == 0, f"orphaned embeddings remain: {embedding_rows}"
```

**Step 2: Run to confirm they fail**
```bash
pytest tests/test_brain_index.py::test_index_file_prunes_excess_chunks_when_file_shrinks tests/test_brain_index.py::test_purge_stale_paths_also_deletes_embeddings -v
```
Expected: FAIL

**Step 3: Fix `tools/brain_index.py`**

In `index_file`, after the chunk loop, add pruning of now-excess chunks:

```python
    # Prune chunks whose index is beyond the current chunk count (file shrank)
    conn = sqlite3.connect(db_path)
    try:
        stale_ids = [
            row[0] for row in conn.execute(
                "SELECT id FROM chunks WHERE filepath=? AND chunk_index >= ?",
                (filepath, len(chunks))
            ).fetchall()
        ]
        if stale_ids:
            from lib.db import _connect as _vec_connect
            vec_conn = _vec_connect(db_path)
            try:
                placeholders = ",".join("?" * len(stale_ids))
                vec_conn.execute(f"DELETE FROM embeddings WHERE rowid IN ({placeholders})", stale_ids)
                vec_conn.execute(f"DELETE FROM chunks WHERE id IN ({placeholders})", stale_ids)
                vec_conn.commit()
            finally:
                vec_conn.close()
    finally:
        conn.close()
```

In `purge_stale_paths`, before the `DELETE FROM chunks` line, collect chunk ids and delete from embeddings first:

```python
def purge_stale_paths(db_path: str) -> None:
    """Remove DB entries for filepaths that no longer exist on disk."""
    from lib.db import _connect as _vec_connect
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT DISTINCT filepath FROM chunks").fetchall()
        stale = [fp for (fp,) in rows if not os.path.isfile(fp)]
        for fp in stale:
            stale_ids = [
                row[0] for row in conn.execute(
                    "SELECT id FROM chunks WHERE filepath=?", (fp,)
                ).fetchall()
            ]
            if stale_ids:
                vec_conn = _vec_connect(db_path)
                try:
                    placeholders = ",".join("?" * len(stale_ids))
                    vec_conn.execute(f"DELETE FROM embeddings WHERE rowid IN ({placeholders})", stale_ids)
                    vec_conn.execute("DELETE FROM chunks WHERE filepath=?", (fp,))
                    vec_conn.commit()
                finally:
                    vec_conn.close()
            print(f"Purged stale: {fp}", file=sys.stderr)
        # outer conn no longer needs to commit — vec_conn handled it
    finally:
        conn.close()
```

**Step 4: Run all index tests**
```bash
pytest tests/test_brain_index.py -v
```
Expected: all PASS

**Step 5: Commit**
```bash
git add tools/brain_index.py tests/test_brain_index.py
git commit -m "fix: prune excess chunks on shrink and delete embeddings on purge"
```

---

## HIGH

### Task 3: Test + fix input validation on `handle_brain_query` params

**Files:**
- Modify: `tools/lib/brain.py:109–128`
- Test: `tests/test_brain_service.py`

**Background:** `tag`, `status`, and `note_type` are passed to `zk`'s `--match` argument as `f"status:{value}"`. While not shell-injectable (list-form subprocess), arbitrary values could confuse zk's query parser. Restrict to `[a-zA-Z0-9\-_]`.

**Step 1: Write the failing tests**

Add to `tests/test_brain_service.py`:

```python
def test_brain_query_rejects_invalid_tag(tmp_path):
    result = handle_brain_query(tag="foo; bar", status=None, note_type=None, brain_path=str(tmp_path))
    assert "invalid" in result.lower()

def test_brain_query_rejects_invalid_status(tmp_path):
    result = handle_brain_query(tag=None, status="draft\ninjected", note_type=None, brain_path=str(tmp_path))
    assert "invalid" in result.lower()

def test_brain_query_rejects_invalid_type(tmp_path):
    result = handle_brain_query(tag=None, status=None, note_type="../etc/passwd", brain_path=str(tmp_path))
    assert "invalid" in result.lower()

def test_brain_query_accepts_valid_params(tmp_path):
    # Should not fail on input validation (may fail on zk not found — that's fine)
    result = handle_brain_query(tag="my-effort", status="draft", note_type="discovery", brain_path=str(tmp_path))
    assert "invalid" not in result.lower()
```

Note: `handle_brain_query` needs to be added to the imports at the top of `test_brain_service.py`.

**Step 2: Run to confirm they fail**
```bash
pytest tests/test_brain_service.py::test_brain_query_rejects_invalid_tag -v
```
Expected: FAIL (no validation error returned)

**Step 3: Fix `tools/lib/brain.py`**

Add a helper just above `handle_brain_query`:

```python
_SAFE_PARAM_RE = re.compile(r'^[a-zA-Z0-9\-_]+$')

def _validate_query_param(name: str, value: str) -> Optional[str]:
    """Return an error string if value contains unsafe characters, else None."""
    if not _SAFE_PARAM_RE.match(value):
        return f"Invalid {name}: must contain only letters, digits, hyphens and underscores"
    return None
```

At the top of `handle_brain_query`, before building `cmd`:

```python
def handle_brain_query(tag, status, note_type, brain_path):
    for name, value in [("tag", tag), ("status", status), ("type", note_type)]:
        if value is not None:
            if err := _validate_query_param(name, value):
                return err
    cmd = ["zk", "list", ...]
```

**Step 4: Run tests**
```bash
pytest tests/test_brain_service.py -v -k "query"
```
Expected: all PASS

**Step 5: Commit**
```bash
git add tools/lib/brain.py tests/test_brain_service.py
git commit -m "fix: validate brain_query params against safe character allowlist"
```

---

### Task 4: Test + fix ReDoS in `find_replace` with `regex=True`

**Files:**
- Modify: `tools/lib/edit.py:118–132`
- Test: `tests/lib/test_edit.py`

**Background:** `re.subn(find, replace, text)` with a caller-controlled pattern can catastrophically backtrack. Compile the pattern first to catch `re.error`, and return a clean error tuple rather than raising.

**Step 1: Write the failing tests**

Add to `tests/lib/test_edit.py`:

```python
def test_find_replace_invalid_regex_returns_error():
    """Invalid regex must return an error, not raise."""
    text, n = find_replace("some text", r"(invalid[regex", "replace", regex=True)
    assert n == -1  # sentinel for error
    # text should contain the error message
    assert "Invalid regex" in text

def test_find_replace_valid_regex_still_works():
    text, n = find_replace("hello world", r"w\w+", "there", regex=True)
    assert n == 1
    assert text == "hello there"
```

**Step 2: Run to confirm first test fails**
```bash
pytest tests/lib/test_edit.py::test_find_replace_invalid_regex_returns_error -v
```
Expected: FAIL (raises `re.error` instead of returning error tuple)

**Step 3: Fix `tools/lib/edit.py`**

Replace the `if regex:` branch in `find_replace`:

```python
def find_replace(text: str, find: str, replace: str, *, regex: bool = False, count: int = 0) -> tuple[str, int]:
    """Find and replace text. Returns (new_text, num_replacements).

    count=0 means replace all occurrences.
    On invalid regex, returns (error_message, -1).
    """
    if regex:
        try:
            pattern = re.compile(find)
        except re.error as e:
            return f"Invalid regex: {e}", -1
        new_text, n = pattern.subn(replace, text, count=count or 0)
    else:
        if count == 0:
            new_text = text.replace(find, replace)
            n = text.count(find)
        else:
            new_text = text.replace(find, replace, count)
            n = min(text.count(find), count)
    return new_text, n
```

Also update `handle_brain_edit` in `tools/lib/brain.py` and `edit_note` in `tools/brain_api.py` to check for `n == -1` and surface the error:

In `handle_brain_edit` (brain.py), after the `find_replace` call:
```python
text, n = find_replace(...)
if n == -1:
    return text  # text is the error message
detail = f"Replaced {n} occurrence(s)"
```

In `edit_note` (brain_api.py), after the `find_replace` call:
```python
text, n = find_replace(...)
if n == -1:
    raise HTTPException(400, text)  # text is the error message
detail = f"Replaced {n} occurrence(s)"
```

**Step 4: Run all edit tests**
```bash
pytest tests/lib/test_edit.py tests/test_brain_service.py -v
```
Expected: all PASS

**Step 5: Commit**
```bash
git add tools/lib/edit.py tools/lib/brain.py tools/brain_api.py tests/lib/test_edit.py
git commit -m "fix: catch re.error in find_replace and return error tuple instead of raising"
```

---

### Task 5: Fix CORS to not be wide open

**Files:**
- Modify: `tools/lib/config.py`
- Modify: `tools/brain_api.py:47–52`
- Test: `tests/lib/test_config.py`

**Background:** `allow_origins=["*"]` on a read/write vault API binding to `0.0.0.0`. Should default to localhost only and be configurable via env var.

**Step 1: Read `tools/lib/config.py` and `tests/lib/test_config.py` first** (done before writing tests)

**Step 2: Write the failing test**

Add to `tests/lib/test_config.py`:

```python
import os
import importlib

def test_config_cors_defaults_to_localhost(monkeypatch):
    monkeypatch.delenv("BRAIN_API_CORS_ORIGINS", raising=False)
    import lib.config
    importlib.reload(lib.config)
    cfg = lib.config.Config()
    assert cfg.cors_origins == ["http://localhost:7779", "http://127.0.0.1:7779"]

def test_config_cors_from_env(monkeypatch):
    monkeypatch.setenv("BRAIN_API_CORS_ORIGINS", "http://localhost:3000,http://localhost:8080")
    import lib.config
    importlib.reload(lib.config)
    cfg = lib.config.Config()
    assert cfg.cors_origins == ["http://localhost:3000", "http://localhost:8080"]
```

**Step 3: Run to confirm they fail**
```bash
pytest tests/lib/test_config.py -v -k "cors"
```
Expected: FAIL (AttributeError — no `cors_origins` on Config)

**Step 4: Fix `tools/lib/config.py`**

Read the file first, then add to the `Config` class:

```python
@property
def cors_origins(self) -> list[str]:
    raw = os.environ.get("BRAIN_API_CORS_ORIGINS", "")
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    return ["http://localhost:7779", "http://127.0.0.1:7779"]
```

**Step 5: Fix `tools/brain_api.py`**

Replace:
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
```
With:
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cfg.cors_origins,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)
```

**Step 6: Run tests**
```bash
pytest tests/lib/test_config.py -v
```
Expected: all PASS

**Step 7: Commit**
```bash
git add tools/lib/config.py tools/brain_api.py tests/lib/test_config.py
git commit -m "fix: restrict CORS to localhost by default, configurable via BRAIN_API_CORS_ORIGINS"
```

---

### Task 6: Test + fix `get_embedding` calling `sys.exit(1)` from library code

**Files:**
- Modify: `tools/lib/embeddings.py`
- Modify: `tools/brain_index.py` (catch new exception in CLI callers)
- Modify: `tools/lib/brain.py` (handle_brain_search, handle_brain_related)
- Modify: `tools/brain_api.py` (search_notes, related_notes)
- Test: `tests/test_brain_service.py`, `tests/test_brain_index.py`

**Background:** `sys.exit(1)` inside `get_embedding` kills the entire uvicorn process on a transient model outage. The fix: define an `EmbeddingError` in `embeddings.py`, raise it instead of exiting, and let each call site decide whether to exit (CLI) or return HTTP 503 (API).

**Step 1: Write the failing tests**

Add to `tests/test_brain_service.py`:

```python
from unittest.mock import patch
from lib.embeddings import EmbeddingError  # will fail until we create it

def test_handle_brain_search_returns_error_on_embedding_failure(tmp_path):
    """API-context search must not call sys.exit on embedding failure."""
    with patch("lib.brain.get_embedding", side_effect=EmbeddingError("model not found")):
        result = handle_brain_search("test query", 5, ":memory:")
    assert "error" in result.lower() or "embedding" in result.lower()
```

Add to `tests/test_brain_index.py`:

```python
from lib.embeddings import EmbeddingError

def test_index_file_raises_on_embedding_error(brain, monkeypatch):
    """index_file should propagate EmbeddingError, not swallow or exit."""
    db_path = str(brain / ".ai" / "embeddings.db")
    from lib.db import init_db
    init_db(db_path, embedding_dim=1024)

    monkeypatch.setattr("brain_index.get_embedding", lambda t: (_ for _ in ()).throw(EmbeddingError("no model")))

    with pytest.raises(EmbeddingError):
        index_file(str(brain / "test-note.md"), db_path)
```

**Step 2: Run to confirm they fail**
```bash
pytest tests/test_brain_service.py::test_handle_brain_search_returns_error_on_embedding_failure -v
```
Expected: FAIL (ImportError — EmbeddingError doesn't exist yet)

**Step 3: Fix `tools/lib/embeddings.py`**

Add the exception class and replace `sys.exit(1)` calls:

```python
class EmbeddingError(RuntimeError):
    """Raised when the embedding service is unavailable or misconfigured."""
    pass


def get_embedding(text: str, max_chars: int = 1500) -> list[float]:
    try:
        response = _get_client().embeddings.create(
            input=text[:max_chars],
            model=_cfg.embedding_model,
        )
        return response.data[0].embedding
    except InternalServerError as e:
        if "too large" in str(e) and max_chars > 100:
            print(f"Warning: input too large, retrying with {max_chars // 2} chars", file=sys.stderr)
            return get_embedding(text, max_chars // 2)
        raise
    except NotFoundError:
        raise EmbeddingError(
            f"Embedding model '{_cfg.embedding_model}' not found at {_cfg.embedding_base_url}. "
            f"Check that the model is loaded and EMBEDDING_MODEL is set correctly."
        )
    except APIConnectionError:
        raise EmbeddingError(
            f"Cannot connect to embedding endpoint {_cfg.embedding_base_url}. "
            f"Is Docker Model Runner (or your configured LLM server) running?"
        )
```

**Step 4: Update CLI callers in `tools/brain_index.py`**

In `index_brain` and `detect_embedding_dim`, wrap `get_embedding` / `index_file` calls to catch `EmbeddingError` and call `sys.exit(1)` with the message:

```python
from lib.embeddings import get_embedding, EmbeddingError

def detect_embedding_dim() -> int:
    print(f"Detecting embedding dimension for {_cfg.embedding_model}...", file=sys.stderr)
    try:
        vec = get_embedding("dimension probe")
    except EmbeddingError as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)
    dim = len(vec)
    print(f"  → {dim} dimensions", file=sys.stderr)
    return dim

def index_file(filepath: str, db_path: str) -> None:
    # ... existing code ...
    for i, chunk in enumerate(chunks):
        content_hash = hashlib.sha256(chunk.encode()).hexdigest()
        if existing_hashes.get(i) == content_hash:
            continue
        try:
            embedding = get_embedding(chunk)
        except EmbeddingError as e:
            print(f"Warning: skipping chunk {i} of {filepath}: {e}", file=sys.stderr)
            continue
        upsert_chunk(...)
```

**Step 5: Update API callers in `tools/lib/brain.py`**

In `handle_brain_search` and `handle_brain_related`, catch `EmbeddingError`:

```python
from lib.embeddings import get_embedding, EmbeddingError

def handle_brain_search(query: str, limit: int, db_path: str) -> str:
    from lib.db import search_chunks
    try:
        embedding = get_embedding(query)
    except EmbeddingError as e:
        return f"Error: embedding service unavailable — {e}"
    results = search_chunks(db_path, embedding, limit=limit)
    return _format_results(results)
```

Apply the same pattern to `handle_brain_related`.

**Step 6: Update `tools/brain_api.py`**

In `search_notes` and `related_notes`, catch `EmbeddingError` and raise HTTP 503:

```python
from lib.embeddings import EmbeddingError

@app.get("/api/search", ...)
def search_notes(...):
    from lib.db import search_chunks
    from lib.embeddings import get_embedding, EmbeddingError
    try:
        embedding = get_embedding(q)
    except EmbeddingError as e:
        raise HTTPException(503, f"Embedding service unavailable: {e}")
    ...
```

**Step 7: Run all tests**
```bash
pytest tests/test_brain_service.py tests/test_brain_index.py -v
```
Expected: all PASS

**Step 8: Commit**
```bash
git add tools/lib/embeddings.py tools/brain_index.py tools/lib/brain.py tools/brain_api.py tests/test_brain_service.py tests/test_brain_index.py
git commit -m "fix: replace sys.exit(1) in get_embedding with EmbeddingError; handle in API and CLI"
```

---

### Task 7: Fix `entrypoint.sh` retry loop for non-transient errors

**Files:**
- Modify: `tools/entrypoint.sh`

**Background:** The `while true` restart loop restarts even on fatal errors (e.g. dimension mismatch exit code 1), causing a retry storm. Exit codes: `0` = clean stop (should restart), `130`/`SIGINT` = interrupted (stop), `1` = error (stop and log). Only restart on signal-kill or clean exit.

**Step 1: Read the current `entrypoint.sh`** before editing.

**Step 2: Update the watch loop**

Replace:
```sh
while true; do
    brain-index watch >> /brain/.ai/watch.log 2>&1
    echo "$(date): brain-index watch exited, retrying in 30s..." >> /brain/.ai/watch.log
    sleep 30
done
```

With:
```sh
RETRY_DELAY=30
while true; do
    brain-index watch >> /brain/.ai/watch.log 2>&1
    EXIT_CODE=$?
    if [ $EXIT_CODE -eq 1 ]; then
        echo "$(date): brain-index watch exited with error (code $EXIT_CODE) — not retrying. Check watch.log for details." >> /brain/.ai/watch.log
        break
    fi
    echo "$(date): brain-index watch exited (code $EXIT_CODE), retrying in ${RETRY_DELAY}s..." >> /brain/.ai/watch.log
    sleep $RETRY_DELAY
done &
```

**Step 3: Commit**
```bash
git add tools/entrypoint.sh
git commit -m "fix: stop watch retry loop on exit code 1 (non-transient errors)"
```

---

## MEDIUM

### Task 8: Test + fix `_find_section` off-by-one at end of string

**Files:**
- Modify: `tools/lib/edit.py:40`
- Test: `tests/lib/test_edit.py`

**Background:** `body_start = m.end() + 1` when the heading has no trailing newline results in `body_start > len(text)`. String slicing is safe in Python (returns `""`) but silently produces wrong output.

**Step 1: Write the failing test**

Add to `tests/lib/test_edit.py`:

```python
def test_replace_section_heading_at_eof_no_trailing_newline():
    """Section at end of file with no trailing newline must not silently truncate."""
    text = "# Overview\n\nSome content.\n\n# Final"  # no trailing newline
    result, found = replace_section(text, "Final", "New content.")
    assert found
    assert "New content." in result
    assert "Some content." in result  # prior section preserved
```

**Step 2: Run to confirm it fails**
```bash
pytest tests/lib/test_edit.py::test_replace_section_heading_at_eof_no_trailing_newline -v
```

**Step 3: Fix `tools/lib/edit.py`**

Change line 40:
```python
body_start = m.end() + 1  # skip the newline after the heading
```
To:
```python
body_start = min(m.end() + 1, len(text))  # skip the newline after the heading
```

**Step 4: Run all edit tests**
```bash
pytest tests/lib/test_edit.py -v
```
Expected: all PASS

**Step 5: Commit**
```bash
git add tools/lib/edit.py tests/lib/test_edit.py
git commit -m "fix: clamp _find_section body_start to len(text) to handle headings at EOF"
```

---

### Task 9: Test + fix `_relative_path` prefix collision

**Files:**
- Modify: `tools/lib/brain.py:66–70`
- Test: `tests/test_brain_service.py`

**Background:** `full_path.startswith(brain_path)` matches `/brain-backup/note.md` when `brain_path` is `/brain`. Use `os.path.relpath` instead.

**Step 1: Write the failing test**

Add to `tests/test_brain_service.py`:

```python
def test_relative_path_does_not_match_sibling_prefix():
    """_relative_path('/brain-backup/note.md', '/brain') must not strip the prefix."""
    result = _relative_path("/brain-backup/note.md", "/brain")
    # Should return the full path unchanged, not 'backup/note.md'
    assert result == "/brain-backup/note.md"
```

**Step 2: Run to confirm it fails**
```bash
pytest tests/test_brain_service.py::test_relative_path_does_not_match_sibling_prefix -v
```
Expected: FAIL (returns `"backup/note.md"`)

**Step 3: Fix `tools/lib/brain.py`**

Replace:
```python
def _relative_path(full_path: str, brain_path: str) -> str:
    """Return path relative to *brain_path*."""
    if full_path.startswith(brain_path):
        return full_path[len(brain_path):].lstrip("/")
    return full_path
```
With:
```python
def _relative_path(full_path: str, brain_path: str) -> str:
    """Return path relative to *brain_path*, or the original path if outside."""
    try:
        rel = os.path.relpath(full_path, brain_path)
    except ValueError:
        return full_path  # Windows: different drives
    if rel.startswith(".."):
        return full_path  # outside brain_path — return unchanged
    return rel
```

**Step 4: Run all service tests**
```bash
pytest tests/test_brain_service.py -v
```
Expected: all PASS

**Step 5: Commit**
```bash
git add tools/lib/brain.py tests/test_brain_service.py
git commit -m "fix: use os.path.relpath in _relative_path to avoid prefix collision"
```

---

### Task 10: Test + refactor `find_backlinks` / `handle_brain_backlinks` duplication

**Files:**
- Modify: `tools/lib/brain.py:286–361`
- Test: `tests/test_brain_service.py`

**Background:** Both functions walk the vault and find wikilinks. `handle_brain_backlinks` should call `find_backlinks` and format the result. This is a refactor — cover the current behaviour with a regression test first.

**Step 1: Write a regression test that covers both code paths**

Add to `tests/test_brain_service.py`:

```python
def test_handle_brain_backlinks_consistent_with_find_backlinks(tmp_path):
    """handle_brain_backlinks must return the same notes as find_backlinks."""
    target = tmp_path / "target.md"
    target.write_text("---\ntitle: Target\n---\n\nHello.")
    linker = tmp_path / "linker.md"
    linker.write_text("---\ntitle: Linker Note\n---\n\nSee [[target]] here.")

    formatted = handle_brain_backlinks("target.md", str(tmp_path))
    structured = find_backlinks(str(target), str(tmp_path))

    # Both must find the same linker
    assert len(structured) == 1
    assert "Linker Note" in formatted
    assert structured[0]["title"] == "Linker Note"
    assert structured[0]["filepath"] == "linker.md"
```

**Step 2: Run to confirm it passes (regression baseline)**
```bash
pytest tests/test_brain_service.py::test_handle_brain_backlinks_consistent_with_find_backlinks -v
```
Expected: PASS (both currently work correctly — this is a regression guard)

**Step 3: Refactor `tools/lib/brain.py`**

Replace `handle_brain_backlinks` to delegate to `find_backlinks`:

```python
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
```

**Step 4: Run all backlinks tests**
```bash
pytest tests/test_brain_service.py -v -k "backlink"
```
Expected: all PASS

**Step 5: Commit**
```bash
git add tools/lib/brain.py tests/test_brain_service.py
git commit -m "refactor: handle_brain_backlinks delegates to find_backlinks, eliminating duplication"
```

---

### Task 11: Test + fix `list_templates` parsing human-readable text

**Files:**
- Modify: `tools/brain_api.py:352–363`
- Modify: `tools/lib/brain.py:159–173` (add a data-returning variant)
- Test: `tests/test_brain_api.py`

**Background:** `list_templates` in the REST API parses the formatted string from `handle_brain_templates` by string-splitting. A format change silently breaks it. Fix by adding `_list_template_names(brain_path)` that returns `list[str]` directly, and having `handle_brain_templates` call it.

**Step 1: Write the failing test**

Read `tests/test_brain_api.py` first to understand existing patterns, then add:

```python
def test_list_templates_endpoint_returns_list_not_formatted_string(tmp_path, monkeypatch):
    """list_templates must return a clean list, not parse a formatted string."""
    templates_dir = tmp_path / ".zk" / "templates"
    templates_dir.mkdir(parents=True)
    (templates_dir / "effort.md").write_text("")
    (templates_dir / "discovery.md").write_text("")
    monkeypatch.setattr("brain_api._cfg.brain_path", str(tmp_path))

    from brain_api import list_templates
    result = list_templates()
    assert isinstance(result, list)
    assert "effort" in result
    assert "discovery" in result
    # Must NOT contain header text
    assert not any("Available" in item for item in result)
```

**Step 2: Run to confirm it passes or fails** (it may pass as-is — if so, the issue is fragility not current failure; still do the refactor)

**Step 3: Fix `tools/lib/brain.py`**

Extract a data-returning helper and keep `handle_brain_templates` as a formatting wrapper:

```python
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
```

Export `_list_template_names` from `brain.py` and import it in `brain_api.py`.

**Step 4: Fix `tools/brain_api.py`**

Replace `list_templates`:

```python
from lib.brain import (
    ...,
    _list_template_names,
)

@app.get("/api/templates", response_model=list[str])
def list_templates():
    """List available note templates."""
    return _list_template_names(brain_path=_cfg.brain_path)
```

**Step 5: Run tests**
```bash
pytest tests/test_brain_api.py -v -k "template"
```
Expected: all PASS

**Step 6: Commit**
```bash
git add tools/lib/brain.py tools/brain_api.py tests/test_brain_api.py
git commit -m "refactor: extract _list_template_names so REST API does not parse formatted string"
```

---

## LOW

### Task 12: Test + fix `handle_brain_create` template path traversal

**Files:**
- Modify: `tools/lib/brain.py:176–201`
- Test: `tests/test_brain_service.py`

**Background:** The `template` argument is passed to `zk new --template` without validation. A value like `../../../etc/passwd` could cause zk to open unexpected files. Restrict to bare filenames (no path separators).

**Step 1: Write the failing test**

Add to `tests/test_brain_service.py`:

```python
def test_brain_create_rejects_path_traversal_template(tmp_path):
    result = handle_brain_create("../../../etc/passwd", "Test", str(tmp_path))
    assert "invalid" in result.lower() or "template" in result.lower()

def test_brain_create_rejects_template_with_slash(tmp_path):
    result = handle_brain_create("subdir/template", "Test", str(tmp_path))
    assert "invalid" in result.lower() or "template" in result.lower()
```

Note: `handle_brain_create` needs to be added to the import in `test_brain_service.py`.

**Step 2: Run to confirm they fail**
```bash
pytest tests/test_brain_service.py::test_brain_create_rejects_path_traversal_template -v
```
Expected: FAIL (no validation — would try to call zk)

**Step 3: Fix `tools/lib/brain.py`**

At the start of `handle_brain_create`, before the `.md` extension check:

```python
def handle_brain_create(template, title, brain_path, directory=None):
    # Validate template is a bare filename — no path separators
    bare = template.rstrip(".md") if template.endswith(".md") else template
    if "/" in bare or "\\" in bare or ".." in bare:
        return f"Invalid template name: must be a bare filename with no path separators"
    if not template.endswith(".md"):
        template = template + ".md"
    ...
```

**Step 4: Run tests**
```bash
pytest tests/test_brain_service.py -v -k "create"
```
Expected: all PASS

**Step 5: Commit**
```bash
git add tools/lib/brain.py tests/test_brain_service.py
git commit -m "fix: reject path traversal in handle_brain_create template argument"
```

---

### Task 13: Fix module-level `Config()` at import time

**Files:**
- Modify: `tools/lib/embeddings.py`
- Modify: `tools/brain_index.py`
- Modify: `tools/brain_api.py`

**Background:** `_cfg = Config()` at module level reads env vars at import time. Changes to env vars after import (common in tests) are invisible. The existing tests use `importlib.reload` as a workaround. Lazy-initialise instead: move `_cfg` into a `_get_config()` helper that initialises once on first call.

**Note:** This is a low-risk, low-urgency refactor. Do it last. Existing tests already work around the issue.

**Step 1: Read all three files, then apply the same pattern to each**

Pattern (apply to `embeddings.py`, `brain_index.py`; `brain_api.py` uses `_cfg` pervasively so handle carefully):

```python
_cfg: Config | None = None

def _get_cfg() -> Config:
    global _cfg
    if _cfg is None:
        _cfg = Config()
    return _cfg
```

Then replace all `_cfg.` usages in the module with `_get_cfg().`.

**Step 2: Run full test suite**
```bash
pytest -m "not integration" -v
```
Expected: all PASS

**Step 3: Commit**
```bash
git add tools/lib/embeddings.py tools/brain_index.py tools/brain_api.py
git commit -m "refactor: lazy-initialise Config to avoid env-var freeze at import time"
```

---

## Final verification

After all tasks are complete:

```bash
pytest -m "not integration" -v
```

All tests must pass. Then open a PR against main.
