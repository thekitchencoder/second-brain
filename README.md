# second-brain

Docker container for brain management: zk, semantic search, and MCP server for Claude Code and Claude Desktop.

## Two Images

| Image | Use when | Size |
|-------|----------|------|
| `kitchencoder/second-brain:latest` | MCP server + brain tools only — Claude Code plugin, API access, no browser UI needed | ~600MB |
| `kitchencoder/second-brain:ui` | Adds code-server web IDE — open `http://localhost:7778` in your browser | ~1.5GB |

**Base image (MCP only):**
```bash
docker run -d --name brain \
  -v ~/Documents/brain:/brain \
  -p 7779:7779 -p 7780:7780 \
  kitchencoder/second-brain:latest
```

**UI image (includes code-server web IDE):**
```bash
docker run -d --name brain \
  -v ~/Documents/brain:/brain \
  -p 7778:7778 -p 7779:7779 -p 7780:7780 \
  kitchencoder/second-brain:ui
```

## Quick start

No repo clone needed — the Docker image has everything.

```bash
# 1. Create a directory for your vault (or use an existing notes folder)
mkdir -p ~/Documents/brain

# 2. Run the setup wizard (choose your model provider, create folders, generate .env)
docker run --rm -it \
  -v ~/Documents/brain:/brain \
  kitchencoder/second-brain:latest \
  brain-init

# 3a. Start with browser IDE (code-server on http://localhost:7778)
docker run -d --name second-brain --restart unless-stopped \
  -v ~/Documents/brain:/brain \
  -v second-brain-claude:/home/coder/.claude \
  -v second-brain-code-server:/home/coder/.local/share/code-server \
  -v second-brain-zsh:/home/coder/.zsh-data \
  -p 7778:7778 -p 7779:7779 -p 7780:7780 \
  kitchencoder/second-brain:ui
open http://localhost:7778

# 3b. Or start lean (MCP + brain tools only, no browser UI — ~600MB smaller)
docker run -d --name second-brain --restart unless-stopped \
  -v ~/Documents/brain:/brain \
  -v second-brain-claude:/home/coder/.claude \
  -v second-brain-zsh:/home/coder/.zsh-data \
  -p 7779:7779 -p 7780:7780 \
  kitchencoder/second-brain:latest
```

The wizard lets you pick your model provider and embedding model. It offers presets for Docker Model Runner, Ollama, LM Studio, and Anthropic API. You can re-run it any time:

```bash
docker exec -it second-brain brain-init
```

### Connect to host Claude Code

`brain-init` stages a Claude Code plugin inside the vault with global skills and MCP server config. Install it on your host with two commands:

```bash
claude plugin marketplace add ~/Documents/brain/.ai
claude plugin install second-brain
```

This registers the brain MCP server and installs all global skills so Claude Code can access your brain from any project.

### Custom configuration

For Ollama, LM Studio, or Anthropic API, run `brain-init` — it offers presets for common setups and writes a `.env` file to your vault. Changes take effect on container restart.

