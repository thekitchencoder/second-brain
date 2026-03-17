# second-brain

Docker container for brain management: zk, semantic search, and MCP server for Claude Code and Claude Desktop.

## Quick start

```bash
# Copy and configure
cp .env.example .env
# Edit BRAIN_HOST_PATH in .env to point at your notes directory

# Start (pulls image from Docker Hub)
docker compose up -d

# Shell into the container
docker exec -it brain zsh

# Initialise a brain (first time only)
brain-init

# Index for semantic search
brain-index run
```

## Host aliases

Add to `~/.zshrc` or `~/.bashrc`:

```bash
# Drop into brain shell
alias brain='docker exec -it brain zsh'

# Semantic search from host
alias bsearch='docker exec brain brain-search'

# Index brain from host
alias bindex='docker exec brain brain-index run'

# Watch mode (background indexing)
alias bwatch='docker exec -d brain brain-index watch'
```

After adding: `source ~/.zshrc`

## Inside the container

### Browse and search

```bash
# List notes by tag
zk list --tag "epistemic-lens"

# List recent notes (alias: recent)
recent

# Full-text search with preview (alias: preview)
preview

# Semantic search (alias: search)
search "co-dependent confabulation"
search "embedding models" --limit 10
brain-search "query" --json

# Watch the background indexer log
watchlog
```

### Create notes

```bash
zk new --title "My Note"
zk new --template context-primer --title "Project X — Context"
zk new --template project --title "Project X"
zk new --template meeting --title "Team Sync"
zk new --template daily
zk new --template effort --title "Project X"
zk new --template spec --title "Feature Y"
zk new --template adr --title "Use SQLite for storage"
zk new --template discovery --title "Interesting idea"
```

### Index

```bash
# Full reindex (also purges stale entries)
brain-index run

# Watch for changes (incremental)
brain-index watch
```

### Template sync (Obsidian + zk)

If you use both Obsidian and the Docker TUI, keep templates in sync:

```bash
# Check sync state
brain-template-sync status

# After editing an Obsidian template, push to zk
brain-template-sync obsidian-to-zk

# After adding a new zk template, push to Obsidian
brain-template-sync zk-to-obsidian
```

## MCP server (Claude Code + Claude Desktop)

### Claude Code

Add to `.mcp.json` in your project root (or `~/.claude/mcp.json` for global):

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

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

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

The brain container must be running before starting Claude Desktop.

### Available tools

| Tool | Description |
|---|---|
| `brain_search(query, limit?)` | Semantic search — returns results with full frontmatter provenance |
| `brain_query(tag?, status?, type?)` | Structured metadata query via zk |
| `brain_read(filepath)` | Read the full content of a note by filepath |
| `brain_write(filepath, content)` | Write content to a note (use after `brain_create`) |
| `brain_create(template, title, directory?)` | Create a note stub from a template in an optional subdirectory, returns filepath |
| `brain_templates()` | List available templates — call before `brain_create` |
| `brain_related(filepath, limit?)` | Find semantically related notes |

## Skills

Pre-built Claude Code skills are included in the `skills/` directory.

### Claude Code

Copy (one-off):
```bash
cp -r skills/brain-* ~/.claude/skills/
```

Or symlink so skills stay in sync with the repo:
```bash
for d in skills/brain-*/; do ln -sf "$PWD/$d" ~/.claude/skills/; done
```

### Claude Desktop

Zip each skill folder and upload via **Customize → Skills**:

```bash
cd skills && for d in brain-*/; do zip -r "${d%/}.zip" "$d"; done
```

Then upload each `.zip` in Claude Desktop → Customize → Skills.

See [`skills/README.md`](skills/README.md) for details on what each skill does.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `BRAIN_HOST_PATH` | `~/Documents/brain` | Path to your notes directory on the host |
| `EMBEDDING_BASE_URL` | Docker Model Runner | OpenAI-compatible embedding endpoint |
| `EMBEDDING_MODEL` | `mxbai-embed-large` | Embedding model name — dimension auto-detected at index time |
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

The container works with any notes directory. On first use, `brain-init` adds:

```
your-brain/
├── .zk/                  ← zk config and templates (created by brain-init)
│   ├── config.toml
│   └── templates/
│       ├── default.md
│       ├── context-primer.md
│       ├── project.md
│       ├── spec.md
│       ├── adr.md
│       ├── discovery.md
│       ├── effort.md
│       ├── meeting.md
│       └── daily.md
└── .ai/
    └── embeddings.db     ← sqlite-vec vector index (created by brain-index)
```

Both `.zk/` and `.ai/` are ignored by Obsidian. The brain remains fully compatible with Obsidian on your host machine.
