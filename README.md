# second-brain

Docker container for brain management: zk, semantic search, and MCP server for Claude Code and Claude Desktop.

## Quick start

```bash
# Set your vault path in the shell — required before docker compose up
export BRAIN_HOST_PATH=~/Documents/brain   # edit to match your vault location
# Add this to ~/.zshrc or ~/.bashrc to persist across sessions

# Copy and configure container environment
cp .env.example .env
# Edit .env for EMBEDDING_MODEL, CHAT_MODEL, etc. if needed

# Start (pulls image from Docker Hub)
docker compose up -d

# Shell into the container
docker exec -it brain zsh

# Initialise a brain (first time only)
brain-init

# First-time vault structure setup — paste prompts/setup.md into a Claude session

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

## VS Code

Open your brain vault folder in VS Code to get wiki-link navigation and markdown preview.

`brain-init` creates a `.vscode/` directory in the vault with recommended extensions and settings. VS Code will prompt to install them (Foam, Markdown All in One, Paste Image) — accept the prompt or run `Extensions: Show Recommended Extensions` from the command palette.

**Usage:**
- **Follow wiki-links:** Ctrl+click (Cmd+click on Mac) any `[[wiki-link]]` to navigate to that note
- **Backlinks:** Open the Foam panel in the sidebar to see which notes link to the current note
- **Graph view:** Run `Foam: Show Graph` from the command palette to visualise connections
- **Daily notes:** Run `Foam: Open Daily Note` — configured to create in `Calendar/`

Foam coexists with Obsidian — it uses `.vscode/` configuration, not `.obsidian/`.

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

## MCP server

The brain exposes an MCP server with two transports:

- **stdio** (default) — for local clients like Claude Code and Claude Desktop
- **HTTP** — Streamable HTTP on port 7780 for network clients like Open WebUI and LM Studio

### Claude Code

Register once across all your projects (user scope):

```bash
claude mcp add --scope user brain -- docker exec -i brain brain-mcp-server
```

Or for a single project only (adds `.mcp.json` to the project root):

```bash
claude mcp add --scope project brain -- docker exec -i brain brain-mcp-server
```

Verify it's registered:

```bash
claude mcp list
```

### Claude Desktop

Add to your Claude Desktop config file:

- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux:** `~/.config/Claude/claude_desktop_config.json`

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

### Docker MCP Toolkit (Docker Desktop 4.48+)

Docker Desktop's MCP Toolkit provides a centralised gateway that exposes MCP servers to all your AI clients at once. Instead of configuring each client separately, you configure the gateway once.

**1. Enable the MCP Toolkit:**

Docker Desktop → Settings → Beta Features → Enable "Docker MCP Toolkit"

**2. Create a catalog file** at `~/.docker/mcp/catalogs/brain.yaml`:

```yaml
name: brain-catalog
displayName: Second Brain
registry:
  brain-mcp:
    description: "Second Brain MCP server — search, read, write, edit notes"
    title: "Brain MCP"
    image: "kitchencoder/second-brain:latest"
    command:
      - "brain-mcp-server"
    volumes:
      - "{{brain-mcp.brain_path}}:/brain"
    env:
      - name: "BRAIN_PATH"
        value: "/brain"
    config:
      - name: "brain-mcp"
        type: "object"
        properties:
          brain_path:
            type: "string"
            description: "Path to your vault on the host"
        required: ["brain_path"]
```

**3. Create a profile and configure it:**

```bash
docker mcp profile create --name brain
docker mcp profile add-server brain --server-id brain-mcp
docker mcp profile config brain --set brain-mcp.brain_path=$BRAIN_HOST_PATH
```

**4. Connect clients via the gateway:**

```bash
# stdio mode — for Claude Desktop / Claude Code
docker mcp gateway run --profile brain

# SSE mode — for Open WebUI / LM Studio / remote clients
docker mcp gateway run --profile brain --transport streaming --port 8811
```

For Claude Desktop, the easiest path is Docker Desktop → MCP Toolkit → MCP Clients → click "Connect" next to Claude Desktop.

> **Note:** The Docker MCP gateway launches its own containers from images — it does not connect to your existing `docker compose` services. If you need the full stack (indexer + REST API + MCP server), use docker compose with HTTP transport instead (see below).

### Open WebUI

Open WebUI connects to the MCP server over HTTP. Enable HTTP transport in docker compose and point Open WebUI at the `/mcp` endpoint.

**1. Add HTTP transport to your compose config.** In `.env`:

```bash
BRAIN_MCP_TRANSPORT=http
```

Or add the environment variable and port directly in `docker-compose.yml`:

```yaml
services:
  brain:
    environment:
      - BRAIN_MCP_TRANSPORT=http
    ports:
      - "${BRAIN_API_PORT:-7779}:7779"
      - "7780:7780"   # MCP HTTP
