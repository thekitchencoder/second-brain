# second-brain

Docker container for brain management: zk, semantic search, and MCP server for Claude Code.

## Quick start

```bash
# Copy and configure
cp .env.example .env
# Edit BRAIN_PATH in .env to point at your brain (default: ~/Documents/Vault33)

# Build
docker compose build

# Start (runs in background)
docker compose up -d

# Shell into the container
docker exec -it brain zsh

# Initialise a brain (first time only)
brain-init
```

## Host aliases

Add to `~/.zshrc` or `~/.bashrc`:

```bash
# Drop into brain shell
alias brain='docker exec -it brain zsh'

# Semantic search from host
alias vsearch='docker exec brain brain-search'

# Index brain from host
alias vindex='docker exec brain brain-index run'

# Watch mode (background indexing)
alias vwatch='docker exec -d brain brain-index watch'
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
brain-search "co-dependent confabulation"
brain-search "embedding models" --limit 10
brain-search "query" --json
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
brain-index run

# Watch for changes (incremental)
brain-index watch
```

## MCP server (Claude Code integration)

Add to `~/.claude/mcp.json`:

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

Available tools:

| Tool | Description |
|---|---|
| `brain_search(query, limit?)` | Semantic search — returns results with full frontmatter provenance |
| `brain_query(tag?, status?, type?)` | Structured metadata query via zk |
| `brain_create(template, title)` | Create a note from a template |
| `brain_related(filepath, limit?)` | Find semantically related notes |

## Configuration

| Variable | Default | Description |
|---|---|---|
| `BRAIN_PATH` | `~/Documents/Vault33` | Path to brain on the host |
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

## Brain structure

The container works with any brain structure. On first use, `brain-init` adds:

```
your-brain/
├── .zk/                  ← zk config and templates (created by brain-init)
│   ├── config.toml
│   └── templates/
│       ├── default.md
│       ├── daily.md
│       ├── meeting.md
│       └── effort.md
└── .ai/
    └── embeddings.db     ← sqlite-vec vector index (created by brain-index)
```

Both `.zk/` and `.ai/` are ignored by Obsidian. The brain remains fully compatible with Obsidian on your personal machine.

## Skills

Pre-built Claude Code skills are included in the `skills/` directory:

```bash
cp -r skills/brain-* ~/.claude/skills/
```

See [`skills/README.md`](skills/README.md) for details.
