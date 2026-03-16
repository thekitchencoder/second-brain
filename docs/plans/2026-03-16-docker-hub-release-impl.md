# Docker Hub Release Pipeline + Integration Tests — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a GitHub repo, release pipeline to `kitchencoder/second-brain` on Docker Hub, and testcontainers-based integration tests verifying Phase 1 of the co-dependent confabulation roadmap.

**Architecture:** GitHub Actions triggers on published release, syncs version to `pyproject.toml` and `Dockerfile LABEL`, then builds/pushes multi-tag image. Integration tests use testcontainers to spin up the real image with a fixture vault, run `vault-index`, then assert on MCP tool outputs via `docker exec`.

**Tech Stack:** GitHub Actions, Docker Buildx, testcontainers-python, pytest, `kitchencoder/second-brain` image, `thekitchencoder/second-brain` GitHub repo.

---

### Task 1: Create the GitHub repository

**Files:**
- No file changes — CLI only

**Step 1: Create the repo**

```bash
gh repo create thekitchencoder/second-brain --public --description "Docker-packaged markdown vault with semantic search and Claude Code MCP integration" --source . --remote origin
```

Expected: repo created, remote `origin` added.

**Step 2: Push**

```bash
git push -u origin main
```

Expected: all commits pushed, branch tracking set.

**Step 3: Verify**

```bash
gh repo view thekitchencoder/second-brain
```

Expected: repo page shown with description.

---

### Task 2: Add version LABEL to Dockerfile

**Files:**
- Modify: `Dockerfile`

**Step 1: Add the LABEL line**

After the `FROM python:3.12-slim` line, add:

```dockerfile
LABEL version="0.1.0"
```

So the top of the Dockerfile becomes:

```dockerfile
FROM python:3.12-slim

LABEL version="0.1.0"

ARG ZK_VERSION=0.14.1
```

**Step 2: Verify it builds**

```bash
docker build -t second-brain-test .
```

Expected: build succeeds. (Will take a few minutes due to sqlite-vec compilation.)

**Step 3: Commit**

```bash
git add Dockerfile
git commit -m "feat: add version LABEL to Dockerfile"
```

---

### Task 3: Add sync-version.sh

**Files:**
- Create: `scripts/sync-version.sh`

**Step 1: Create the scripts directory and script**

```bash
mkdir -p scripts
```

`scripts/sync-version.sh`:

```bash
#!/usr/bin/env bash
# Syncs the version from pyproject.toml into Dockerfile LABEL
# Run after updating pyproject.toml version field.
set -euo pipefail

VERSION=$(grep '^version' pyproject.toml | sed 's/version = "\(.*\)"/\1/')
echo "Syncing version $VERSION to Dockerfile..."
sed -i "s/^LABEL version=.*/LABEL version=\"$VERSION\"/" Dockerfile
echo "Done."
```

**Step 2: Make it executable**

```bash
chmod +x scripts/sync-version.sh
```

**Step 3: Test it**

```bash
# Check current state
grep 'LABEL version' Dockerfile

# Run the script
./scripts/sync-version.sh

# Verify no change (versions already match)
grep 'LABEL version' Dockerfile
```

Expected: no change, script exits cleanly.

**Step 4: Commit**

```bash
git add scripts/sync-version.sh
git commit -m "feat: add sync-version.sh to keep Dockerfile LABEL in sync with pyproject.toml"
```

---

### Task 4: Update docker-compose.yml and .gitignore

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.gitignore`
- Create: `docker-compose.override.yml`

**Step 1: Update docker-compose.yml to use published image by default**

Replace the `build: .` line with `image: kitchencoder/second-brain:latest` and add a comment explaining the override pattern:

```yaml
services:
  vault:
    image: kitchencoder/second-brain:latest
    container_name: vault
    volumes:
      - ${VAULT_HOST_PATH:-~/Documents/Vault33}:/vault
    env_file:
      - .env
    stdin_open: true
    tty: true
    restart: unless-stopped
```

**Step 2: Create docker-compose.override.yml for local dev**

```yaml
# Local development override — builds image from source instead of pulling.
# This file is gitignored; copy it manually when developing.
services:
  vault:
    build: .
    image: second-brain-dev
```

**Step 3: Add to .gitignore**

Append to `.gitignore`:

```
docker-compose.override.yml
```

**Step 4: Verify compose still works with override**

```bash
# With override (dev mode)
docker compose -f docker-compose.yml -f docker-compose.override.yml up -d
docker compose ps
docker compose down
```

Expected: container starts using local build.

**Step 5: Commit**

```bash
git add docker-compose.yml .gitignore
git commit -m "feat: switch docker-compose to published image, add override pattern for local dev"
```

---

### Task 5: Add GitHub Actions release workflow

**Files:**
- Create: `.github/workflows/docker-release.yml`

**Step 1: Create the workflow directory and file**

```bash
mkdir -p .github/workflows
```

`.github/workflows/docker-release.yml`:

```yaml
name: Build and Push Docker Image

