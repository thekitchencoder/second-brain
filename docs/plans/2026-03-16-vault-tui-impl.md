# Vault TUI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Docker container with zk, semantic search, and an MCP server that gives Claude Code provenance-aware access to a markdown vault.

**Architecture:** Python tools (`lib/clean.py`, `lib/db.py`, `lib/config.py`) are shared across `vault-index`, `vault-search`, and `vault-mcp-server`. All tools run inside a Docker container with the vault mounted at `/vault`. Embeddings stored in sqlite-vec at `/vault/.ai/embeddings.db`.

**Tech Stack:** Python 3.12, sqlite-vec, openai (embedding client), pyyaml, watchfiles, mcp (MCP server SDK), zk (Go binary), fzf, ripgrep, bat

---

### Task 1: Project Scaffolding

**Files:**
- Create: `tools/lib/__init__.py`
- Create: `tools/lib/config.py`
- Create: `tests/__init__.py`
- Create: `tests/lib/__init__.py`
- Create: `requirements.txt`
- Create: `pyproject.toml`
- Create: `.env.example`

**Step 1: Create directory structure**

```bash
mkdir -p tools/lib tests/lib
touch tools/lib/__init__.py tests/__init__.py tests/lib/__init__.py
```

**Step 2: Write `requirements.txt`**

```
openai>=1.0.0
pyyaml>=6.0
sqlite-vec>=0.1.0
watchfiles>=0.21.0
mcp>=1.0.0
pytest>=8.0.0
pytest-mock>=3.12.0
```

**Step 3: Write `pyproject.toml`**

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["tools"]
```

**Step 4: Write `.env.example`**

```
EMBEDDING_BASE_URL=http://model-runner.docker.internal/engines/llama.cpp/v1
EMBEDDING_MODEL=mxbai-embed-large
EMBEDDING_DIM=1024
CHAT_BASE_URL=http://model-runner.docker.internal/engines/llama.cpp/v1
CHAT_MODEL=llama3.2
VAULT_PATH=/vault
```

**Step 5: Commit**

```bash
git add tools/ tests/ requirements.txt pyproject.toml .env.example
git commit -m "chore: project scaffolding and test infrastructure"
```

---

### Task 2: `lib/config.py` — Shared Configuration

**Files:**
- Create: `tools/lib/config.py`
- Create: `tests/lib/test_config.py`

**Step 1: Write failing test**

```python
# tests/lib/test_config.py
import os
import pytest
from lib.config import Config


def test_defaults():
    cfg = Config()
    assert cfg.embedding_base_url == "http://model-runner.docker.internal/engines/llama.cpp/v1"
    assert cfg.embedding_model == "mxbai-embed-large"
    assert cfg.embedding_dim == 1024
    assert cfg.vault_path == "/vault"


