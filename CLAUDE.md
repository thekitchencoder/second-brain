# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Repo Is

A Docker-packaged second-brain system: Python MCP server + semantic search + zk note-taking, designed to run as a persistent container. The container mounts a user's brain (markdown notes directory), indexes them into a SQLite+sqlite-vec embedding database, and exposes search/read/write tools via MCP (stdio or HTTP) and a FastAPI REST API.

## Development Setup

Use `task` (Taskfile) for all dev tasks. Set `BRAIN_HOST_PATH` in `.env.local` (gitignored) once:

```
# .env.local
BRAIN_HOST_PATH=/path/to/your/brain
```

Then:

```bash
task build       # Build dev image (layer-cached — fast after first build)
task up          # Start container (uses docker run directly, not compose)
task logs        # Tail logs
task shell       # Open zsh in container
task down        # Stop and remove container
```

`task up` bind-mounts `tools/lib/` and `zk/templates/` and sets `BRAIN_DEV=1`, so Python and template changes are live immediately. Skills are force-reseeded from the image on every restart.

### Base image dev (MCP + brain tools)

```bash
task build      # Build second-brain-dev:latest from Dockerfile
task up         # Start container — ports 7779 (API) and 7780 (MCP HTTP)
task down       # Stop and remove
task restart    # Restart (picks up entrypoint/skill changes)
task shell      # zsh shell inside container
task logs       # Tail container logs
```

### UI image dev (adds code-server + Claude Code)

```bash
task build-ui   # Build second-brain-ui:latest from Dockerfile.ui (run task build first)
task up-ui      # Start UI container — ports 7778 (code-server), 7779, 7780
task down-ui    # Stop and remove
task restart-ui # Restart
```

### Iterating without rebuilding

| What changed | Command | Notes |
|---|---|---|
| `tools/lib/*.py` | just save | bind-mounted — live immediately |
| `zk/templates/` | just save | bind-mounted — live immediately |
| `skills/`, `brain-skills/` | `task sync-skills` | copies to `~/.claude/skills/`; run `/reload` in Claude Code |
| Entrypoint or image env | `task restart` (or `restart-ui`) | skills auto-reseeded from image |
| Dockerfile changes | `task build && task restart` | full rebuild needed |
| Dockerfile.ui changes | `task build-ui && task restart-ui` | rebuild UI layer only |

## Testing

```bash
task test              # Unit tests in a container (full coverage)
task test-integration  # Integration tests (needs Docker Model Runner)
```

`task test` runs unit tests inside a throwaway container so SQLite/sqlite-vec tests pass (they skip on macOS system Python). `task test-integration` spins up a container via `testcontainers` and tests against a live embedding model. See `docs/testing.md` for details, dependencies, and fixture layout.

## Core Architecture

### Tools Layer (`tools/`)

Shell wrappers call into Python modules in `tools/lib/`:

- **`brain.py`** — Central service layer; all MCP tools and REST endpoints delegate here. Entry point for understanding any feature.
- **`db.py`** — SQLite + sqlite-vec integration (stored at `.ai/embeddings.db` inside the brain)
- **`edit.py`** — Surgical YAML/markdown editing: frontmatter fields, sections, find-replace, wikilink insertion
- **`embeddings.py`** — OpenAI-compatible client; uses local model-runner by default

Executables (`brain-init`, `brain-index`, `brain-search`, `brain-mcp-server`, `brain-api`) are thin shell wrappers that invoke Python modules. `brain-init` is a Python script with an interactive setup wizard (`brain-init`) and a non-interactive mode (`brain-init --auto`) used by the container entrypoint.

### MCP Server (`tools/brain-mcp-server`)

Two transports, can run simultaneously:
- **stdio** (default): `docker exec -i brain brain-mcp-server`
- **HTTP** (optional): Port 7780, enabled via `BRAIN_MCP_TRANSPORT=http`

Tools: `brain_search`, `brain_query`, `brain_read`, `brain_write`, `brain_create`, `brain_templates`, `brain_edit`, `brain_related`, `brain_backlinks`

### Skills System

Two tiers of Claude Code skills:
- **`skills/`** — Global skills (11): MCP-only, work from any host session via `claude plugin add`. Includes brain-capture, brain-connect, brain-context, brain-create-effort, brain-distil, brain-effort, brain-project, brain-save, brain-setup, brain-surface, brain-triage.
- **`brain-skills/`** — Brain-local skills (5): need direct filesystem access (mv, Glob, Edit). Includes brain-daily, brain-extract, brain-hygiene, brain-rename, brain-reorganise.

Both tiers are baked into the Docker image and seeded into `~/.claude/skills/` inside the container by `entrypoint.sh`. Global skills use MCP tools only; brain-local skills also use filesystem tools for structural operations. When editing skills, check both directories.

### Brain Structure Convention (ACE-aligned)

Notes are organized as `Atlas/`, `Efforts/`, `Cards/`, `Calendar/`, `Sources/`. Templates in `zk/templates/` define frontmatter schemas per note type. `brain-init` creates the brain scaffold including `.zk/`, `.ai/`, `.vscode/`, `.claude/skills/`, and optionally the ACE folder structure.

### Embedding Configuration

All model endpoints are configurable via `.env` in the brain root (generated by `brain-init` or created manually). The container entrypoint sources `<brain>/.env` on startup. Defaults point to Docker Model Runner at `model-runner.docker.internal`. The embedding model must match the dimensions stored in `embeddings.db` — changing models requires re-indexing.

## Key Files to Know

| File | Purpose |
|------|---------|
| `tools/lib/brain.py` | Core service — start here for any feature work |
| `tools/lib/edit.py` | Surgical note editing logic |
| `tools/setup.sh` | Shared container startup logic (brain env, seeding, watcher, MCP HTTP) |
| `tools/entrypoint.sh` | Base image entrypoint — sources setup.sh, execs brain-api |
| `tools/entrypoint-ui.sh` | UI image entrypoint — sources setup.sh, starts brain-api in bg, execs code-server |
| `Dockerfile` | Lean base image (MCP + brain tools, no code-server) |
| `Dockerfile.ui` | UI image — FROM base, adds code-server + Claude Code + extensions |
| `zk/config.toml` | zk notebook configuration |
| `prompts/setup.md` | Brain setup conventions and frontmatter rules |

## Release Process

Releases are cut via GitHub — the `docker-release.yml` workflow auto-syncs the version tag into `pyproject.toml`, `Dockerfile`, and `Dockerfile.ui`, then builds and pushes both `kitchencoder/second-brain:latest` (lean base) and `kitchencoder/second-brain:ui` (code-server layer) to Docker Hub.
