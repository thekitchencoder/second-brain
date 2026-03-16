# second-brain

Docker container for vault management: zk, semantic search, and MCP server for Claude Code.

## Quick start

```bash
# Copy and configure
cp .env.example .env
# Edit VAULT_PATH in .env to point at your vault (default: ~/Documents/Vault33)

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

After adding: `source ~/.zshrc`

## Inside the container

### Browse and search

```bash
# List notes by tag
zk list --tag "epistemic-lens"

# List recent notes
zk list $recents

# Full-text search with preview
zk list | fzf --preview 'bat --color=always {}'

# Semantic search
vault-search "co-dependent confabulation"
vault-search "embedding models" --limit 10
vault-search "query" --json
```

### Create notes

```bash
zk new --title "My Note"
zk new --template meeting --title "Team Sync"
zk new --template daily
zk new --template effort --title "Project X"
```

### Index

```bash
# Full reindex
vault-index run

# Watch for changes (incremental)
vault-index watch
```

## MCP server (Claude Code integration)

Add to `~/.claude/mcp.json`:

```json
{
  "mcpServers": {
    "vault": {
      "command": "docker",
      "args": ["exec", "-i", "vault", "vault-mcp-server"]
    }
  }
}
```

Available tools:

| Tool | Description |
|---|---|
| `vault_search(query, limit?)` | Semantic search — returns results with full frontmatter provenance |
| `vault_query(tag?, status?, type?)` | Structured metadata query via zk |
| `vault_create(template, title)` | Create a note from a template |
| `vault_related(filepath, limit?)` | Find semantically related notes |

## Configuration

| Variable | Default | Description |
|---|---|---|
| `VAULT_PATH` | `~/Documents/Vault33` | Path to vault on the host |
| `EMBEDDING_BASE_URL` | Docker Model Runner | OpenAI-compatible embedding endpoint |
| `EMBEDDING_MODEL` | `mxbai-embed-large` | Embedding model name |
| `EMBEDDING_DIM` | `1024` | Embedding vector dimension — must match model |
| `CHAT_BASE_URL` | Docker Model Runner | Chat completions endpoint |
| `CHAT_MODEL` | `llama3.2` | Chat model name |
| `OPENAI_API_KEY` | `local` | API key (any non-empty string for local endpoints) |

### Using Ollama instead of Docker Model Runner

```bash
EMBEDDING_BASE_URL=http://host.docker.internal:11434/v1
CHAT_BASE_URL=http://host.docker.internal:11434/v1
```

### Using LM Studio

```bash
EMBEDDING_BASE_URL=http://host.docker.internal:1234/v1
CHAT_BASE_URL=http://host.docker.internal:1234/v1
```

## Vault structure

The container works with any vault structure. On first use, `vault-init` adds:

```
your-vault/
├── .zk/                  ← zk config and templates (created by vault-init)
│   ├── config.toml
│   └── templates/
│       ├── default.md
│       ├── daily.md
│       ├── meeting.md
│       └── effort.md
└── .ai/
    └── embeddings.db     ← sqlite-vec vector index (created by vault-index)
```

Both `.zk/` and `.ai/` are ignored by Obsidian. The vault remains fully compatible with Obsidian on your personal machine.
