# Second Brain

A self-contained Docker image that turns a folder of markdown notes into an AI-accessible second brain. Mount your notes, index them with semantic search, and expose an MCP server so AI clients (Claude Code, Claude Desktop, Open WebUI, LM Studio) can search, read, and write your notes.

## Quick start

No repository clone required — the image includes everything.

```bash
# 1. Create a directory for your brain (or use an existing notes folder)
mkdir -p ~/Documents/brain

# 2. Run the setup wizard (choose model provider, create folders, generate .env)
docker run --rm -it \
  -v ~/Documents/brain:/brain \
  kitchencoder/second-brain:latest \
  brain-init

# 3. Start the container
docker run -d --name second-brain --restart unless-stopped \
  -v ~/Documents/brain:/brain \
  -v second-brain-claude:/home/coder/.claude \
  -v second-brain-zsh:/home/coder/.zsh-data \
  -p 7779:7779 -p 7780:7780 \
  kitchencoder/second-brain:latest
```

First init clones the default profile from GitHub, so it needs network access — or point `BRAIN_PROFILE_REPO` at a local profile checkout.

## Tags

| Tag | Contents |
|---|---|
| `latest` (also `2`, `2.0`, …) | Core image: MCP server (stdio + HTTP), semantic search (SQLite + sqlite-vec), note tools |
| `oauth` | Twin tag of the core image — static-token and OAuth 2.1 auth are built in, enabled via profile config |
| `full` | Core + Postgres/pgvector tier: pgvector index store, RBAC admin plane, agent tokens, per-principal retrieval log |
| `ui` | **No longer published** (2.0+). Build your own IDE layer — see the [code-server recipe](https://github.com/thekitchencoder/second-brain/blob/main/docs/recipes/code-server.md) |

## What's inside

- **Semantic search** — find notes by meaning, not just keywords. Embedded SQLite + sqlite-vec by default; Postgres/pgvector in the `full` tier.
- **MCP server** — stdio and HTTP transports. Tools: `brain_search`, `brain_query`, `brain_read`, `brain_write`, `brain_create`, `brain_edit`, `brain_related`, `brain_backlinks`, `brain_templates`.
- **Profiles: one engine, many brains** — a brain self-describes via a profile repo (folders, templates, skills, plugin identity, queryable fields). The default [ace profile](https://github.com/thekitchencoder/brain-profile-ace) is cloned on first init; an [Obsidian flavour](https://github.com/thekitchencoder/brain-profile-obsidian) and custom forks are one env var away.
- **Claude Code integration** — stages a Claude Code plugin with note-management skills (capture, triage, daily notes, …). Per-brain identity (`brain-init --brain-name`) lets several brains coexist on one machine.
- **Auth, off by default** — static per-principal bearer tokens or a full OAuth 2.1 authorization server for exposing the API/MCP over HTTP.
- **RBAC + audit (`full` tier)** — role-based content visibility, `brain-admin` CLI, append-only per-principal retrieval log.
- **Privacy first** — designed for local models via Docker Model Runner, Ollama, or LM Studio; any OpenAI-compatible embedding endpoint works.

## Connect to Claude Code

`brain-init` stages a Claude Code plugin inside your brain. Install it on your host:

```bash
claude plugin marketplace add ~/Documents/brain/.ai
claude plugin install second-brain
```

This registers the MCP server and installs the global skills — no separate `claude mcp add` needed. Other MCP clients (Claude Desktop, Open WebUI, LM Studio) connect over HTTP at `http://localhost:7780/mcp/`.

## Ports

| Port | Service |
|---|---|
| `7779` | REST API |
| `7780` | MCP HTTP transport (optional, `BRAIN_MCP_TRANSPORT=http`) |

## Requirements

Docker, plus an embedding model: Docker Model Runner, Ollama, LM Studio, or any OpenAI-compatible API. The `brain-init` wizard walks you through provider presets.

## Documentation

Source, user guide, MCP client setup, auth guide, and recipes (browser IDE, full-stack compose):
**[github.com/thekitchencoder/second-brain](https://github.com/thekitchencoder/second-brain)**
