# User Guide

This guide covers everything you need to know about running and using the second-brain.

## Two Images

| Image | Use when | Size |
|-------|----------|------|
| `kitchencoder/second-brain:latest` | MCP server + brain tools only — Claude Code plugin, API access, no browser UI needed | ~600MB |
| `kitchencoder/second-brain:ui` | Adds code-server web IDE — open `http://localhost:7780` in your browser | ~1.5GB |

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

## Upgrading

```bash
docker pull kitchencoder/second-brain:latest   # or :ui
docker rm -f second-brain
# Re-run your docker run command
```

Your brain data, Claude config, and shell history are preserved in named volumes. To update templates and skills inside an existing brain, run `brain-init` again — it will update staged host skills and leave existing config untouched.

No re-indexing required unless the release notes say otherwise.

## Browser UI (code-server)

> Requires the `kitchencoder/second-brain:ui` image.

A browser-based VS Code at `http://localhost:7778` — no password, single-user. This is the primary interface when running at a machine where a local editor can't be installed.

**Features:**
- Full VS Code in the browser with your brain open
- Foam extension — `[[wikilink]]` navigation, backlinks panel, graph view
- Integrated terminal running zsh with all brain tools on PATH (`brain-search`, `zk`, `brain-index`, etc.)
- Claude Code pre-configured in the terminal — connects to any Anthropic-compatible provider via your brain's `.env`

**Claude Code in the terminal:**

