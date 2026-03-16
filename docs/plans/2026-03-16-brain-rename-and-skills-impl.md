# Brain Rename + Skills Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rename all `vault` references to `brain` throughout the codebase, then ship four Claude Code skills (`brain-context`, `brain-save`, `brain-project`, `brain-hygiene`) in a `skills/` directory.

**Architecture:** The rename is a coordinated find-and-replace across Python modules, entrypoints, Dockerfile, Docker Compose, and MCP config — done as a single logical unit before the skills are written. Skills are plain markdown files in `skills/` that users copy to `~/.claude/skills/`. The rename must complete before skills are written because skills reference the new tool names.

**Tech Stack:** Python, Docker, Claude Code MCP, pytest, zsh

---

### Task 1: Rename Python modules and update symbols

**Files:**
- Rename: `tools/vault_mcp_server.py` → `tools/brain_mcp_server.py`
- Rename: `tools/vault_index.py` → `tools/brain_index.py`
- Rename: `tools/vault_search.py` → `tools/brain_search.py`
- Modify: `tools/lib/config.py`

**Step 1: Rename the three Python files**

```bash
cd /Users/chris/projects/second-brain
git mv tools/vault_mcp_server.py tools/brain_mcp_server.py
git mv tools/vault_index.py tools/brain_index.py
git mv tools/vault_search.py tools/brain_search.py
```

**Step 2: Update brain_mcp_server.py — rename MCP tool names and handler functions**

In `tools/brain_mcp_server.py`, make these replacements throughout the file:

| Old | New |
|-----|-----|
| `handle_vault_search` | `handle_brain_search` |
| `handle_vault_query` | `handle_brain_query` |
| `handle_vault_create` | `handle_brain_create` |
| `handle_vault_related` | `handle_brain_related` |
| `"vault_search"` | `"brain_search"` |
| `"vault_query"` | `"brain_query"` |
| `"vault_create"` | `"brain_create"` |
| `"vault_related"` | `"brain_related"` |
| `vault_path` (parameter and attribute names) | `brain_path` |
| `"vault-mcp-server"` (Server name string) | `"brain-mcp-server"` |

Also update the tool descriptions — change any mention of "vault" in description strings to "brain".

**Step 3: Update brain_index.py — rename internal references**

In `tools/brain_index.py`, replace:
- `"vault-index"` → `"brain-index"` (in usage docstring)
- `VAULT_PATH` env var references → `BRAIN_PATH`
- `vault_path` variable names → `brain_path`

**Step 4: Update brain_search.py — rename internal references**

In `tools/brain_search.py`:
- `"vault-search"` in docstring/description → `"brain-search"`
- `"vault"` in argparse description → `"brain"`

**Step 5: Update lib/config.py**

Replace the entire file content:

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
        self.brain_path = os.environ.get("BRAIN_PATH", "/brain")

    @property
    def db_path(self):
        return f"{self.brain_path}/.ai/embeddings.db"
```

**Step 6: Verify no remaining `vault` references in Python files**

```bash
grep -r "vault" tools/ --include="*.py" | grep -v "__pycache__"
```

Expected: no matches (or only in comments that are intentionally kept).

**Step 7: Commit**

```bash
git add tools/
git commit -m "refactor: rename vault→brain in Python modules and lib/config"
```

---

### Task 2: Rename entrypoints

**Files:**
- Rename: `tools/vault-mcp-server` → `tools/brain-mcp-server`
- Rename: `tools/vault-index` → `tools/brain-index`
- Rename: `tools/vault-search` → `tools/brain-search`
- Rename: `tools/vault-init` → `tools/brain-init`

**Step 1: Rename the entrypoint files**

```bash
git mv tools/vault-mcp-server tools/brain-mcp-server
git mv tools/vault-index tools/brain-index
git mv tools/vault-search tools/brain-search
git mv tools/vault-init tools/brain-init
```

**Step 2: Update brain-mcp-server**

```python
#!/usr/bin/env python3
from brain_mcp_server import main
main()
```

**Step 3: Update brain-index**

```python
#!/usr/bin/env python3
"""brain-index: index second-brain notes into sqlite-vec for semantic search.

Usage:
  brain-index run    Full reindex of all markdown files
  brain-index watch  Watch for changes and reindex incrementally
"""
from brain_index import main