on:
  release:
    types: [published]

env:
  REGISTRY: docker.io
  IMAGE_NAME: kitchencoder/second-brain

jobs:
  sync-version:
    runs-on: ubuntu-latest
    permissions:
      contents: write

    steps:
      - name: Checkout code
        uses: actions/checkout@v4
        with:
          token: ${{ secrets.GITHUB_TOKEN }}

      - name: Extract version from tag
        id: get_version
        run: |
          VERSION=${GITHUB_REF#refs/tags/v}
          echo "version=$VERSION" >> $GITHUB_OUTPUT
          echo "Extracted version: $VERSION"

      - name: Update version in pyproject.toml
        run: |
          VERSION=${{ steps.get_version.outputs.version }}
          sed -i "s/^version = .*/version = \"$VERSION\"/" pyproject.toml
          echo "Updated pyproject.toml to version $VERSION"

      - name: Sync version to Dockerfile
        run: |
          chmod +x scripts/sync-version.sh
          ./scripts/sync-version.sh

      - name: Commit version updates
        run: |
          git config --local user.email "github-actions[bot]@users.noreply.github.com"
          git config --local user.name "github-actions[bot]"
          git add pyproject.toml Dockerfile
          git diff --staged --quiet || git commit -m "chore: bump version to ${{ steps.get_version.outputs.version }}"

      - name: Push changes
        uses: ad-m/github-push-action@master
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          branch: ${{ github.event.release.target_commitish }}

  docker:
    runs-on: ubuntu-latest
    needs: sync-version
    permissions:
      contents: read
      packages: write

    steps:
      - name: Checkout code
        uses: actions/checkout@v4
        with:
          ref: ${{ github.event.release.target_commitish }}

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to Docker Hub
        uses: docker/login-action@v3
        with:
          username: ${{ secrets.DOCKER_USERNAME }}
          password: ${{ secrets.DOCKER_PASSWORD }}

      - name: Extract metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}
          tags: |
            type=semver,pattern={{version}}
            type=semver,pattern={{major}}.{{minor}}
            type=semver,pattern={{major}}
            type=raw,value=latest

      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
```

**Step 2: Add Docker Hub secrets to the repo**

```bash
gh secret set DOCKER_USERNAME --body "kitchencoder"
# DOCKER_PASSWORD: set this via the GitHub UI with a Docker Hub access token
# (Hub → Account Settings → Security → New Access Token)
```

**Step 3: Commit**

```bash
git add .github/workflows/docker-release.yml
git commit -m "feat: add GitHub Actions release workflow for Docker Hub"
git push
```

---

### Task 6: Create the fixture vault

**Files:**
- Create: `tests/fixtures/vault/.zk/config.toml`
- Create: `tests/fixtures/vault/Projects/confabulation/context-co-dependent-confabulation.md`
- Create: `tests/fixtures/vault/Sources/cognitive-debt-paper-summary.md`
- Create: `tests/fixtures/vault/Cards/strange-loops.md`
- Create: `tests/fixtures/vault/templates/example.md`

**Step 1: Create the zk config**

`tests/fixtures/vault/.zk/config.toml`:

```toml
[note]
filename = "{{slug title}}"
extension = "md"
default-title = "Untitled"

[tool]
fzf-preview = "bat -p --color always {-1}"
```

**Step 2: Create the confabulation context note**

`tests/fixtures/vault/Projects/confabulation/context-co-dependent-confabulation.md`:

```markdown
---
type: context-primer
title: "Co-dependent Confabulation and Homeostatic Control"
status: draft
created: 2026-03-15
tags: [epistemic-lens, confabulation, homeostasis, control-theory]
---

# Co-dependent Confabulation and Homeostatic Control

Co-dependent confabulation is a self-reinforcing loop in which human and AI each accept and elaborate the other's framings, producing output that feels true but may not be independently grounded.

The phenomenon operates as a homeostatic control failure: the system settles into a stable but inaccurate equilibrium because both participants are providing damping signals rather than corrective signals.

## Candidate Convergence Signatures

- Vocabulary convergence: human adopts LLM-characteristic phrasing over time
- Declining disagreement rate: challenges decrease as agreement increases
- Mutual enthusiasm markers: "exactly", "precisely", "that's it"
- Framework elaboration without falsification

