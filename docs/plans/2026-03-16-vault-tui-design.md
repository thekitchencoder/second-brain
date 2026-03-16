# Vault TUI Design

**Date:** 2026-03-16
**Status:** approved
**Scope:** Docker container with zk, semantic search, and MCP server for Claude Code

---

## Problem

Build a vault toolchain that:
- Runs without host installs (Docker only)
- Works with any mounted vault regardless of folder structure
- Integrates with Claude Code via MCP, returning provenance-aware results
- Supports semantic search using local embeddings (Docker Model Runner by default)
- Remains fully compatible with the existing Obsidian vault

---

## Architecture

```
second-brain/
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── README.md
├── tools/
│   ├── vault-index          # embedding indexer (full + watch modes)
│   ├── vault-search         # semantic search CLI
│   ├── vault-mcp-server     # MCP server for Claude Code
│   └── lib/
│       ├── config.py        # shared env-var config
│       ├── db.py            # sqlite-vec helpers
│       └── clean.py         # document cleaning + chunking
└── zk/
    ├── config.toml          # copied into vault on init
    └── templates/
        ├── default.md
        ├── daily.md
        ├── meeting.md
        └── effort.md
```

**Container base:** `python:3.12-slim`
**Baked at build time:** zk binary, fzf, ripgrep, bat, Python deps (openai, pyyaml, sqlite-vec, watchfiles)
**Vault mount:** `/vault`
**Embeddings DB:** `/vault/.ai/embeddings.db`
**Entry point:** interactive zsh shell

---

## Configuration

All endpoints configurable via environment variables. Defaults target Docker Model Runner.

`.env.example`:
```
EMBEDDING_BASE_URL=http://model-runner.docker.internal/engines/llama.cpp/v1
EMBEDDING_MODEL=mxbai-embed-large
CHAT_BASE_URL=http://model-runner.docker.internal/engines/llama.cpp/v1
CHAT_MODEL=llama3.2
```

Compatible with any OpenAI-compatible endpoint (LM Studio, Ollama, etc.).

---

## Document Cleaning (`lib/clean.py`)

Runs before chunking every note. Steps in order:

1. **Extract front matter** — parse YAML block, remove from content, store as metadata
2. **Strip ASCII art** — remove lines consisting mostly of box-drawing characters (`─│┼╔═+|-`) and repeated symbol lines
3. **Collapse code blocks** — replace fenced code blocks with `[code block: lang]` placeholder
4. **Simplify tables** — strip separator rows (`|---|---`), join remaining rows as space-separated text
5. **Collapse whitespace** — normalise multiple blank lines to one

**Chunking:** 400-token overlapping windows, 50-token overlap, splitting on paragraph boundaries. Each chunk carries: `filepath`, `chunk_index`, `title`, `tags`, `type`, `status`, `created`, `scope`, `content_hash`.

Front matter is stored as structured columns alongside the vector — not embedded with the content. This keeps semantic search clean while making structured metadata available in results.

---

## Indexer (`vault-index`)

Two modes:

- `vault-index run` — full reindex of all notes
- `vault-index watch` — incremental reindex using `watchfiles`, skips chunks whose `content_hash` is unchanged

sqlite-vec schema:
- `chunks` table: cleaned text + frontmatter columns + filepath + chunk_index
- `embeddings` virtual table: vectors with chunk_id foreign key

---

## MCP Server (`vault-mcp-server`)

Exposes four tools to Claude Code:

### `vault_search(query, limit=5)`
Embeds the query, runs KNN against sqlite-vec. Returns chunks with full parent document frontmatter: matched text, filepath, title, type, status, created, tags, similarity score.

### `vault_query(tag=None, status=None, type=None)`
Delegates to `zk list` with front matter filters. Pure structured metadata query, no embeddings. Returns file list with frontmatter.

### `vault_create(template, title)`
Runs `zk new` with the specified template. Returns the path of the created file.

### `vault_related(filepath, limit=5)`
Finds chunks from other files semantically close to the mean embedding of all chunks in the target file.

**Claude Code config** (`~/.claude/mcp.json`):
```json
{
  "mcpServers": {
    "vault": {
      "command": "docker",
      "args": ["exec", "-i", "vault", "python3",
               "/usr/local/lib/vault-tools/vault-mcp-server.py"]
    }
  }
}
```

---

## zk Config & Templates

`zk/config.toml` (copied to `/vault/.zk/config.toml` on `vault-init`):

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

Templates use front matter matching the existing vault schema. `type` values: `note`, `journal`, `meeting`, `effort`.

---

## Vault Init

`vault-init` command:
- Copies `.zk/` config and templates into the mounted vault
- Creates `.ai/` directory
- Idempotent — skips if already initialised

---

## Interaction Model

Users interact via interactive shell:
```bash
docker exec -it vault zsh
```

README documents common commands and host alias setup. No named wrapper commands — shell is the interface.

---

## Design Decisions

| Decision | Rationale |
|---|---|
| No in-container editor | User unfamiliar with neovim; Claude Code is the primary editing interface |
| Structure-agnostic container | Vault layout varies; `.zk/` init is per-vault, not per-container |
| Frontmatter as structured columns | Enables provenance-aware search results without polluting embedding space |
| Clean before chunk | ASCII art, code blocks, and tables degrade embedding quality |
| Configurable endpoints | Default to Docker Model Runner; compatible with Ollama and LM Studio |
| sqlite-vec over dedicated vector DB | One file in the vault, no extra services, sufficient for personal vault scale |

---

## Provenance Requirement

Search results must include document frontmatter so a consuming Claude session can assess evidential status. A search for "co-dependent confabulation" should return not just the matched text but: when the concept was coined, its current status (draft/current/speculative), and its tags. This is the critical constraint from the experimental roadmap — without provenance, each session must re-establish context from scratch.