You can also create or edit the `.env` file manually at `<vault>/.env`. See the [Configuration](#configuration) section for all available variables.

## Upgrading

```bash
docker pull kitchencoder/second-brain:latest   # or :ui
docker rm -f second-brain
# Re-run the docker run command from Quick Start step 3 above
```

Your vault data, Claude config, and shell history are preserved in named volumes. To update templates and skills inside an existing vault, run `brain-init` again — it will update staged host skills and leave existing config untouched.

No re-indexing required unless the release notes say otherwise.

## Browser UI (code-server)

> Requires the `kitchencoder/second-brain:ui` image — see [Two Images](#two-images).

A browser-based VS Code at `http://localhost:7778` — no password, single-user. This is the primary interface when running at a machine where a local editor can't be installed.

**Features:**
- Full VS Code in the browser with your vault open
- Foam extension — `[[wikilink]]` navigation, backlinks panel, graph view
- Integrated terminal running zsh with all brain tools on PATH (`brain-search`, `zk`, `brain-index`, etc.)
- Claude Code pre-configured in the terminal — connects to any Anthropic-compatible provider via your vault's `.env`

**Claude Code in the terminal:**

Claude Code is pre-wired with:
- Docker Model Runner as the LLM backend (no Anthropic API key needed)
- Brain MCP server pre-approved — all brain tools available immediately
- All skills from `skills/` and `brain-skills/` seeded into `~/.claude/skills/`

```bash
# Open the browser UI
open http://localhost:7778

# In the VS Code integrated terminal, Claude Code is ready:
claude
```

**Configuring the model:**

Claude Code reads `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, and `ANTHROPIC_MODEL` from the container environment. Set them in `.env` and restart — no rebuild needed:

```bash
# .env
ANTHROPIC_BASE_URL=http://model-runner.docker.internal
ANTHROPIC_AUTH_TOKEN=ollama
ANTHROPIC_MODEL=docker.io/ai/qwen2.5:7B-Q4_0
```

To switch to real Claude, remove `ANTHROPIC_BASE_URL` and set a real `ANTHROPIC_AUTH_TOKEN` or `ANTHROPIC_API_KEY`.

**Persistent state:**

| Volume | Contents |
|---|---|
| `second-brain-claude` | Claude Code user config (`~/.claude/`) — settings, session history |
| `second-brain-code-server` | VS Code UI state — open tabs, panel layout |
| `second-brain-zsh` | Zsh history across sessions |

---

## Host aliases

Add to `~/.zshrc` or `~/.bashrc`:

```bash
# Drop into brain shell
alias brain='docker exec -it second-brain zsh'

# Semantic search from host
alias bsearch='docker exec second-brain brain-search'

# Index brain from host
alias bindex='docker exec second-brain brain-index run'

# Watch mode (background indexing)
alias bwatch='docker exec -d second-brain brain-index watch'
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

The brain exposes an MCP server with two transports that can run **simultaneously**:

- **stdio** — on-demand via `docker exec` (always available, no config needed)
- **HTTP** — Streamable HTTP on port 7780 (persistent daemon, started when `BRAIN_MCP_TRANSPORT=http`)

Both transports share the same tools and handler logic. When you set `BRAIN_MCP_TRANSPORT=http`, the entrypoint starts the HTTP daemon as a background process alongside the indexer and REST API. The stdio transport remains available via `docker exec` regardless — it spawns a fresh process per invocation.

### Enabling HTTP transport

`brain-init` sets `BRAIN_MCP_TRANSPORT=http` in your vault's `.env` by default, and the Quick Start commands expose port 7780. To verify:

```bash
# Check vault .env
grep BRAIN_MCP_TRANSPORT ~/Documents/brain/.env

# If missing, add it and restart
echo "BRAIN_MCP_TRANSPORT=http" >> ~/Documents/brain/.env
docker restart second-brain
```

Once the container is running with port 7780 mapped and HTTP transport enabled, configure each client:

| Client | Transport | How it connects |
|---|---|---|
| Claude Code | stdio | `docker exec -i second-brain brain-mcp-server` |
| Claude Code | HTTP | `http://localhost:7780/mcp/` |
| Claude Desktop | stdio | `docker exec -i second-brain brain-mcp-server` |
| Open WebUI | HTTP | `http://<host>:7780/mcp/` |
| LM Studio | HTTP | `http://localhost:7780/mcp/` |
| Docker MCP Toolkit | either | Gateway manages its own container |

### Claude Code

**Option A — HTTP (recommended when HTTP transport is enabled):**

```bash
claude mcp add --transport http --scope user brain http://localhost:7780/mcp/
```

Or in `.mcp.json` (shared with your team):

```json
{
  "mcpServers": {
    "brain": {
      "type": "http",
      "url": "http://localhost:7780/mcp/"
    }
  }
}
```

**Option B — stdio (works without HTTP transport):**

```bash
claude mcp add --scope user brain -- docker exec -i second-brain brain-mcp-server
```

Verify it's registered:

```bash
claude mcp list
```

HTTP is simpler — no `docker exec` subprocess management — but requires `BRAIN_MCP_TRANSPORT=http` and port 7780 exposed. The stdio option works with the default container config and needs no port mapping.

### Claude Desktop

Add to your Claude Desktop config file:

- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux:** `~/.config/Claude/claude_desktop_config.json`

**HTTP (recommended when HTTP transport is enabled):**

```json
{
  "mcpServers": {
    "brain": {
      "type": "http",
      "url": "http://localhost:7780/mcp/"
    }
  }
}
```

**stdio (works without HTTP transport):**

```json
{
  "mcpServers": {
    "brain": {
      "command": "docker",
      "args": ["exec", "-i", "second-brain", "brain-mcp-server"]
    }
  }
}
```

The brain container must be running before starting Claude Desktop.

### Open WebUI

Open WebUI connects over HTTP. With the recommended setup above (HTTP enabled, port 7780 exposed):

**Configure in Open WebUI:** Admin Panel → Settings → Tools → MCP Servers:

- **URL:** `http://host.docker.internal:7780/mcp/` (Open WebUI running on the host or in Docker for Mac/Windows)
- **URL:** `http://second-brain:7780/mcp/` (Open WebUI and brain on the same Docker network)

**If Open WebUI and brain are in separate containers**, put them on a shared network so they can reach each other by name:

```bash
docker network create brain-net
docker run -d --name second-brain --network brain-net ... kitchencoder/second-brain:latest
```

Then use `http://second-brain:7780/mcp/` as the URL in Open WebUI.

### LM Studio

LM Studio runs on the host and connects to the brain's HTTP transport.

With the recommended setup above (HTTP enabled, port 7780 exposed), add an MCP server in LM Studio:

- **URL:** `http://localhost:7780/mcp/`
- **Transport:** Streamable HTTP

LM Studio requires a model that supports tool/function calling (e.g. Qwen 2.5, Llama 3.x, Mistral). The model must be loaded with tool use enabled for the brain tools to appear.

### Docker MCP Toolkit (Docker Desktop 4.48+)

The Docker MCP Toolkit is an alternative to docker compose. It provides a centralised gateway that launches its own container from the brain image and exposes it to all AI clients at once. Use this if you only need the MCP server (no indexer or REST API).

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

# Streaming mode — for Open WebUI / LM Studio / remote clients
docker mcp gateway run --profile brain --transport streaming --port 8811
```

For Claude Desktop, the easiest path is Docker Desktop → MCP Toolkit → MCP Clients → click "Connect" next to Claude Desktop.

> **Note:** The Docker MCP gateway launches its own container — it does not connect to your existing `docker run` container. The gateway runs only the MCP server, not the indexer or REST API. For the full stack (indexer + REST API + MCP), use the Quick Start `docker run` command with HTTP transport enabled.

### HTTP transport reference

| Variable | Default | Description |
|---|---|---|
| `BRAIN_MCP_TRANSPORT` | `stdio` | Set to `http` to start the HTTP daemon in the entrypoint |
| `BRAIN_MCP_HOST` | `0.0.0.0` | Bind address for HTTP mode |
| `BRAIN_MCP_PORT` | `7780` | Port for HTTP mode |

The HTTP endpoint is `http://<host>:<port>/mcp/` and implements the MCP Streamable HTTP protocol (JSON-RPC over HTTP POST with SSE responses).

### Available tools

| Tool | Description |
|---|---|
| `brain_search(query, limit?)` | Semantic search — returns results with full frontmatter provenance |
| `brain_query(tag?, status?, type?)` | Structured metadata query via zk |
| `brain_read(filepath)` | Read the full content of a note by filepath |
| `brain_write(filepath, content)` | Overwrite a note's full content (use `brain_edit` to surgically modify an existing note) |
| `brain_create(template, title, directory?)` | Create a note stub from a template in an optional subdirectory, returns filepath |
| `brain_templates()` | List available templates — call before `brain_create` |
| `brain_related(filepath, limit?)` | Find semantically related notes |
| `brain_edit(filepath, op, ...)` | Surgical edit — update frontmatter, replace/append/prepend sections, find-replace, line ranges, insert wikilinks |
| `brain_backlinks(filepath)` | Find all notes that link to a given note via `[[wikilinks]]` |
| `brain_trash(filepath)` | Move a note to `.trash/`, remove from index, report any backlinks that now dangle |
| `brain_restore(trash_path)` | Restore a trashed note to its original location and re-index |

## Skills

There are two tiers of skills:

- **Global** (`skills/`) — for Claude Code on the host machine, from any project directory. Use MCP tools only. Installed via the Claude Code plugin.
- **Vault-level** (`brain-skills/`) — auto-installed by `brain-init` into `<vault>/.claude/skills/`. Load when Claude Code is opened at the vault root. Use MCP for semantic search and direct filesystem tools for file I/O.

### Global skills (host install via plugin)

Global skills let Claude Code access your brain from any project on your host machine (e.g. while coding, save context back to the brain). `brain-init` stages them as a Claude Code plugin:

```bash
claude plugin marketplace add ~/Documents/brain/.ai
claude plugin install second-brain
```

This also registers the brain MCP server — no separate `claude mcp add` needed.

| Skill | Trigger | What it does |
|---|---|---|
| `brain-capture` | "I've had an idea about X" | Conversational capture → creates note → waits for edit → wires in wikilinks |
| `brain-connect` | "Find connections for this note" | Surfaces related notes, offers to patch wikilinks |
| `brain-context` | Working on a named topic or project | Searches the brain for prior context before starting work |
| `brain-create-effort` | "Create a new effort for X" | Scaffolds a new effort note with goal, intensity state, and optional context primer |
| `brain-effort` | "Where does X effort stand?" | Status overview of all notes in an effort, flags orphans and missing stubs |
| `brain-project` | "start a new project" | Scaffolds a new effort with context primer |
| `brain-save` | "remember", "save", "capture" | Saves something to the brain with correct frontmatter and placement |
| `brain-setup` | "Set up my brain" / first-time vault setup | Guided vault setup flow with pre-flight check and step-by-step instructions |
| `brain-surface` | "What's simmering?" | Surfaces efforts with `intensity: simmering`, shows saved next steps, offers to resume |
| `brain-triage` | "Process my inbox" | Works through `status: raw` notes one at a time — promote, archive, or defer |
| `brain-distil` | "Distil my research into a primer" | Synthesises one or more source notes into a concise context primer for an effort |

### Vault-level skills (auto-installed)

These are installed automatically when the container starts or when you run `brain-init`. No manual setup needed.

| Skill | Trigger | What it does |
|---|---|---|
| `brain-daily` | "Start my day" | Creates today's daily note, carries forward open items, shows inbox count |
| `brain-extract` | "Pull the ideas out of this note" | Extracts atomic ideas from a long note into separate Cards with wikilinks back |
| `brain-hygiene` | "tidy", "audit", "health-check" | Checks frontmatter, orphaned notes, broken wikilinks, stale drafts |
| `brain-rename` | "Rename this note" | Renames a file and updates every `[[wikilink]]` pointing to it across the vault |
| `brain-reorganise` | "Move X into effort Y" | Moves/consolidates notes into an effort via `brain-rename` to preserve all wikilinks |

### Claude Desktop / claude.ai

Global skills can be uploaded as ZIP files:

```bash
cd skills && for d in brain-*/; do zip -r "${d%/}.zip" "$d"; done
```

- **Claude Desktop:** Settings → Customize → Skills → upload each `.zip`
- **claude.ai:** Open a Project → Project settings → Skills → upload each `.zip`

See [`skills/README.md`](skills/README.md) for details on what each skill does.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `BRAIN_HOST_PATH` | `~/Documents/brain` | Path to your notes directory on the host (shell export, not in `.env`) |
| `EMBEDDING_BASE_URL` | Docker Model Runner | OpenAI-compatible embedding endpoint |
| `EMBEDDING_MODEL` | `mxbai-embed-large` | Embedding model name — dimension auto-detected at index time |
| `OPENAI_API_KEY` | `local` | API key (any non-empty string for local endpoints) |
| `BRAIN_MCP_TRANSPORT` | `stdio` | MCP transport: `stdio` or `http` |
| `BRAIN_MCP_HOST` | `0.0.0.0` | Bind address for MCP HTTP mode |
| `BRAIN_MCP_PORT` | `7780` | Port for MCP HTTP mode |
| `BRAIN_API_PORT` | `7779` | Port for the REST API |
| `CODE_SERVER_PORT` | `7778` | Port for the browser VS Code UI (**`:ui` image only**) |
| `ANTHROPIC_BASE_URL` | Docker Model Runner | Claude Code LLM endpoint (**`:ui` image only**) |
| `ANTHROPIC_AUTH_TOKEN` | — | Claude Code auth token (**`:ui` image only**) |
| `ANTHROPIC_MODEL` | — | Claude Code model name (**`:ui` image only**) |
| `BRAVE_API_KEY` | — | Enables web search in Claude Code via Brave Search MCP (**`:ui` image only**) |

### Choosing an embedding model

The embedding model affects semantic search quality, indexing speed, and database size. `brain-init` defaults to `mxbai-embed-large` but you can choose a different model during setup or by editing `EMBEDDING_MODEL` in your vault's `.env`.

| Model | Dimensions | Best for | Trade-offs |
|---|---|---|---|
| `mxbai-embed-large` | 1024 | General-purpose notes, mixed content | Good balance of quality and speed |
| `nomic-embed-text` | 768 | Token-dense technical content (code, specs, architecture docs) | Higher quality on technical text, larger index |
| `all-minilm` | 384 | Large vaults where speed matters | Fastest and smallest index, lower retrieval quality |

**Changing models requires re-indexing** — the embedding dimensions are stored in `embeddings.db`. After changing `EMBEDDING_MODEL`, delete `.ai/embeddings.db` and run `brain-index run` (or restart the container and let the background watcher rebuild it).

For Docker Model Runner, prefix model names with `ai/` (e.g. `ai/mxbai-embed-large:latest`). For Ollama and LM Studio, use the bare name (e.g. `mxbai-embed-large`).

### Using Ollama instead of Docker Model Runner

```bash
EMBEDDING_BASE_URL=http://host.docker.internal:11434/v1
```

### Using LM Studio

```bash
EMBEDDING_BASE_URL=http://host.docker.internal:1234/v1
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