## Related Notes

- [[roadmap-co-dependent-confabulation-experiments]]
- [[cognitive-debt-paper-summary]]
- [[strange-loops]]
```

**Step 3: Create the cognitive debt source note**

`tests/fixtures/vault/Sources/cognitive-debt-paper-summary.md`:

```markdown
---
type: source
title: "Cognitive Debt: Your Brain on AI — Paper Summary"
status: current
created: 2026-03-11
tags: [source, ai, cognition, neuroscience, research]
---

# Cognitive Debt: Your Brain on AI

Summary of Kosmyna et al. research on cognitive offloading to AI tools.

Key finding: participants who used LLM assistance showed reduced neural engagement in frontal regions associated with independent reasoning. The effect persisted after LLM assistance was removed.

The delta band, typically linked with homeostatic and motivational processes, reflected deeper frontal-subcortical control engagement in the Search Engine group compared to the LLM group.

This provides empirical support for the damping signal degradation hypothesis: sustained reliance on AI for generative tasks reduces the human's capacity to provide corrective signals.

## Related Notes

- [[context-co-dependent-confabulation]]
- [[strange-loops]]
```

**Step 4: Create the strange loops card**

`tests/fixtures/vault/Cards/strange-loops.md`:

```markdown
---
type: context-primer
title: "Strange Loops and Reflecting Pools"
status: current
created: 2026-03-01
tags: [ai, philosophy, systems, epistemic-lens]
---

# Strange Loops and Reflecting Pools

A reflection on the design principles that emerge when AI systems are used as thinking partners rather than answer machines.

The core risk: a system that reflects your own thinking back at you with high fidelity will feel like independent confirmation. The pool is still water. The loop is still closed.

Design principle: build for disagreement, not consensus. An AI that never challenges you isn't a thinking partner — it's a mirror.

## Related Notes

- [[context-co-dependent-confabulation]]
- [[cognitive-debt-paper-summary]]
```

**Step 5: Create the template file (must NOT be indexed)**

`tests/fixtures/vault/templates/example.md`:

```markdown
---
title: "{{title}}"
type: note
status: draft
created: "{{date}}"
tags: []
---

# {{title}}

## Purpose

## Notes
```

**Step 6: Commit**

```bash
git add tests/fixtures/
git commit -m "test: add fixture vault for integration tests"
```

---

### Task 7: Add testcontainers and integration tests

**Files:**
- Modify: `requirements.txt`
- Modify: `pyproject.toml`
- Create: `tests/test_integration.py`

**Step 1: Add testcontainers to requirements.txt**

Add to `requirements.txt`:

```
testcontainers>=4.0.0
```

Install locally:

```bash
pip install testcontainers
```

**Step 2: Add pytest marker config to pyproject.toml**

Add `integration` to the markers list:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["tools"]
markers = ["integration: requires Docker and a running embedding model (deselect with '-m not integration')"]
```

**Step 3: Write the integration tests**

`tests/test_integration.py`:

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
import subprocess
import pytest
from pathlib import Path

FIXTURE_VAULT = Path(__file__).parent / "fixtures" / "vault"
IMAGE = os.environ.get("SECOND_BRAIN_IMAGE", "kitchencoder/second-brain:latest")
EMBEDDING_BASE_URL = os.environ.get(
    "EMBEDDING_BASE_URL",
    "http://model-runner.docker.internal/engines/llama.cpp/v1"
)
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "mxbai-embed-large")


@pytest.fixture(scope="session")
def vault_container():
    """Start the vault container with fixture vault mounted, run vault-index, yield container name."""
    from testcontainers.core.container import DockerContainer

    container = (
        DockerContainer(IMAGE)
        .with_volume_mapping(str(FIXTURE_VAULT.resolve()), "/vault", "rw")
        .with_env("EMBEDDING_BASE_URL", EMBEDDING_BASE_URL)
        .with_env("EMBEDDING_MODEL", EMBEDDING_MODEL)
        .with_env("VAULT_PATH", "/vault")
    )

    with container:
        # Check embedding model is reachable before spending time indexing
        exit_code, output = container.exec("python3 -c \""
            "from openai import OpenAI; "
            "c = OpenAI(base_url='\" + EMBEDDING_BASE_URL + \"', api_key='local'); "
            "c.embeddings.create(input='test', model='\" + EMBEDDING_MODEL + \"')"
            "\"")
        if exit_code != 0:
            pytest.skip(f"Embedding model unavailable at {EMBEDDING_BASE_URL} — skipping integration tests")

        # Run full index
        exit_code, output = container.exec("vault-index run")
        assert exit_code == 0, f"vault-index failed:\n{output.decode()}"

        yield container

    # Cleanup: remove the generated embeddings DB from the fixture vault
    db = FIXTURE_VAULT / ".ai" / "embeddings.db"
    if db.exists():
        db.unlink()
    ai_dir = FIXTURE_VAULT / ".ai"
    if ai_dir.exists() and not any(ai_dir.iterdir()):
        ai_dir.rmdir()


