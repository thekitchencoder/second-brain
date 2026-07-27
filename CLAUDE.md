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

`task up` bind-mounts `tools/lib/` and `profiles/ace/templates/` and sets `BRAIN_DEV=1`, so Python and template changes are live immediately. Skills are force-reseeded from the image on every restart.

### Base image dev (MCP + brain tools)

```bash
task build      # Build second-brain-dev:latest from Dockerfile
task up         # Start container — ports 7779 (API) and 7780 (MCP HTTP)
task down       # Stop and remove
task restart    # Restart (picks up entrypoint/skill changes)
task shell      # zsh shell inside container
task logs       # Tail container logs
```

### Iterating without rebuilding

| What changed | Command | Notes |
|---|---|---|
| `tools/lib/*.py` | just save | bind-mounted — live immediately |
| `profiles/ace/templates/` | just save | bind-mounted — live immediately |
| `profiles/ace/skills/` | `task sync-skills` | copies to `~/.claude/skills/`; run `/reload` in Claude Code |
| Entrypoint or image env | `task restart` | skills auto-reseeded from image |
| Dockerfile changes | `task build && task restart` | full rebuild needed |

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

Skills now live in the **profile**, not the top-level repo. The bundled `ace` profile (`profiles/ace/`) carries two tiers under `skills/`:
- **`skills/global/`** — 11 skills: MCP-only, work from any host session via the Claude Code plugin staged at `<brain>/.ai/brain-plugin/`. Includes brain-capture, brain-connect, brain-context, brain-create-effort, brain-distil, brain-effort, brain-project, brain-save, brain-setup, brain-surface, brain-triage.
- **`skills/vault/`** — 5 skills: need direct filesystem access (mv, Glob, Edit). Includes brain-daily, brain-extract, brain-hygiene, brain-rename, brain-reorganise.

`brain-init` resolves a profile into `<brain>/.brain/` (see "Profiles" below), copies the vault tier into `<brain>/.claude/skills/`, and stages the global tier (plus hooks and plugin identity) into `<brain>/.ai/brain-plugin/`. `tools/setup.sh`'s `seed_skills_from_profile` then copies both tiers from `<brain>/.brain/skills/{global,vault}` into the container's `~/.claude/skills/` on every start. When editing the bundled skills, edit them under `profiles/ace/skills/global/` or `profiles/ace/skills/vault/` — the old top-level `skills/`/`brain-skills/` directories no longer exist.

### Profiles

A brain is self-describing: everything skill-, template-, hook-, and plugin-identity-related is resolved from `<brain>/.brain/`, seeded once by `brain-init` (`resolve_profile` in `tools/brain-init`) and never hand-edited — it's reseeded/updated, not user-maintained.

Source precedence, resolved only when `<brain>/.brain/profile.toml` is absent:
1. A custom source — `brain-init --profile-repo <url-or-path>` or `-e BRAIN_PROFILE_REPO=<url-or-path>` for the container — git-cloned (URL or existing git repo) or copied (plain local dir) into `.brain/`.
2. The bundled `ace` profile (`profiles/ace/`, or `/usr/local/lib/brain-tools/profiles/ace` in the container) — copied in as the zero-config, offline default.

`brain-profile show` prints the active profile's identity and origin; `brain-profile update` runs `git pull --ff-only` against a cloned profile (a no-op for the bundled/copied default, which isn't a git clone).

### Brain Structure Convention (ACE-aligned)

Notes are organized as `Atlas/`, `Efforts/`, `Cards/`, `Calendar/`, `Sources/` — the bundled `ace` profile's `folders`. Templates in `profiles/ace/templates/` define frontmatter schemas per note type; `brain-init` copies them into `<brain>/.zk/templates/` and composes `<brain>/.zk/config.toml` from engine-owned zk infra plus the profile's `[zk]` conventions. `brain-init` creates the brain scaffold including `.brain/`, `.zk/`, `.ai/`, `.vscode/`, `.claude/skills/`, and optionally the ACE folder structure.

### Embedding Configuration

All model endpoints are configurable via `.env` in the brain root (generated by `brain-init` or created manually). The container entrypoint sources `<brain>/.env` on startup. Defaults point to Docker Model Runner at `model-runner.docker.internal`. The embedding model must match the dimensions stored in `embeddings.db` — changing models requires re-indexing.

## Key Files to Know

| File | Purpose |
|------|---------|
| `tools/lib/brain.py` | Core service — start here for any feature work |
| `tools/lib/edit.py` | Surgical note editing logic |
| `tools/setup.sh` | Shared container startup logic (brain env, seeding, watcher, MCP HTTP) |
| `tools/entrypoint.sh` | Base image entrypoint — sources setup.sh, execs brain-api |
| `Dockerfile` | Lean base image (MCP + brain tools, no code-server) |
| `Dockerfile.full` | Full-stack tier image — core + psycopg for pgvector |
| `tools/lib/pgstore.py` | PostgreSQL/pgvector index-store backend |
| `tools/lib/policy.py` | `ProfilePolicyProvider` — hot-reloading rbac reads, `BRAIN_AUTH_MODE` seam, agent-token verification |
| `tools/lib/policy_edit.py` | `PolicyEditor` — the only writer of auth policy; every edit is a git commit to the profile repo |
| `tools/lib/credentials.py` | `PgCredentialStore` — Postgres agent-token credentials (mint/verify/revoke, hash-only) |
| `tools/brain_admin.py` | `brain-admin` CLI — manage roles/identities/principals/tokens, local (docker-exec) or remote (`/api/admin/*`) |
| `tools/lib/retrieval_log.py` | `PgRetrievalLog` — append-only per-principal retrieval/audit log (reads/writes/admin actions), best-effort `safe_log_*` hooks |
| `profiles/ace/profile.toml` | Bundled profile manifest — folders, skills, plugin identity, zk conventions |
| `tools/lib/profile.py` | Profile loading/validation/zk-config composition (`load_profile`, `compose_zk_config`) |

## Release Process

Releases are cut via GitHub — the `docker-release.yml` workflow auto-syncs the version tag into `pyproject.toml`, `Dockerfile`, and `Dockerfile.full`, then builds and pushes `kitchencoder/second-brain:latest` (lean base, plus `:oauth` twin tags) and `:full` (adds psycopg for the Postgres/pgvector tier) to Docker Hub. The `:ui` image is no longer published — see `docs/recipes/code-server.md` for a build-your-own recipe.