if __name__ == "__main__":
    main()
```

**Step 4: Update brain-search**

```python
#!/usr/bin/env python3
from brain_search import main
main()
```

**Step 5: Update brain-init — full content**

```python
#!/usr/bin/env python3
"""brain-init: initialise a second-brain for use with brain tools.

Copies .zk config and templates into the brain directory.
Creates .ai directory for embeddings.
Idempotent — safe to run multiple times.
"""
import os
import shutil
import sys

# Source zk config: relative to this script in the repo, or baked path in container
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
_ZK_SOURCE_CANDIDATES = [
    os.path.join(_REPO_ROOT, "zk"),            # local dev
    "/usr/local/lib/brain-tools/zk",           # inside container
]


def init_brain(brain_path: str) -> None:
    zk_source = next((p for p in _ZK_SOURCE_CANDIDATES if os.path.isdir(p)), None)
    if zk_source is None:
        print("Error: could not find zk config source directory.", file=sys.stderr)
        sys.exit(1)

    zk_dest = os.path.join(brain_path, ".zk")
    ai_dest = os.path.join(brain_path, ".ai")

    if os.path.isdir(zk_dest):
        print(f".zk already exists at {zk_dest}, skipping.")
    else:
        shutil.copytree(zk_source, zk_dest)
        print(f"Created {zk_dest}")

    os.makedirs(ai_dest, exist_ok=True)
    print(f"Ensured {ai_dest} exists")
    print("Brain initialised.")


if __name__ == "__main__":
    brain_path = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("BRAIN_PATH", "/brain")
    if not os.path.isdir(brain_path):
        print(f"Error: brain path does not exist: {brain_path}", file=sys.stderr)
        sys.exit(1)
    init_brain(brain_path)
```

**Step 6: Commit**

```bash
git add tools/
git commit -m "refactor: rename vault→brain entrypoints"
```

---

### Task 3: Update Dockerfile and infrastructure

**Files:**
- Modify: `Dockerfile`
- Modify: `docker-compose.yml`
- Modify: `docker-compose.override.yml`
- Modify: `.mcp.json`

**Step 1: Update Dockerfile**

Changes needed:
- `/usr/local/lib/vault-tools/` → `/usr/local/lib/brain-tools/`
- All four entrypoint names in `RUN chmod +x`
- `ENV PATH` value
- `ENV PYTHONPATH` value
- `WORKDIR /vault` → `WORKDIR /brain`

The tools section of the Dockerfile should become:

```dockerfile
# Brain tools
COPY tools/ /usr/local/lib/brain-tools/
COPY zk/ /usr/local/lib/brain-tools/zk/
RUN chmod +x /usr/local/lib/brain-tools/brain-index \
              /usr/local/lib/brain-tools/brain-search \
              /usr/local/lib/brain-tools/brain-mcp-server \
              /usr/local/lib/brain-tools/brain-init

# Add tools to PATH and Python path
ENV PATH="/usr/local/lib/brain-tools:$PATH"
ENV PYTHONPATH="/usr/local/lib/brain-tools"

WORKDIR /brain
CMD ["zsh"]
```

**Step 2: Update docker-compose.yml**

```yaml
services:
  brain:
    image: kitchencoder/second-brain:latest
    container_name: brain
    volumes:
      - ${BRAIN_HOST_PATH:-~/Documents/Vault33}:/brain
    env_file:
      - .env
    stdin_open: true
    tty: true
    restart: unless-stopped
```

**Step 3: Update docker-compose.override.yml**

```yaml
# Local development override — builds image from source instead of pulling.
# This file is gitignored; copy it manually when developing.
services:
  brain:
    build: .
    image: second-brain-dev