Claude Code is pre-wired with:
- Docker Model Runner as the LLM backend (no Anthropic API key needed)
- Brain MCP server pre-approved — all brain tools available immediately
- All skills from the active profile (global + vault tiers) seeded into `~/.claude/skills/` — see [Custom profiles](#custom-profiles) below

```bash
# In the VS Code integrated terminal, Claude Code is ready:
claude
```

**Configuring the model:**

Claude Code reads `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, and `ANTHROPIC_MODEL` from the container environment. Set them in `.env` and restart:

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

## VS Code (Host)

Open your brain folder in VS Code to get wiki-link navigation and markdown preview.

`brain-init` creates a `.vscode/` directory in the brain with recommended extensions and settings. VS Code will prompt to install them (Foam, Markdown All in One, Paste Image) — accept the prompt or run `Extensions: Show Recommended Extensions` from the command palette.

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

# List draft notes (alias: drafts)
drafts

# Full-text search with preview (alias: preview)
preview

# Semantic search (alias: search)
search "renewable energy"
search "embedding models" --limit 10
brain-search "query" --json

# Watch the background indexer log
watchlog
```

### Create notes

```bash
zk new --title "My Note"
zk new --template context-primer --title "Project X — Context"
zk new --template effort --title "Project X"
zk new --template meeting --title "Team Sync"
zk new --template daily
zk new --template spec --title "Feature Y"
zk new --template doc --title "Design notes"
zk new --template adr --title "Use SQLite for storage"
zk new --template discovery --title "Interesting idea"
```

### Index

```bash
# Full reindex (also purges stale entries)
brain-index run

# Full reindex via alias (inside the container)
reindex

# Watch for changes (incremental, runs automatically in background)
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

## Configuration

| Variable | Default | Description |
|---|---|---|
| `BRAIN_HOST_PATH` | `~/Documents/brain` | Path to your notes directory on the host — written to brain `.env` by `brain-init`, used by skills when generating `docker run` commands |
| `EMBEDDING_BASE_URL` | Docker Model Runner | OpenAI-compatible embedding endpoint |
| `EMBEDDING_MODEL` | `mxbai-embed-large` | Embedding model name — dimension auto-detected at index time |
| `OPENAI_API_KEY` | `local` | API key (any non-empty string for local endpoints) |
| `BRAIN_MCP_TRANSPORT` | `stdio` | MCP transport: `stdio` or `http` |
| `BRAIN_MCP_HOST` | `0.0.0.0` | Bind address for MCP HTTP mode |
| `BRAIN_MCP_PORT` | `7780` | Port for MCP HTTP mode |
| `BRAIN_API_HOST` | `0.0.0.0` | Bind address for the REST API |
| `BRAIN_API_PORT` | `7779` | Port for the REST API |
| `ANTHROPIC_BASE_URL` | Docker Model Runner | Claude Code LLM endpoint (**`:ui` image only**) |
| `ANTHROPIC_AUTH_TOKEN` | — | Claude Code auth token (**`:ui` image only**) |
| `ANTHROPIC_MODEL` | — | Claude Code model name (**`:ui` image only**) |
| `BRAVE_API_KEY` | — | Enables web search in Claude Code via Brave Search MCP (**`:ui` image only**) |

### Choosing an embedding model

The embedding model affects semantic search quality, indexing speed, and database size. `brain-init` defaults to `mxbai-embed-large` but you can choose a different model during setup or by editing `EMBEDDING_MODEL` in your brain's `.env`.

| Model | Dimensions | Best for | Trade-offs |
|---|---|---|---|
| `mxbai-embed-large` | 1024 | General-purpose notes, mixed content | Good balance of quality and speed |
| `nomic-embed-text` | 768 | Token-dense technical content (code, specs, architecture docs) | Higher quality on technical text, larger index |
| `all-minilm` | 384 | Large brains where speed matters | Fastest and smallest index, lower retrieval quality |

**Changing models requires re-indexing** — the embedding dimensions are stored in `embeddings.db`. After changing `EMBEDDING_MODEL`, delete `.ai/embeddings.db` and run `brain-index run`.

## Brain structure

The container works with any notes directory. On first use, `brain-init` adds:

```
your-brain/
├── .brain/               ← active profile: skills, templates, hooks (seeded by brain-init)
│   └── profile.toml
├── .zk/                  ← zk config and templates, composed from the profile
│   ├── config.toml
│   └── templates/
├── .ai/
│   ├── embeddings.db     ← sqlite-vec vector index (created by brain-index)
│   └── brain-plugin/     ← staged Claude Code plugin (global skills + MCP config)
├── .claude/
│   └── skills/           ← vault-tier skills, copied from the profile
└── .vscode/              ← VS Code workspace config (created by brain-init)
    ├── extensions.json
    └── settings.json
```

`.brain/`, `.zk/`, `.ai/`, `.claude/`, and `.vscode/` are ignored by Obsidian. The brain remains fully compatible with Obsidian on your host machine. `brain-init` auto-adds `.ai/`, `.zk/`, and `.brain/.git/` to the brain's `.gitignore` — if you sync the brain with Obsidian Sync or another tool, exclude those same paths there too.

## Custom profiles

A profile is the skills, zk templates, hooks, and Claude Code plugin identity that shape a brain — everything under `<brain>/.brain/`. Every brain has exactly one, resolved once on first `brain-init` and reseeded/updated (never hand-edited) after that.

**Default: bundled `ace`.** With no configuration, `brain-init` copies the `ace` profile baked into the image — zero config, works fully offline, no network required. This is what you get from a plain `docker run`.

**Custom profile.** Fork `profiles/ace/` from the [second-brain repo](https://github.com/thekitchencoder/second-brain), edit `profile.toml` (folders, skills, plugin identity, zk conventions) and the `skills/`, `templates/`, `hooks/` it references, then host the result as a git repository (a fork, a private repo, anything `git clone` can reach) or just a local directory.

Point a new brain at it:

```bash
# Container — via env var
docker run -d --name brain \
  -v ~/Documents/brain:/brain \
  -e BRAIN_PROFILE_REPO=https://github.com/you/my-brain-profile.git \
  -p 7779:7779 -p 7780:7780 \
  kitchencoder/second-brain:latest

# Or on the host, via brain-init directly
brain-init --profile-repo https://github.com/you/my-brain-profile.git /path/to/brain
brain-init --profile-repo /path/to/local/profile-dir /path/to/brain
```

`BRAIN_PROFILE_REPO` / `--profile-repo` is only consulted the **first** time `brain-init` runs against a vault (when `.brain/profile.toml` doesn't exist yet). A git URL or existing git repo is `git clone`d; a plain local directory is copied. Because a custom profile clone happens on first init, **that first run needs network access** — the bundled `ace` default never does, since it's copied from the image.

Once seeded, manage the profile with:

```bash
brain-profile show     # print the active profile's identity and origin
brain-profile update   # git pull the profile (no-op unless it's a git clone)
```

`brain-profile update` only does something for a cloned custom profile — the bundled/copied `ace` default isn't a git clone, so it reports there's nothing to update. To pick up new upstream `ace` skills or templates, re-run `brain-init` after upgrading the image.