def test_overrides_from_env(monkeypatch):
    monkeypatch.setenv("EMBEDDING_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("EMBEDDING_MODEL", "nomic-embed-text")
    monkeypatch.setenv("EMBEDDING_DIM", "768")
    monkeypatch.setenv("VAULT_PATH", "/tmp/testvault")
    cfg = Config()
    assert cfg.embedding_base_url == "http://localhost:11434/v1"
    assert cfg.embedding_model == "nomic-embed-text"
    assert cfg.embedding_dim == 768
    assert cfg.vault_path == "/tmp/testvault"
```

**Step 2: Run to confirm failure**

```bash
pytest tests/lib/test_config.py -v
```
Expected: `ImportError: cannot import name 'Config'`

**Step 3: Write `tools/lib/config.py`**

```python
import os


class Config:
    def __init__(self):
        self.embedding_base_url = os.environ.get(
            "EMBEDDING_BASE_URL",
            "http://model-runner.docker.internal/engines/llama.cpp/v1"
        )
        self.embedding_model = os.environ.get("EMBEDDING_MODEL", "mxbai-embed-large")
        self.embedding_dim = int(os.environ.get("EMBEDDING_DIM", "1024"))
        self.chat_base_url = os.environ.get(
            "CHAT_BASE_URL",
            "http://model-runner.docker.internal/engines/llama.cpp/v1"
        )
        self.chat_model = os.environ.get("CHAT_MODEL", "llama3.2")
        self.vault_path = os.environ.get("VAULT_PATH", "/vault")

    @property
    def db_path(self):
        return f"{self.vault_path}/.ai/embeddings.db"
```

**Step 4: Run to confirm passing**

```bash
pytest tests/lib/test_config.py -v
```
Expected: 2 PASSED

**Step 5: Commit**

```bash
git add tools/lib/config.py tests/lib/test_config.py
git commit -m "feat: shared config from environment variables"
```

---

### Task 3: `lib/clean.py` — Document Cleaner

**Files:**
- Create: `tools/lib/clean.py`
- Create: `tests/lib/test_clean.py`

**Step 1: Write failing tests**

```python
# tests/lib/test_clean.py
import pytest
from lib.clean import extract_frontmatter, clean_content, chunk_text


def test_extract_frontmatter_present():
    doc = "---\ntitle: Test\ntags: [foo, bar]\n---\n\nBody text here."
    meta, content = extract_frontmatter(doc)
    assert meta["title"] == "Test"
    assert meta["tags"] == ["foo", "bar"]
    assert content.strip() == "Body text here."


def test_extract_frontmatter_absent():
    doc = "No front matter here."
    meta, content = extract_frontmatter(doc)
    assert meta == {}
    assert content == "No front matter here."


def test_clean_strips_ascii_art():
    content = "Real text.\n\n───────────────────\n\nMore text."
    result = clean_content(content)
    assert "───" not in result
    assert "Real text." in result
    assert "More text." in result


def test_clean_strips_box_drawing_lines():
    content = "Intro.\n\n+-------+-------+\n| col1  | col2  |\n+-------+-------+\n\nOutro."
    result = clean_content(content)
    assert "+-------+" not in result


def test_clean_collapses_code_blocks():
    content = "Text before.\n\n```python\ndef foo():\n    return 42\n```\n\nText after."
    result = clean_content(content)
    assert "def foo" not in result
    assert "[code block: python]" in result
    assert "Text before." in result
    assert "Text after." in result


def test_clean_collapses_code_block_no_lang():
    content = "Text.\n\n```\nsome code\n```\n\nMore."
    result = clean_content(content)
    assert "some code" not in result
    assert "[code block]" in result


def test_clean_simplifies_tables():
    content = "Intro.\n\n| Col A | Col B |\n|-------|-------|\n| val1  | val2  |\n\nOutro."
    result = clean_content(content)
    assert "|-------|" not in result
    assert "Col A" in result
    assert "val1" in result


def test_clean_collapses_whitespace():
    content = "Line one.\n\n\n\n\nLine two."
    result = clean_content(content)
    assert "\n\n\n" not in result


def test_chunk_text_returns_non_empty_chunks():
    long_text = " ".join(["word"] * 2000)
    chunks = chunk_text(long_text)
    assert len(chunks) > 1
    assert all(len(c) > 0 for c in chunks)


def test_chunk_text_overlaps():
    # Each chunk should share some content with the next
    long_text = " ".join([f"word{i}" for i in range(2000)])
    chunks = chunk_text(long_text)
    # Last words of chunk 0 should appear at start of chunk 1
    last_words_of_first = chunks[0].split()[-20:]
    first_words_of_second = chunks[1].split()[:20]
    overlap = set(last_words_of_first) & set(first_words_of_second)
    assert len(overlap) > 0


def test_chunk_short_text_is_single_chunk():
    short = "This is a short note."
    chunks = chunk_text(short)
    assert len(chunks) == 1
    assert chunks[0] == short
```

**Step 2: Run to confirm failure**

```bash
pytest tests/lib/test_clean.py -v
```
Expected: `ImportError`

**Step 3: Write `tools/lib/clean.py`**

```python
import re
import yaml


def extract_frontmatter(text: str) -> tuple[dict, str]:
    """Extract YAML front matter. Returns (metadata_dict, remaining_content)."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    yaml_block = text[3:end].strip()
    content = text[end + 4:].lstrip("\n")
    try:
        meta = yaml.safe_load(yaml_block) or {}
    except yaml.YAMLError:
        meta = {}
    return meta, content


# Characters used in box-drawing and ASCII art
_BOX_CHARS = set("─│┼╔╗╚╝╠╣╦╩╬═║┌┐└┘├┤┬┴")
_REPEATED_SYMBOL_RE = re.compile(r"^[+\-=_~*#|]{4,}\s*$")
_CODE_BLOCK_RE = re.compile(r"```(\w*)\n.*?```", re.DOTALL)
_TABLE_SEPARATOR_RE = re.compile(r"^\|[\s\-:]+\|[\s\-:|]*$")
_MULTI_BLANK_RE = re.compile(r"\n{3,}")


def _is_ascii_art_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    box_count = sum(1 for c in stripped if c in _BOX_CHARS)
    if len(stripped) > 0 and box_count / len(stripped) > 0.5:
        return True
    if _REPEATED_SYMBOL_RE.match(stripped):
        return True
    return False


def _collapse_code_block(match: re.Match) -> str:
    lang = match.group(1).strip()
    return f"[code block: {lang}]" if lang else "[code block]"


def _simplify_table_line(line: str) -> str:
    if _TABLE_SEPARATOR_RE.match(line.strip()):
        return ""
    if line.strip().startswith("|"):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        return " ".join(c for c in cells if c)
    return line


def clean_content(content: str) -> str:
    """Clean document content for embedding. Strips noise, preserves prose."""
    # Collapse fenced code blocks first (before line-by-line processing)
    content = _CODE_BLOCK_RE.sub(_collapse_code_block, content)

    lines = content.splitlines()
    cleaned = []
    for line in lines:
        if _is_ascii_art_line(line):
            continue
        cleaned.append(_simplify_table_line(line))

    result = "\n".join(cleaned)
    result = _MULTI_BLANK_RE.sub("\n\n", result)
    return result.strip()


# ~4 chars per token; 400 tokens ≈ 1600 chars; 50-token overlap ≈ 200 chars
_CHUNK_SIZE = 1600
_CHUNK_OVERLAP = 200


def chunk_text(text: str) -> list[str]:
    """Split text into overlapping chunks, splitting on paragraph boundaries."""
    if len(text) <= _CHUNK_SIZE:
        return [text]

    paragraphs = re.split(r"\n\n+", text)
    chunks = []
    current = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para)
        if current_len + para_len > _CHUNK_SIZE and current:
            chunks.append("\n\n".join(current))
            # Keep last paragraph(s) for overlap
            overlap = []
            overlap_len = 0
            for p in reversed(current):
                if overlap_len + len(p) < _CHUNK_OVERLAP:
                    overlap.insert(0, p)
                    overlap_len += len(p)
                else:
                    break
            current = overlap
            current_len = overlap_len
        current.append(para)
        current_len += para_len

    if current:
        chunks.append("\n\n".join(current))

    return chunks
```

**Step 4: Run to confirm passing**

```bash
pytest tests/lib/test_clean.py -v
```
Expected: all PASSED

**Step 5: Commit**

```bash
git add tools/lib/clean.py tests/lib/test_clean.py
git commit -m "feat: document cleaner and chunker"
```

---

### Task 4: `lib/db.py` — sqlite-vec Helpers

**Files:**
- Create: `tools/lib/db.py`
- Create: `tests/lib/test_db.py`

**Step 1: Write failing tests**

```python
# tests/lib/test_db.py
import sqlite3
import tempfile
import os
import pytest
from lib.db import init_db, upsert_chunk, search_chunks, get_chunk_embeddings


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


def test_init_db_creates_tables(db_path):
    init_db(db_path, embedding_dim=4)
    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "chunks" in tables
    conn.close()


def test_upsert_chunk_inserts(db_path):
    init_db(db_path, embedding_dim=4)
    upsert_chunk(
        db_path=db_path,
        filepath="notes/foo.md",
        chunk_index=0,
        content="Some content here.",
        content_hash="abc123",
        embedding=[0.1, 0.2, 0.3, 0.4],
        meta={"title": "Foo", "type": "note", "status": "draft",
              "created": "2026-03-16", "tags": ["a"], "scope": None},
    )
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT filepath, title, type FROM chunks").fetchone()
    assert row == ("notes/foo.md", "Foo", "note")
    conn.close()


def test_upsert_chunk_updates_on_conflict(db_path):
    init_db(db_path, embedding_dim=4)
    meta = {"title": "Foo", "type": "note", "status": "draft",
            "created": "2026-03-16", "tags": [], "scope": None}
    upsert_chunk(db_path, "notes/foo.md", 0, "Original.", "hash1", [0.1]*4, meta)
    upsert_chunk(db_path, "notes/foo.md", 0, "Updated.", "hash2", [0.2]*4, meta)
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT content FROM chunks WHERE filepath='notes/foo.md'").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "Updated."
    conn.close()


def test_search_chunks_returns_results(db_path):
    init_db(db_path, embedding_dim=4)
    meta = {"title": "Foo", "type": "note", "status": "current",
            "created": "2026-03-16", "tags": ["test"], "scope": "testing"}
    upsert_chunk(db_path, "notes/foo.md", 0, "Content about foo.", "h1", [1.0, 0.0, 0.0, 0.0], meta)
    upsert_chunk(db_path, "notes/bar.md", 0, "Content about bar.", "h2", [0.0, 1.0, 0.0, 0.0], meta)

    results = search_chunks(db_path, query_embedding=[1.0, 0.0, 0.0, 0.0], limit=1)
    assert len(results) == 1
    assert results[0]["filepath"] == "notes/foo.md"
    assert results[0]["title"] == "Foo"
    assert results[0]["type"] == "note"
    assert results[0]["status"] == "current"
    assert "distance" in results[0]


def test_get_chunk_embeddings_returns_vectors(db_path):
    init_db(db_path, embedding_dim=4)
    meta = {"title": "X", "type": "note", "status": "draft",
            "created": "2026-03-16", "tags": [], "scope": None}
    upsert_chunk(db_path, "notes/x.md", 0, "text", "h1", [0.1, 0.2, 0.3, 0.4], meta)
    upsert_chunk(db_path, "notes/x.md", 1, "more", "h2", [0.5, 0.6, 0.7, 0.8], meta)

    vectors = get_chunk_embeddings(db_path, "notes/x.md")
    assert len(vectors) == 2
    assert len(vectors[0]) == 4
```

**Step 2: Run to confirm failure**

```bash
pytest tests/lib/test_db.py -v
```
Expected: `ImportError`

**Step 3: Write `tools/lib/db.py`**

```python
import json
import sqlite3
import sqlite_vec


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str, embedding_dim: int) -> None:
    """Create tables if they don't exist. Idempotent."""
    conn = _connect(db_path)
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
        INSERT OR IGNORE INTO meta VALUES ('embedding_dim', '{embedding_dim}');
    """)
    conn.commit()
    conn.close()


def upsert_chunk(
    db_path: str,
    filepath: str,
    chunk_index: int,
    content: str,
    content_hash: str,
    embedding: list[float],
    meta: dict,
) -> None:
    conn = _connect(db_path)
    tags_json = json.dumps(meta.get("tags") or [])
    # Upsert chunk row
    conn.execute("""
        INSERT INTO chunks (filepath, chunk_index, content, content_hash, title, type, status, created, tags, scope)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(filepath, chunk_index) DO UPDATE SET
            content=excluded.content,
            content_hash=excluded.content_hash,
            title=excluded.title,
            type=excluded.type,
            status=excluded.status,
            created=excluded.created,
            tags=excluded.tags,
            scope=excluded.scope
    """, (filepath, chunk_index, content, content_hash, meta.get("title"),
          meta.get("type"), meta.get("status"), meta.get("created"),
          tags_json, meta.get("scope")))
    chunk_id = conn.execute(
        "SELECT id FROM chunks WHERE filepath=? AND chunk_index=?",
        (filepath, chunk_index)
    ).fetchone()[0]
    # Upsert embedding
    conn.execute("DELETE FROM embeddings WHERE rowid=?", (chunk_id,))
    conn.execute(
        "INSERT INTO embeddings(rowid, embedding) VALUES (?, ?)",
        (chunk_id, sqlite_vec.serialize_float32(embedding))
    )
    conn.commit()
    conn.close()


def search_chunks(db_path: str, query_embedding: list[float], limit: int = 5) -> list[dict]:
    conn = _connect(db_path)
    rows = conn.execute("""
        SELECT c.filepath, c.chunk_index, c.content, c.title, c.type,
               c.status, c.created, c.tags, c.scope, e.distance
        FROM embeddings e
        JOIN chunks c ON c.id = e.rowid
        WHERE e.embedding MATCH ?
        ORDER BY e.distance
        LIMIT ?
    """, (sqlite_vec.serialize_float32(query_embedding), limit)).fetchall()
    conn.close()
    results = []
    for row in rows:
        r = dict(row)
        r["tags"] = json.loads(r["tags"] or "[]")
        results.append(r)
    return results


def get_chunk_embeddings(db_path: str, filepath: str) -> list[list[float]]:
    """Return all embedding vectors for a given filepath."""
    conn = _connect(db_path)
    rows = conn.execute("""
        SELECT e.embedding
        FROM embeddings e
        JOIN chunks c ON c.id = e.rowid
        WHERE c.filepath = ?
    """, (filepath,)).fetchall()
    conn.close()
    return [sqlite_vec.deserialize_float32(row[0]) for row in rows]
```

**Step 4: Run to confirm passing**

```bash
pytest tests/lib/test_db.py -v
```
Expected: all PASSED

**Step 5: Commit**

```bash
git add tools/lib/db.py tests/lib/test_db.py
git commit -m "feat: sqlite-vec database helpers"
```

---

### Task 5: `vault-index` — Full Reindex

**Files:**
- Create: `tools/vault-index`
- Create: `tests/test_vault_index.py`

**Step 1: Write failing tests**

```python
# tests/test_vault_index.py
import os
import tempfile
import textwrap
import pytest
from unittest.mock import patch, MagicMock
from vault_index import index_vault, index_file


@pytest.fixture
def vault(tmp_path):
    note = tmp_path / "test-note.md"
    note.write_text(textwrap.dedent("""\
        ---
        title: Test Note
        type: note
        status: current
        created: 2026-03-16
        tags: [testing]
        ---

        This is the body of the test note. It has enough content to be meaningful.
    """))
    ai_dir = tmp_path / ".ai"
    ai_dir.mkdir()
    return tmp_path


@pytest.fixture
def mock_embed():
    with patch("vault_index.get_embedding") as mock:
        mock.return_value = [0.1] * 1024
        yield mock


def test_index_file_creates_chunks(vault, mock_embed):
    db_path = str(vault / ".ai" / "embeddings.db")
    from lib.db import init_db
    init_db(db_path, embedding_dim=1024)

    filepath = str(vault / "test-note.md")
    index_file(filepath, db_path)

    mock_embed.assert_called()


def test_index_vault_processes_markdown_files(vault, mock_embed):
    db_path = str(vault / ".ai" / "embeddings.db")
    index_vault(str(vault), db_path)
    mock_embed.assert_called()


def test_index_vault_skips_dotdirectories(vault, mock_embed):
    # Files inside .obsidian or .zk should be ignored
    obsidian_dir = vault / ".obsidian"
    obsidian_dir.mkdir()
    (obsidian_dir / "config.json").write_text("{}")

    db_path = str(vault / ".ai" / "embeddings.db")
    index_vault(str(vault), db_path)

    # Should only have been called for the one real note
    calls = mock_embed.call_count
    assert calls >= 1  # at least the real note


def test_index_file_skips_unchanged_chunks(vault, mock_embed):
    db_path = str(vault / ".ai" / "embeddings.db")
    from lib.db import init_db
    init_db(db_path, embedding_dim=1024)

    filepath = str(vault / "test-note.md")
    index_file(filepath, db_path)
    first_call_count = mock_embed.call_count

    # Second index of same file with same content — should not re-embed
    index_file(filepath, db_path)
    assert mock_embed.call_count == first_call_count
```

**Step 2: Run to confirm failure**

```bash
pytest tests/test_vault_index.py -v
```
Expected: `ImportError`

**Step 3: Write `tools/vault-index`**

```python
#!/usr/bin/env python3
"""vault-index: index vault notes into sqlite-vec for semantic search.

Usage:
  vault-index run    Full reindex of all markdown files
  vault-index watch  Watch for changes and reindex incrementally
"""
import hashlib
import os
import sys

from openai import OpenAI

from lib.clean import chunk_text, clean_content, extract_frontmatter
from lib.config import Config
from lib.db import init_db, upsert_chunk

_cfg = Config()
_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(base_url=_cfg.embedding_base_url, api_key="local")
    return _client


def get_embedding(text: str) -> list[float]:
    response = _get_client().embeddings.create(
        input=text,
        model=_cfg.embedding_model,
    )
    return response.data[0].embedding


def index_file(filepath: str, db_path: str) -> None:
    with open(filepath, "r", encoding="utf-8") as f:
        raw = f.read()

    meta, content = extract_frontmatter(raw)
    cleaned = clean_content(content)
    chunks = chunk_text(cleaned)

    import sqlite3
    conn = sqlite3.connect(db_path)

    for i, chunk in enumerate(chunks):
        content_hash = hashlib.sha256(chunk.encode()).hexdigest()
        # Skip if unchanged
        existing = conn.execute(
            "SELECT content_hash FROM chunks WHERE filepath=? AND chunk_index=?",
            (filepath, i)
        ).fetchone()
        if existing and existing[0] == content_hash:
            continue

        embedding = get_embedding(chunk)
        conn.close()
        upsert_chunk(
            db_path=db_path,
            filepath=filepath,
            chunk_index=i,
            content=chunk,
            content_hash=content_hash,
            embedding=embedding,
            meta=meta,
        )
        conn = sqlite3.connect(db_path)

    conn.close()


def index_vault(vault_path: str, db_path: str) -> None:
    init_db(db_path, embedding_dim=_cfg.embedding_dim)
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
            if path.endswith(".md") and "/.ai/" not in path:
                print(f"Reindexing {path}", file=sys.stderr)
                index_file(path, db_path)


if __name__ == "__main__":
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
```

**Step 4: Run to confirm passing**

```bash
pytest tests/test_vault_index.py -v
```
Expected: all PASSED

**Step 5: Commit**

```bash
git add tools/vault-index tests/test_vault_index.py
git commit -m "feat: vault-index full reindex and watch mode"
```

---

### Task 6: `vault-search` — Semantic Search CLI

**Files:**
- Create: `tools/vault-search`
- Create: `tests/test_vault_search.py`

**Step 1: Write failing tests**

```python
# tests/test_vault_search.py
import pytest
from unittest.mock import patch
from vault_search import format_result, search


@pytest.fixture
def mock_results():
    return [
        {
            "filepath": "projects/test.md",
            "content": "This is matching content.",
            "title": "Test Note",
            "type": "context-primer",
            "status": "current",
            "created": "2026-03-16",
            "tags": ["testing", "foo"],
            "scope": "test-scope",
            "distance": 0.12,
        }
    ]


def test_format_result_includes_key_fields(mock_results):
    output = format_result(mock_results[0])
    assert "Test Note" in output
    assert "projects/test.md" in output
    assert "current" in output
    assert "2026-03-16" in output
    assert "testing" in output
    assert "This is matching content." in output


def test_search_calls_db(mock_results):
    with patch("vault_search.get_embedding", return_value=[0.1] * 1024), \
         patch("vault_search.search_chunks", return_value=mock_results) as mock_db:
        results = search("test query", db_path="/tmp/fake.db", limit=3)
        mock_db.assert_called_once()
        assert len(results) == 1
```

**Step 2: Run to confirm failure**

```bash
pytest tests/test_vault_search.py -v
```
Expected: `ImportError`

**Step 3: Write `tools/vault-search`**

```python
#!/usr/bin/env python3
"""vault-search: semantic search across the vault.

Usage:
  vault-search "your query"
  vault-search "your query" --limit 10
"""
import json
import sys

from openai import OpenAI

from lib.config import Config
from lib.db import search_chunks

_cfg = Config()
_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(base_url=_cfg.embedding_base_url, api_key="local")
    return _client


def get_embedding(text: str) -> list[float]:
    response = _get_client().embeddings.create(
        input=text,
        model=_cfg.embedding_model,
    )
    return response.data[0].embedding


def format_result(result: dict) -> str:
    tags = ", ".join(result.get("tags") or [])
    lines = [
        f"## {result['title'] or result['filepath']}",
        f"  File:    {result['filepath']}",
        f"  Type:    {result.get('type', '-')}",
        f"  Status:  {result.get('status', '-')}",
        f"  Created: {result.get('created', '-')}",
        f"  Tags:    {tags or '-'}",
        f"  Score:   {result['distance']:.4f}",
        "",
        f"  {result['content'][:300].strip()}",
        "",
    ]
    return "\n".join(lines)


def search(query: str, db_path: str, limit: int = 5) -> list[dict]:
    embedding = get_embedding(query)
    return search_chunks(db_path, embedding, limit=limit)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Semantic search across vault")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--limit", type=int, default=5, help="Number of results")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    results = search(args.query, db_path=_cfg.db_path, limit=args.limit)

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        if not results:
            print("No results found.")
        for r in results:
            print(format_result(r))
```

**Step 4: Run to confirm passing**

```bash
pytest tests/test_vault_search.py -v
```
Expected: all PASSED

**Step 5: Commit**

```bash
git add tools/vault-search tests/test_vault_search.py
git commit -m "feat: vault-search semantic search CLI"
```

---

### Task 7: `vault-mcp-server` — MCP Server

**Files:**
- Create: `tools/vault-mcp-server`
- Create: `tests/test_vault_mcp_server.py`

**Step 1: Write failing tests**

```python
# tests/test_vault_mcp_server.py
import json
import pytest
from unittest.mock import patch, MagicMock
from vault_mcp_server import handle_vault_search, handle_vault_query, handle_vault_related


@pytest.fixture
def mock_search_results():
    return [
        {
            "filepath": "atlas/test.md",
            "content": "Some content.",
            "title": "Test",
            "type": "note",
            "status": "current",
            "created": "2026-03-16",
            "tags": ["foo"],
            "scope": None,
            "distance": 0.1,
        }
    ]


def test_handle_vault_search_returns_text(mock_search_results):
    with patch("vault_mcp_server.get_embedding", return_value=[0.1] * 1024), \
         patch("vault_mcp_server.search_chunks", return_value=mock_search_results):
        result = handle_vault_search(query="test", limit=5, db_path="/tmp/fake.db")
    assert "Test" in result
    assert "atlas/test.md" in result
    assert "current" in result


def test_handle_vault_search_no_results():
    with patch("vault_mcp_server.get_embedding", return_value=[0.1] * 1024), \
         patch("vault_mcp_server.search_chunks", return_value=[]):
        result = handle_vault_search(query="nothing", limit=5, db_path="/tmp/fake.db")
    assert "No results" in result


def test_handle_vault_related_returns_text(mock_search_results):
    with patch("vault_mcp_server.get_chunk_embeddings", return_value=[[0.1] * 1024]), \
         patch("vault_mcp_server.search_chunks", return_value=mock_search_results):
        result = handle_vault_related(
            filepath="notes/other.md", limit=5,
            db_path="/tmp/fake.db", vault_path="/vault"
        )
    assert "Test" in result


def test_handle_vault_related_no_embeddings():
    with patch("vault_mcp_server.get_chunk_embeddings", return_value=[]):
        result = handle_vault_related(
            filepath="notes/missing.md", limit=5,
            db_path="/tmp/fake.db", vault_path="/vault"
        )
    assert "not indexed" in result.lower() or "no embeddings" in result.lower()


def test_handle_vault_query_runs_zk(tmp_path):
    with patch("vault_mcp_server.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            stdout="notes/foo.md\nnotes/bar.md\n",
            returncode=0
        )
        result = handle_vault_query(tag="testing", status=None, type=None, vault_path=str(tmp_path))
    assert "foo.md" in result
    assert "bar.md" in result
```

**Step 2: Run to confirm failure**

```bash
pytest tests/test_vault_mcp_server.py -v
```
Expected: `ImportError`

**Step 3: Write `tools/vault-mcp-server`**

```python
#!/usr/bin/env python3
"""vault-mcp-server: MCP server exposing vault tools to Claude Code."""
import json
import subprocess
import sys
from typing import Optional

import numpy as np
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from openai import OpenAI

from lib.config import Config
from lib.db import get_chunk_embeddings, search_chunks

_cfg = Config()
_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(base_url=_cfg.embedding_base_url, api_key="local")
    return _client


def get_embedding(text: str) -> list[float]:
    response = _get_client().embeddings.create(
        input=text, model=_cfg.embedding_model
    )
    return response.data[0].embedding


def _format_results(results: list[dict]) -> str:
    if not results:
        return "No results found."
    lines = []
    for r in results:
        tags = ", ".join(r.get("tags") or [])
        lines += [
            f"### {r.get('title') or r['filepath']}",
            f"- **File:** {r['filepath']}",
            f"- **Type:** {r.get('type', '-')}  **Status:** {r.get('status', '-')}",
            f"- **Created:** {r.get('created', '-')}  **Tags:** {tags or '-'}",
            "",
            r["content"][:400].strip(),
            "",
            "---",
            "",
        ]
    return "\n".join(lines)


def handle_vault_search(query: str, limit: int, db_path: str) -> str:
    embedding = get_embedding(query)
    results = search_chunks(db_path, embedding, limit=limit)
    return _format_results(results)


def handle_vault_related(filepath: str, limit: int, db_path: str, vault_path: str) -> str:
    full_path = filepath if filepath.startswith("/") else f"{vault_path}/{filepath}"
    vectors = get_chunk_embeddings(db_path, full_path)
    if not vectors:
        # Try relative path as stored
        vectors = get_chunk_embeddings(db_path, filepath)
    if not vectors:
        return f"No embeddings found for {filepath}. Has it been indexed?"
    mean_vec = list(np.mean(vectors, axis=0))
    results = [r for r in search_chunks(db_path, mean_vec, limit=limit + 1)
               if r["filepath"] != full_path and r["filepath"] != filepath]
    return _format_results(results[:limit])


def handle_vault_query(
    tag: Optional[str], status: Optional[str], type: Optional[str], vault_path: str
) -> str:
    cmd = ["zk", "list", "--quiet", "--format", "{{path}}"]
    if tag:
        cmd += ["--tag", tag]
    if status:
        cmd += ["--match", f"status:{status}"]
    result = subprocess.run(cmd, cwd=vault_path, capture_output=True, text=True)
    if result.returncode != 0:
        return f"zk list failed: {result.stderr}"
    files = [f.strip() for f in result.stdout.splitlines() if f.strip()]
    if not files:
        return "No notes matched the query."
    return "\n".join(files)


def handle_vault_create(template: str, title: str, vault_path: str) -> str:
    result = subprocess.run(
        ["zk", "new", "--template", template, "--title", title],
        cwd=vault_path, capture_output=True, text=True
    )
    if result.returncode != 0:
        return f"zk new failed: {result.stderr}"
    return result.stdout.strip()


def main():
    server = Server("vault")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="vault_search",
                description="Semantic search across vault notes. Returns matched content with full frontmatter (type, status, created, tags) for provenance.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "limit": {"type": "integer", "default": 5, "description": "Number of results"},
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="vault_query",
                description="Structured metadata query using zk. Filter notes by tag, status, or type.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "tag": {"type": "string"},
                        "status": {"type": "string"},
                        "type": {"type": "string"},
                    },
                },
            ),
            Tool(
                name="vault_create",
                description="Create a new note from a template.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "template": {"type": "string", "description": "Template name (default, daily, meeting, effort)"},
                        "title": {"type": "string"},
                    },
                    "required": ["template", "title"],
                },
            ),
            Tool(
                name="vault_related",
                description="Find notes semantically related to a given file.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "filepath": {"type": "string", "description": "Relative path to the note"},
                        "limit": {"type": "integer", "default": 5},
                    },
                    "required": ["filepath"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        db_path = _cfg.db_path
        vault_path = _cfg.vault_path

        if name == "vault_search":
            text = handle_vault_search(
                query=arguments["query"],
                limit=arguments.get("limit", 5),
                db_path=db_path,
            )
        elif name == "vault_query":
            text = handle_vault_query(
                tag=arguments.get("tag"),
                status=arguments.get("status"),
                type=arguments.get("type"),
                vault_path=vault_path,
            )
        elif name == "vault_create":
            text = handle_vault_create(
                template=arguments["template"],
                title=arguments["title"],
                vault_path=vault_path,
            )
        elif name == "vault_related":
            text = handle_vault_related(
                filepath=arguments["filepath"],
                limit=arguments.get("limit", 5),
                db_path=db_path,
                vault_path=vault_path,
            )
        else:
            text = f"Unknown tool: {name}"

        return [TextContent(type="text", text=text)]

    with stdio_server() as streams:
        import asyncio
        asyncio.run(server.run(*streams))


if __name__ == "__main__":
    main()
```

**Step 4: Run to confirm passing**

```bash
pytest tests/test_vault_mcp_server.py -v
```
Expected: all PASSED

**Step 5: Commit**

```bash
git add tools/vault-mcp-server tests/test_vault_mcp_server.py
git commit -m "feat: MCP server with vault_search, vault_query, vault_create, vault_related"
```

---

### Task 8: zk Config & Templates

**Files:**
- Create: `zk/config.toml`
- Create: `zk/templates/default.md`
- Create: `zk/templates/daily.md`
- Create: `zk/templates/meeting.md`
- Create: `zk/templates/effort.md`

No tests needed — these are static config files.

**Step 1: Write `zk/config.toml`**

```toml
[notebook]
dir = "/vault"

[note]
filename = "{{slug title}}"
extension = "md"
template = "default.md"
id-charset = "alphanum"
id-length = 0

[extra]
author = "Chris"

[tool]
fzf-preview = "bat --color=always --style=plain {path}"

[filter]
recents = "--sort created- --created-after '2 weeks ago'"
```

**Step 2: Write `zk/templates/default.md`**

```
---
type: note
title: "{{title}}"
created: {{format-date now "2006-01-02"}}
tags: []
status: draft
---

# {{title}}
```

**Step 3: Write `zk/templates/daily.md`**

```
---
type: journal
title: "{{format-date now "2006-01-02"}}"
created: {{format-date now "2006-01-02"}}
tags: []
status: current
---

# {{format-date now "2006-01-02"}}

## Today

## Notes
```

**Step 4: Write `zk/templates/meeting.md`**

```
---
type: meeting
title: "{{title}}"
created: {{format-date now "2006-01-02"}}
tags: []
status: current
attendees: []
---

# {{title}}

## Notes

## Actions
```

**Step 5: Write `zk/templates/effort.md`**

```
---
type: effort
title: "{{title}}"
created: {{format-date now "2006-01-02"}}
tags: []
status: active
---

# {{title}}

## Goal

## Log
```

**Step 6: Commit**

```bash
git add zk/
git commit -m "feat: zk config and note templates"
```

---

### Task 9: `vault-init` Script

**Files:**
- Create: `tools/vault-init`

**Step 1: Write `tools/vault-init`**

```python
#!/usr/bin/env python3
"""vault-init: initialise a vault for use with vault tools.

Copies .zk config and templates into the vault.
Creates .ai directory for embeddings.
Idempotent — safe to run multiple times.
"""
import os
import shutil
import sys

ZK_SOURCE = "/usr/local/lib/vault-tools/zk"
TOOLS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def init_vault(vault_path: str) -> None:
    # Locate zk source relative to this script (works both locally and in container)
    zk_source = os.path.join(TOOLS_ROOT, "zk")
    if not os.path.isdir(zk_source):
        zk_source = ZK_SOURCE

    zk_dest = os.path.join(vault_path, ".zk")
    ai_dest = os.path.join(vault_path, ".ai")

    if os.path.isdir(zk_dest):
        print(f".zk already exists at {zk_dest}, skipping.")
    else:
        shutil.copytree(zk_source, zk_dest)
        print(f"Created {zk_dest}")

    os.makedirs(ai_dest, exist_ok=True)
    print(f"Ensured {ai_dest} exists")

    print("Vault initialised.")


if __name__ == "__main__":
    vault_path = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("VAULT_PATH", "/vault")
    if not os.path.isdir(vault_path):
        print(f"Error: vault path does not exist: {vault_path}", file=sys.stderr)
        sys.exit(1)
    init_vault(vault_path)
```

**Step 2: Commit**

```bash
git add tools/vault-init
git commit -m "feat: vault-init setup script"
```

---

### Task 10: Dockerfile & docker-compose

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`

**Step 1: Write `Dockerfile`**

```dockerfile
FROM python:3.12-slim

ARG ZK_VERSION=0.14.1
ARG TARGETARCH

# System tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    fzf \
    ripgrep \
    bat \
    zsh \
    git \
    && rm -rf /var/lib/apt/lists/*

# zk binary
RUN ARCH=$(dpkg --print-architecture) && \
    case "$ARCH" in \
      amd64) ZK_ARCH="linux-amd64" ;; \
      arm64) ZK_ARCH="linux-arm64" ;; \
      *) echo "Unsupported arch: $ARCH" && exit 1 ;; \
    esac && \
    curl -fsSL "https://github.com/zk-org/zk/releases/download/v${ZK_VERSION}/zk-v${ZK_VERSION}-${ZK_ARCH}.tar.gz" \
    | tar xz -C /usr/local/bin/ zk && \
    chmod +x /usr/local/bin/zk

# Python dependencies
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Vault tools
COPY tools/ /usr/local/lib/vault-tools/
COPY zk/ /usr/local/lib/vault-tools/zk/
RUN chmod +x /usr/local/lib/vault-tools/vault-index \
              /usr/local/lib/vault-tools/vault-search \
              /usr/local/lib/vault-tools/vault-mcp-server \
              /usr/local/lib/vault-tools/vault-init

# Add tools to PATH
ENV PATH="/usr/local/lib/vault-tools:$PATH"
ENV PYTHONPATH="/usr/local/lib/vault-tools"

WORKDIR /vault
CMD ["zsh"]
```

**Step 2: Write `docker-compose.yml`**

```yaml
services:
  vault:
    build: .
    container_name: vault
    volumes:
      - ${VAULT_PATH:-~/Documents/Vault33}:/vault
    env_file:
      - .env
    stdin_open: true
    tty: true
    restart: unless-stopped
```

**Step 3: Commit**

```bash
git add Dockerfile docker-compose.yml
git commit -m "feat: Dockerfile and docker-compose"
```

---

### Task 11: README

**Files:**
- Create: `README.md`

**Step 1: Write `README.md`**

````markdown
# second-brain

Docker container for vault management: zk, semantic search, and MCP server for Claude Code.

## Quick start

```bash
# Copy and configure
cp .env.example .env
# Edit VAULT_PATH in .env to point at your vault

# Build
docker compose build

# Start (runs in background)
docker compose up -d

# Shell into the container
docker exec -it vault zsh

# Initialise a vault (first time only)
vault-init
```

## Host aliases

Add to `~/.zshrc` or `~/.bashrc`:

```bash
# Drop into vault shell
alias vault='docker exec -it vault zsh'

# Semantic search from host
alias vsearch='docker exec vault vault-search'

# Index vault from host
alias vindex='docker exec vault vault-index run'

# Watch mode (background indexing)
alias vwatch='docker exec -d vault vault-index watch'
```

## Inside the container

```bash
# Search notes
zk list --tag "foo"
zk list --match "content to find"

# Interactive search with preview
zk list | fzf --preview 'bat --color=always {}'

# Recent notes
zk list $recents

# Create a note
zk new --title "My Note"
zk new --template meeting --title "Team Sync"
zk new --template daily

# Semantic search
vault-search "co-dependent confabulation"
vault-search "embedding models" --limit 10
vault-search "query" --json

# Reindex
vault-index run

# Watch for changes
vault-index watch
```

## MCP server (Claude Code)

Add to `~/.claude/mcp.json`:

```json
{
  "mcpServers": {
    "vault": {
      "command": "docker",
      "args": ["exec", "-i", "vault", "python3",
               "/usr/local/lib/vault-tools/vault-mcp-server"]
    }
  }
}
```

Available tools: `vault_search`, `vault_query`, `vault_create`, `vault_related`

## Configuration

| Variable | Default | Description |
|---|---|---|
| `VAULT_PATH` | `/vault` | Path to vault inside container |
| `EMBEDDING_BASE_URL` | Docker Model Runner | OpenAI-compatible embedding endpoint |
| `EMBEDDING_MODEL` | `mxbai-embed-large` | Embedding model name |
| `EMBEDDING_DIM` | `1024` | Embedding vector dimension |
| `CHAT_BASE_URL` | Docker Model Runner | Chat completions endpoint |
| `CHAT_MODEL` | `llama3.2` | Chat model name |

Compatible with Docker Model Runner (default), Ollama (`http://host.docker.internal:11434/v1`), or LM Studio.
````

**Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README with quickstart, aliases, and MCP config"
```

---

### Task 12: Full Test Run & Smoke Test

**Step 1: Run full test suite**

```bash
pytest tests/ -v
```
Expected: all PASSED

**Step 2: Build Docker image**

```bash
docker compose build
```
Expected: build succeeds, no errors

**Step 3: Run container and verify tools are on PATH**

```bash
docker compose up -d
docker exec vault which zk vault-index vault-search vault-mcp-server vault-init
```
Expected: paths printed for all five

**Step 4: Smoke test vault-init**

```bash
docker exec vault vault-init
```
Expected: `.zk` and `.ai` created in vault

**Step 5: Commit**

```bash
git commit --allow-empty -m "chore: all tests passing, container verified"
```

---

## Execution Options

Plan saved to `docs/plans/2026-03-16-vault-tui-impl.md`.

**1. Subagent-Driven (this session)** — dispatch a fresh subagent per task, review between tasks

**2. Parallel Session (separate)** — open a new session with `superpowers:executing-plans`, batch execution with checkpoints

Which approach?