```

**Step 4: Update .mcp.json**

```json
{
  "mcpServers": {
    "brain": {
      "command": "docker",
      "args": ["exec", "-i", "brain", "brain-mcp-server"]
    }
  }
}
```

**Step 5: Commit**

```bash
git add Dockerfile docker-compose.yml docker-compose.override.yml .mcp.json
git commit -m "refactor: rename vault→brain in Dockerfile and infrastructure"
```

---

### Task 4: Update unit tests

**Files:**
- Rename: `tests/test_vault_mcp_server.py` → `tests/test_brain_mcp_server.py`
- Rename: `tests/test_vault_index.py` → `tests/test_brain_index.py`
- Rename: `tests/test_vault_search.py` → `tests/test_brain_search.py`

**Step 1: Rename test files**

```bash
git mv tests/test_vault_mcp_server.py tests/test_brain_mcp_server.py
git mv tests/test_vault_index.py tests/test_brain_index.py
git mv tests/test_vault_search.py tests/test_brain_search.py
```

**Step 2: Update test_brain_mcp_server.py imports and references**

Change the import line:
```python
# Old
from vault_mcp_server import handle_vault_search, handle_vault_query, handle_vault_related

# New
from brain_mcp_server import handle_brain_search, handle_brain_query, handle_brain_related
```

Update all function call references throughout the file:
- `handle_vault_search(` → `handle_brain_search(`
- `handle_vault_query(` → `handle_brain_query(`
- `handle_vault_related(` → `handle_brain_related(`

**Step 3: Update test_brain_index.py imports**

```python
# Old
from vault_index import index_vault, index_file

# New
from brain_index import index_vault, index_file
```

**Step 4: Update test_brain_search.py imports**

```python
# Old
from vault_search import format_result, search

# New
from brain_search import format_result, search
```

**Step 5: Run unit tests to verify they pass**

```bash
cd /Users/chris/projects/second-brain
source .venv/bin/activate
pytest -m "not integration" -v
```

Expected: 29 passed, 0 failed.

**Step 6: Commit**

```bash
git add tests/
git commit -m "refactor: rename vault→brain in unit tests"
```

---

### Task 5: Update integration tests

**Files:**
- Modify: `tests/test_integration.py`

**Step 1: Update test_integration.py — full replacement**

Every `vault` reference becomes `brain`. Here is the complete updated file:

```python
"""Integration tests for Phase 1 of the co-dependent confabulation roadmap.

Requires:
- Docker running
- kitchencoder/second-brain image built locally (docker build -t kitchencoder/second-brain .)
  OR pulled from Docker Hub
- Docker Model Runner running with an embedding model available

Run with:
    pytest -m integration -v

Skip in unit-test-only mode:
    pytest -m "not integration"
"""
import os
import pytest
from pathlib import Path

FIXTURE_BRAIN = Path(__file__).parent / "fixtures" / "vault"
IMAGE = os.environ.get("SECOND_BRAIN_IMAGE", "kitchencoder/second-brain:latest")
EMBEDDING_BASE_URL = os.environ.get(
    "EMBEDDING_BASE_URL",
    "http://model-runner.docker.internal/engines/llama.cpp/v1"
)
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "mxbai-embed-large")


@pytest.fixture(scope="session")
def brain_container():
    """Start the brain container with fixture brain mounted, run brain-index, yield container."""
    from testcontainers.core.container import DockerContainer

    container = (
        DockerContainer(IMAGE)
        .with_command("sleep infinity")
        .with_volume_mapping(str(FIXTURE_BRAIN.resolve()), "/brain", "rw")
        .with_env("EMBEDDING_BASE_URL", EMBEDDING_BASE_URL)
        .with_env("EMBEDDING_MODEL", EMBEDDING_MODEL)
        .with_env("BRAIN_PATH", "/brain")
    )

    with container:
        # Check embedding model is reachable before spending time indexing
        exit_code, output = container.exec(
            f"python3 -c \""
            f"from openai import OpenAI; "
            f"c = OpenAI(base_url='{EMBEDDING_BASE_URL}', api_key='local'); "
            f"c.embeddings.create(input='test', model='{EMBEDDING_MODEL}')"
            f"\""
        )
        if exit_code != 0:
            pytest.skip(
                f"Embedding model unavailable at {EMBEDDING_BASE_URL} — skipping integration tests"
            )

        # Run full index
        exit_code, output = container.exec("brain-index run")
        assert exit_code == 0, f"brain-index failed:\n{output.decode()}"

        yield container

    # Cleanup: remove the generated embeddings DB from the fixture brain
    db = FIXTURE_BRAIN / ".ai" / "embeddings.db"
    if db.exists():
        db.unlink()
    ai_dir = FIXTURE_BRAIN / ".ai"
    if ai_dir.exists() and not any(ai_dir.iterdir()):
        ai_dir.rmdir()


def _exec(container, cmd: str) -> str:
    """Run a command in the container and return stdout. Fails test on non-zero exit."""
    exit_code, output = container.exec(cmd)
    assert exit_code == 0, f"Command failed: {cmd}\n{output.decode()}"
    return output.decode()


@pytest.mark.integration
def test_search_returns_confabulation_note_with_frontmatter(brain_container):
    """brain_search('co-dependent confabulation') returns the context note with full frontmatter."""
    result = _exec(
        brain_container,
        "python3 -c \""
        "from brain_mcp_server import handle_brain_search; "
        "from lib.config import Config; "
        "cfg = Config(); "
        "print(handle_brain_search('co-dependent confabulation', 5, cfg.db_path))"
        "\""
    )
    assert "Co-dependent Confabulation" in result
    assert "epistemic-lens" in result
    assert "context-primer" in result
    assert "2026-03-15" in result


@pytest.mark.integration
def test_query_by_tag_returns_epistemic_lens_documents(brain_container):
    """brain_query(tag='epistemic-lens') returns all documents tagged epistemic-lens."""
    result = _exec(
        brain_container,
        "python3 -c \""
        "from brain_mcp_server import handle_brain_query; "
        "print(handle_brain_query(tag='epistemic-lens', status=None, type=None, brain_path='/brain'))"
        "\""
    )
    assert "context-co-dependent-confabulation" in result
    assert "strange-loops" in result


@pytest.mark.integration
def test_related_returns_distinct_files_not_repeated_chunks(brain_container):
    """brain_related returns the cognitive debt summary and strange loops as distinct files."""
    result = _exec(
        brain_container,
        "python3 -c \""
        "from brain_mcp_server import handle_brain_related; "
        "from lib.config import Config; "
        "cfg = Config(); "
        "filepath = '/brain/Projects/confabulation/context-co-dependent-confabulation.md'; "
        "print(handle_brain_related(filepath, 5, cfg.db_path, cfg.brain_path))"
        "\""
    )
    assert result.count("cognitive-debt-paper-summary") == 1
    assert result.count("strange-loops") == 1


@pytest.mark.integration
def test_templates_not_indexed(brain_container):
    """Files under templates/ must not appear in the index."""
    result = _exec(
        brain_container,
        "python3 -c \""
        "import sqlite3, sqlite_vec; "
        "db = '/brain/.ai/embeddings.db'; "
        "conn = sqlite3.connect(db); "
        "conn.enable_load_extension(True); "
        "sqlite_vec.load(conn); "
        "conn.enable_load_extension(False); "
        "rows = conn.execute(\\\"SELECT COUNT(*) FROM chunks WHERE filepath LIKE '%/templates/%'\\\").fetchone(); "
        "print(rows[0])"
        "\""
    )
    assert result.strip() == "0", f"Expected 0 template chunks, got: {result.strip()}"
```

**Step 2: Run unit tests to confirm no regressions**

```bash
pytest -m "not integration" -v
```

Expected: 29 passed.

**Step 3: Commit**

```bash
git add tests/test_integration.py
git commit -m "refactor: rename vault→brain in integration tests"
```

---

### Task 6: Rebuild container and verify

**Step 1: Stop the running container**

```bash
docker compose down
```

**Step 2: Rebuild with local dev override**

```bash
docker compose -f docker-compose.yml -f docker-compose.override.yml up -d --build
```

Expected: builds successfully, container named `brain` starts.

**Step 3: Verify the container is running**

```bash
docker compose ps
```

Expected: `brain` container with status `running`.

**Step 4: Verify brain tools are on PATH**

```bash
docker exec brain brain-index --help 2>&1 | head -5
docker exec brain brain-search --help 2>&1 | head -5
```

Expected: help text shown (not "command not found").

**Step 5: Verify unit tests still pass**

```bash
pytest -m "not integration" -v
```

Expected: 29 passed.

**Step 6: Commit**

```bash
git add .
git status  # confirm nothing unexpected
git commit -m "refactor: complete vault→brain rename" --allow-empty
git push
```

---

### Task 7: Write the four skills

**Files:**
- Create: `skills/README.md`
- Create: `skills/brain-context/SKILL.md`
- Create: `skills/brain-save/SKILL.md`
- Create: `skills/brain-project/SKILL.md`
- Create: `skills/brain-hygiene/SKILL.md`

**Step 1: Create skills/README.md**

```markdown
# second-brain Skills for Claude Code

These skills give Claude Code the ability to use your second-brain without any configuration beyond the MCP server being connected.

## Install

Copy the skill directories to your Claude skills folder:

```bash
cp -r skills/brain-* ~/.claude/skills/
```

## Skills

| Skill | Trigger | What it does |
|-------|---------|--------------|
| `brain-context` | Working on a topic/project | Searches the brain for prior context before starting work |
| `brain-save` | "remember", "save", "capture" | Saves something to the brain with correct frontmatter |
| `brain-project` | "start a new project" | Scaffolds a new project with context primer + project note |
| `brain-hygiene` | "tidy", "audit", "health-check" | Checks frontmatter completeness, orphans, broken links, stale drafts |

## Requirements

- The `brain` MCP server must be connected in Claude Code (`.mcp.json` configured)
- The brain container must be running (`docker compose up -d`)
```

**Step 2: Create skills/brain-context/SKILL.md**

```markdown
---
name: brain-context
description: Use when the user mentions a topic, project name, or concept they want to work on — searches the second-brain for prior context before starting work.
---

# Brain Context

Before starting work on a topic, search the second-brain to surface what's already been established.

## When to Use

Invoke when the user names a project, concept, or topic they want to work on. Do not invoke at every session start — only when there is a concrete subject to search for.

## Steps

1. Run `brain_search(query)` using the topic as the query
2. If a tag can be inferred from the topic, also run `brain_query(tag=<slug>)`
3. If a related filepath is known, run `brain_related(filepath)` to find connected notes
4. Surface results with full frontmatter — present type, status, created, tags for each result

## Interpreting Results

| `status` value | Meaning |
|---------------|---------|
| `current` | Established — treat as reliable context |
| `draft` | Speculative — flag as work in progress |
| `archived` | Historical — may be superseded |

## Rules

- If nothing is found, say so explicitly. Do not invent context.
- Do not re-derive or re-explain concepts that exist in the brain — use what is there.
- Empty results are not a failure — they mean this topic is new to the brain.
```

**Step 3: Create skills/brain-save/SKILL.md**

```markdown
---
name: brain-save
description: Use when the user says "remember", "save", "capture", "note down", or asks Claude to record something for future sessions.
---

# Brain Save

Save something to the second-brain with correct frontmatter and placement.

## Steps

1. Run `brain_search` on the topic to check if a note already exists — offer to update it rather than create a duplicate
2. Use Glob to scan the top-level folder structure of the brain and infer where similar content lives — suggest a location based on existing patterns
3. Agree the location with the user if ambiguous
4. Create the note via `brain_create(template, title)`
5. Write frontmatter with exactly these fields:

```yaml
type:     # infer from content — ask if unclear
title:    # human-readable, descriptive
status:   # draft | current | archived
created:  # today YYYY-MM-DD
tags:     # array, lowercase, hyphenated — at least one tag
```

6. Write the body: exactly what was asked to be saved, nothing more
7. Add wikilinks to related notes found in step 1

## Rules

- **No invented fields.** Only the five above unless the user explicitly requests more.
- **No elaboration.** Write what was asked, stop there.
- **No folder invention.** Infer location from existing vault structure — do not create new top-level folders.
- **Check first.** Always search before creating. A duplicate is worse than an update.
```

**Step 4: Create skills/brain-project/SKILL.md**

```markdown
---
name: brain-project
description: Use when the user says "start a new project", "set up a project", or asks to scaffold new work in the second-brain.
---

# Brain Project

Scaffold a new project in the second-brain with two seed documents.

## Steps

1. Ask for a project name if not provided. Derive a kebab-case slug (e.g. `my-project-name`).
2. Use Glob to scan the brain structure — find where existing projects live and what documents they contain. Follow the established pattern.
3. Run `brain_search` on the project topic to find any prior related work.
4. Create two notes via `brain_create`:

### Note 1: Context Primer

Template: `context-primer` (or the closest available template)

```yaml
type: context-primer
title: "<Project Name> — Context"
status: draft
created: <today YYYY-MM-DD>
tags: [<project-slug>, context]
```

Body: problem statement, goals, key decisions made so far, links to related prior work found in step 3.

### Note 2: Project / Effort Note

Template: `project` or `effort` (whichever the brain uses)

```yaml
type: project
title: "<Project Name>"
status: draft
created: <today YYYY-MM-DD>
tags: [<project-slug>]
```

Body: current phase, active work items, wikilink to the context primer.

5. Add wikilinks between the two notes.
6. Report what was created and how to query the project later:
   ```
   brain_query(tag="<project-slug>")
   ```

## Rules

- **Two documents minimum, two maximum** unless the user asks for more.
- **Tag both** with the project slug so the full thread is queryable.
- **No invented content.** Populate from what the user has provided and what `brain_search` returns.
- **Follow existing patterns.** Do not invent a folder structure that doesn't match the brain.
```

**Step 5: Create skills/brain-hygiene/SKILL.md**

```markdown
---
name: brain-hygiene
description: Use when asked to tidy, audit, or health-check the second-brain — checks frontmatter completeness, orphaned notes, broken wikilinks, and stale drafts.
---

# Brain Hygiene

Systematic audit of the second-brain. Four checks in order. Fix what is unambiguous; flag everything else.

## Check 1: Frontmatter Completeness

Use Glob to find all `.md` files excluding the `templates/` directory. Read each file. Flag any missing one or more of these required fields:

```
type, title, status, created, tags
```

**Fix:** if `created` is missing and the file has a filesystem mtime, use that date. For all other missing fields, propose a value based on the content and ask before writing.

**Do not** batch-fix without reading the content first.

## Check 2: Orphaned Notes

**Outbound orphans:** Use Grep to find `.md` files containing no `[[wikilinks]]`. These notes link to nothing.

**Inbound orphans:** Build a list of all filenames (without extension). Grep for `[[filename]]` patterns across all files. Notes with no inbound links are unreferenced.

Report both sets with title and path. Do not delete.

## Check 3: Broken Wikilink Targets

1. Build a filename index: collect all `.md` filenames (without extension) via Glob
2. Grep all files for `[[...]]` patterns
3. For each target, check if it exists in the index
4. Flag any target not found — do not create stub documents

## Check 4: Stale Drafts

Run `brain_query(status=draft)`. Report each result with its title and `created` date.

Present to the user for a decision on each: promote to `current`, move to `archived`, or delete.

**Do not auto-promote.** Drafts are promoted by the human.

---

## Fix vs Flag

| Issue | Action |
|-------|--------|
| Missing `created` (mtime available) | Fix |
| Missing `type`, `title`, `status`, `tags` | Propose + ask |
| Outbound orphan (no links out) | Flag |
| Inbound orphan (nothing links to it) | Flag |
| Broken wikilink target | Flag — do not create stub |
| Stale draft | Flag — do not auto-promote |
| Empty file | Flag — do not delete without confirmation |

## Rules

- Read the file before proposing any fix.
- Never delete anything without explicit user confirmation.
- Never create stub documents for missing wikilink targets.
- Never auto-promote `status: draft` notes.
```

**Step 6: Verify skill files are well-formed**

Each SKILL.md must have:
- A frontmatter block with `name:` and `description:`
- A `#` heading
- No references to Obsidian, Vault33, or specific vault paths

```bash
grep -r "Obsidian\|Vault33\|vault33\|/Users/chris" skills/
```

Expected: no matches.

**Step 7: Commit**

```bash
git add skills/
git commit -m "feat: add brain-context, brain-save, brain-project, brain-hygiene skills"
git push
```