```

**2. Restart the brain container:**

```bash
docker compose up -d
```

**3. Configure Open WebUI:**

Go to **Admin Panel → Settings → Tools → MCP Servers** and add:

- **URL:** `http://brain:7780/mcp` (if Open WebUI and brain share a Docker network)
- **URL:** `http://host.docker.internal:7780/mcp` (if Open WebUI uses the host network)

If they're in separate compose files, create a shared network:

```bash
docker network create brain-net
```

Then add `networks: [brain-net]` to both services and use `http://brain:7780/mcp` as the URL.

### LM Studio

LM Studio supports MCP tool use with compatible models. Connect it to the brain's HTTP transport.

**1. Enable HTTP transport** (same as Open WebUI above — set `BRAIN_MCP_TRANSPORT=http` and expose port 7780).

**2. In LM Studio**, open the MCP server configuration and add:

- **URL:** `http://localhost:7780/mcp`
- **Transport:** Streamable HTTP

LM Studio requires a model that supports tool/function calling (e.g. Qwen 2.5, Llama 3.x, Mistral). The model must be loaded with tool use enabled for the brain tools to appear.

### HTTP transport reference

| Variable | Default | Description |
|---|---|---|
| `BRAIN_MCP_TRANSPORT` | `stdio` | Transport mode: `stdio` or `http` |
| `BRAIN_MCP_HOST` | `0.0.0.0` | Bind address for HTTP mode |
| `BRAIN_MCP_PORT` | `7780` | Port for HTTP mode |

The HTTP endpoint is `http://<host>:<port>/mcp` and implements the MCP Streamable HTTP protocol (JSON-RPC over HTTP POST with SSE responses).

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
| `brain_edit(filepath, op, ...)` | Surgical edit — update frontmatter, replace/append/prepend sections, find-replace, line ranges, insert wikilinks |
| `brain_backlinks(filepath)` | Find all notes that link to a given note via `[[wikilinks]]` |

## Skills

There are two sets of skills:

- **`skills/`** — installed into `~/.claude/skills/` (or Claude Desktop). These use the MCP server and work from any project directory.
- **`brain-skills/`** — installed into `$BRAIN_HOST_PATH/.claude/skills/`. These load only when Claude Code is opened at the vault root. They use MCP for semantic search and direct filesystem tools for file I/O.

### Claude Code — global skills (`skills/`)

Copy (one-off):
```bash
cp -r skills/brain-* ~/.claude/skills/
```

Or symlink so skills stay in sync with the repo:
```bash
for d in skills/brain-*/; do ln -sf "$PWD/$d" ~/.claude/skills/; done
```

### Claude Code — vault-level skills (`brain-skills/`)

These load automatically when Claude Code is opened inside the vault.

Copy (one-off):
```bash
cp -r brain-skills/brain-* $BRAIN_HOST_PATH/.claude/skills/
```

Or symlink:
```bash
for d in brain-skills/brain-*/; do ln -sf "$PWD/$d" "$BRAIN_HOST_PATH/.claude/skills/"; done
```

| Skill | Trigger | What it does |
|---|---|---|
| `brain-capture` | "I've had an idea about X" | Conversational capture → creates note → waits for edit → wires in wikilinks + index |
| `brain-connect` | "Find connections for this note" | Surfaces related notes, offers to patch wikilinks |
| `brain-triage` | "Process my inbox" | Works through `status: raw` notes one at a time — promote, archive, or defer |
| `brain-rename` | "Rename this note" | Renames a file and updates every `[[wikilink]]` pointing to it across the vault |
| `brain-daily` | "Start my day" | Creates today's daily note, carries forward open items, shows inbox count |
| `brain-effort` | "Where does X effort stand?" | Status overview of all notes in an effort, flags orphans and missing stubs |
| `brain-extract` | "Pull the ideas out of this note" | Extracts atomic ideas from a long note into separate Cards with wikilinks back |

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
| `BRAIN_MCP_TRANSPORT` | `stdio` | MCP transport: `stdio` or `http` |
| `BRAIN_MCP_HOST` | `0.0.0.0` | Bind address for MCP HTTP mode |
| `BRAIN_MCP_PORT` | `7780` | Port for MCP HTTP mode |
| `BRAIN_API_PORT` | `7779` | Port for the REST API |

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
├── .ai/
│   └── embeddings.db     ← sqlite-vec vector index (created by brain-index)
└── .vscode/              ← VS Code workspace config (created by brain-init)
    ├── extensions.json
    └── settings.json
```

`.zk/`, `.ai/`, and `.vscode/` are ignored by Obsidian. The brain remains fully compatible with Obsidian on your host machine.
