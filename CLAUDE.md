# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Repo Is

A Docker-packaged second-brain system: Python MCP server + semantic search + zk note-taking, designed to run as a persistent container. The container mounts a user's vault (markdown notes), indexes them into a SQLite+sqlite-vec embedding database, and exposes search/read/write tools via MCP (stdio or HTTP) and a FastAPI REST API.

## Development Setup

```bash
# Build and run dev container (uses docker-compose.override.yml to build from source)
BRAIN_HOST_PATH=/path/to/vault docker compose up

# Run with prebuilt image
BRAIN_HOST_PATH=/path/to/vault docker compose -f docker-compose.yml up
```

`BRAIN_HOST_PATH` must be exported in the shell before `docker compose up` — it is NOT in `.env`.

## Testing

```bash
# Unit tests (no Docker needed)
pytest -m "not integration"

# Single test file
pytest tests/test_brain_service.py

# All tests including integration (requires running container)
pytest
```

Test fixtures live in `tests/fixtures/vault/`. Python path includes `tools/` (set in `pyproject.toml`).

## Core Architecture

### Tools Layer (`tools/`)

Shell wrappers call into Python modules in `tools/lib/`:

- **`brain.py`** — Central service layer; all MCP tools and REST endpoints delegate here. Entry point for understanding any feature.
- **`db.py`** — SQLite + sqlite-vec integration (stored at `.ai/embeddings.db` inside the vault)
- **`edit.py`** — Surgical YAML/markdown editing: frontmatter fields, sections, find-replace, wikilink insertion
- **`embeddings.py`** — OpenAI-compatible client; uses local model-runner by default

Executables (`brain-init`, `brain-index`, `brain-search`, `brain-mcp-server`, `brain-api`) are thin shell wrappers that invoke Python modules.

### MCP Server (`tools/brain-mcp-server`)

Two transports, can run simultaneously:
- **stdio** (default): `docker exec -i brain brain-mcp-server`
- **HTTP** (optional): Port 7780, enabled via `BRAIN_MCP_TRANSPORT=http`

Tools: `brain_search`, `brain_query`, `brain_read`, `brain_write`, `brain_create`, `brain_templates`, `brain_edit`, `brain_related`, `brain_backlinks`

### Skills System

Two tiers of Claude Code skills:
- **`skills/`** — Global skills (install to `~/.claude/skills/` or symlink)
- **`brain-skills/`** — Vault-level skills (auto-load when Claude Code opens the vault directory)

Skills use MCP tools for semantic operations + direct filesystem access for file I/O. When editing skills, check both directories.

### Vault Structure Convention (ACE-aligned)

Notes are organized as `Atlas/`, `Efforts/`, `Cards/`, `Calendar/`, `Sources/`. Templates in `zk/templates/` define frontmatter schemas per note type. `brain-init` creates the vault scaffold including `.zk/`, `.ai/`, and `.vscode/` directories.

### Embedding Configuration

All model endpoints are configurable via `.env` (copy from `.env.example`). Defaults point to Docker Model Runner at `model-runner.docker.internal`. The embedding model must match the dimensions stored in `embeddings.db` — changing models requires re-indexing.

## Key Files to Know

| File | Purpose |
|------|---------|
| `tools/lib/brain.py` | Core service — start here for any feature work |
| `tools/lib/edit.py` | Surgical note editing logic |
| `docker-compose.override.yml` | Dev overrides (builds from source instead of pulling image) |
| `zk/config.toml` | zk notebook configuration |
| `.mcp.json` | MCP stdio client config for Claude Code |
| `prompts/setup.md` | Vault setup conventions and frontmatter rules |

## Release Process

Releases are cut via GitHub — the `docker-release.yml` workflow auto-syncs the version tag into `pyproject.toml` and `Dockerfile`, then pushes to Docker Hub as `kitchencoder/second-brain:latest`.