def _exec(container, cmd: str) -> str:
    """Run a command in the container and return stdout. Fails test on non-zero exit."""
    exit_code, output = container.exec(cmd)
    assert exit_code == 0, f"Command failed: {cmd}\n{output.decode()}"
    return output.decode()


@pytest.mark.integration
def test_search_returns_confabulation_note_with_frontmatter(vault_container):
    """vault_search('co-dependent confabulation') returns the context note with full frontmatter."""
    result = _exec(
        vault_container,
        "python3 -c \""
        "import sys; sys.path.insert(0, '/usr/local/lib/vault-tools'); "
        "from vault_mcp_server import handle_vault_search; "
        "from lib.config import Config; "
        "cfg = Config(); "
        "print(handle_vault_search('co-dependent confabulation', 5, cfg.db_path))"
        "\""
    )
    assert "Co-dependent Confabulation" in result
    assert "epistemic-lens" in result
    assert "context-primer" in result
    assert "2026-03-15" in result


@pytest.mark.integration
def test_query_by_tag_returns_epistemic_lens_documents(vault_container):
    """vault_query(tag='epistemic-lens') returns all documents tagged epistemic-lens."""
    result = _exec(
        vault_container,
        "python3 -c \""
        "import sys; sys.path.insert(0, '/usr/local/lib/vault-tools'); "
        "from vault_mcp_server import handle_vault_query; "
        "print(handle_vault_query(tag='epistemic-lens', status=None, type=None, vault_path='/vault'))"
        "\""
    )
    assert "context-co-dependent-confabulation" in result
    assert "strange-loops" in result


@pytest.mark.integration
def test_related_returns_distinct_files_not_repeated_chunks(vault_container):
    """vault_related returns the cognitive debt summary and strange loops as distinct files."""
    result = _exec(
        vault_container,
        "python3 -c \""
        "import sys; sys.path.insert(0, '/usr/local/lib/vault-tools'); "
        "from vault_mcp_server import handle_vault_related; "
        "from lib.config import Config; "
        "cfg = Config(); "
        "filepath = '/vault/Projects/confabulation/context-co-dependent-confabulation.md'; "
        "print(handle_vault_related(filepath, 5, cfg.db_path, cfg.vault_path))"
        "\""
    )
    # Each file should appear exactly once
    assert result.count("cognitive-debt-paper-summary") == 1
    assert result.count("strange-loops") == 1


@pytest.mark.integration
def test_templates_not_indexed(vault_container):
    """Files under templates/ must not appear in the index."""
    result = _exec(
        vault_container,
        "python3 -c \""
        "import sqlite3, sqlite_vec; "
        "db = '/vault/.ai/embeddings.db'; "
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

**Step 4: Verify unit tests still pass**

```bash
pytest -m "not integration" -v
```

Expected: all existing unit tests pass, integration tests skipped.

**Step 5: Commit**

```bash
git add requirements.txt pyproject.toml tests/test_integration.py
git commit -m "test: add testcontainers integration tests for Phase 1 roadmap criteria"
git push
```

---

### Task 8: Set Docker Hub secret and push everything

**Step 1: Set the DOCKER_PASSWORD secret**

Go to: https://hub.docker.com/settings/security → New Access Token → name it `github-actions-second-brain` → copy the token.

```bash
gh secret set DOCKER_PASSWORD
# paste the token when prompted
```

**Step 2: Verify both secrets are set**

```bash
gh secret list
```

Expected: `DOCKER_USERNAME` and `DOCKER_PASSWORD` both listed.

**Step 3: Push all commits**

```bash
git push
```

**Step 4: Tag and create a release to trigger the workflow**

```bash
git tag v0.1.0
git push origin v0.1.0
gh release create v0.1.0 --title "v0.1.0 — Initial release" --notes "First public release. Vault semantic search, MCP server for Claude Code, Docker TUI for enterprise environments."
```

Expected: GitHub Actions workflow triggers. Watch it:

```bash
gh run watch
```

**Step 5: Verify the image is on Docker Hub**

```bash
docker pull kitchencoder/second-brain:latest
docker run --rm kitchencoder/second-brain:latest zk --version
```

Expected: image pulls, zk version prints.
