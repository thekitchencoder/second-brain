# User Guide

This guide covers everything you need to know about running and using the second-brain.

## Image tiers

| Image | Use when | Size |
|-------|----------|------|
| `kitchencoder/second-brain:latest` | MCP server + brain tools only — Claude Code plugin, API access, no browser UI needed | ~600MB |
| `kitchencoder/second-brain:oauth` | Same as `:latest`, twin tag for deployments that key images by auth mode | ~600MB |
| `kitchencoder/second-brain:full` | Adds `psycopg` for the Postgres/pgvector full-stack tier | ~600MB |

**Core image:**
```bash
docker run -d --name brain \
  -v ~/Documents/brain:/brain \
  -p 7779:7779 -p 7780:7780 \
  kitchencoder/second-brain:latest
```

Want a browser IDE on top, or vectors in Postgres instead of the embedded SQLite index? See [Recipes](#recipes) below.

## Upgrading

```bash
docker pull kitchencoder/second-brain:latest
docker rm -f second-brain
# Re-run your docker run command
```

Your brain data, Claude config, and shell history are preserved in named volumes. To update templates and skills inside an existing brain, run `brain-init` again — it will update staged host skills and leave existing config untouched.

No re-indexing required unless the release notes say otherwise.

## Recipes

Two build-your-own layers on top of the core image, kept out of the published image set so their own release cadences don't leak into this one:

- [Browser IDE (code-server)](recipes/code-server.md) — the `:ui` image is deprecated (last published: 1.1.x); this recipe shows the thin `FROM kitchencoder/second-brain:latest` layer that replaces it, with Claude Code pre-installed in the terminal.
- [Full-stack tier (Postgres/pgvector) via docker-compose](recipes/full-stack-compose.md) — run the `:full` image beside Postgres so vectors (and later, policy/audit data) live in one stateful service.

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
| `ANTHROPIC_BASE_URL` | Docker Model Runner | Claude Code LLM endpoint (**only relevant if you build the [code-server recipe](recipes/code-server.md)**) |
| `ANTHROPIC_AUTH_TOKEN` | — | Claude Code auth token (**code-server recipe only**) |
| `ANTHROPIC_MODEL` | — | Claude Code model name (**code-server recipe only**) |
| `BRAVE_API_KEY` | — | Enables web search in Claude Code via Brave Search MCP (**code-server recipe only**) |

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

## Profiles

A profile is the skills, zk templates, hooks, and Claude Code plugin identity that shape a brain — everything under `<brain>/.brain/`. Every brain has exactly one, resolved once on first `brain-init` and reseeded/updated (never hand-edited) after that.

### Default: `brain-profile-ace` (remote)

With no configuration, `brain-init` clones
[brain-profile-ace](https://github.com/thekitchencoder/brain-profile-ace) —
this is what a plain `docker run` gets. **First init needs network access**;
after that the brain is self-contained and everything works offline.

### Installing a different profile

Point the first init at any profile — a published flavour like
[brain-profile-obsidian](https://github.com/thekitchencoder/brain-profile-obsidian),
your own fork, or a local directory:

```bash
# Container — via env var (git URL, cloned)
docker run -d --name brain \
  -v ~/Documents/brain:/brain \
  -e BRAIN_PROFILE_REPO=https://github.com/thekitchencoder/brain-profile-obsidian \
  -p 7779:7779 -p 7780:7780 \
  kitchencoder/second-brain:latest

# Container — via a local directory (no network needed; plain dirs are
# copied, git checkouts are cloned)
docker run -d --name brain \
  -v ~/Documents/brain:/brain \
  -v ~/profiles/my-profile:/profile-src \
  -e BRAIN_PROFILE_REPO=/profile-src \
  -p 7779:7779 -p 7780:7780 \
  kitchencoder/second-brain:latest

# Or on the host, via brain-init directly
brain-init --profile-repo https://github.com/you/my-brain-profile.git /path/to/brain
brain-init --profile-repo /path/to/local/profile-dir /path/to/brain
```

`BRAIN_PROFILE_REPO` / `--profile-repo` is only consulted the **first** time `brain-init` runs against a vault (when `.brain/profile.toml` doesn't exist yet). A git URL or existing git repo is `git clone`d; a plain local directory is copied. A local source is also the **offline / air-gapped path**: clone or copy a profile repo onto the machine first, then point `BRAIN_PROFILE_REPO` at it.

### Making your own

Fork [brain-profile-ace](https://github.com/thekitchencoder/brain-profile-ace), edit `profile.toml` (folders, skills, plugin identity, zk conventions) and the `skills/`, `templates/`, `hooks/` it references, then host the result anywhere `git clone` can reach — or keep it as a local directory. Keep the manifest's `schema = 1` line: it declares the `profile.toml` format version, and an engine older than the declared schema refuses the profile rather than misreading it.

### Managing a seeded profile

```bash
brain-profile show     # print the active profile's identity and origin
brain-profile update   # git pull --ff-only the profile clone
```

Cloned profiles (including the default) fast-forward to their repo's latest with `brain-profile update`. A profile copied from a plain local directory isn't a git clone — re-seed it by re-running `brain-init` against a fresh vault, or manage the source dir yourself.

## Running two brains on one machine

Every brain's host identity (plugin name, MCP server key, hook marker) defaults
to the profile's shared values, and two containers cannot publish the same host
ports — Docker refuses a duplicate `-p` binding. Give the second (and any
further) brain a **name** at init:

```bash
docker run --rm -it -v ~/Documents/work-brain:/brain \
  -e BRAIN_NAME=work -e BRAIN_MCP_HOST_PORT=7782 -e BRAIN_API_HOST_PORT=7781 \
  kitchencoder/second-brain:latest brain-init
# or on the host: brain-init --brain-name work --mcp-port 7782 --api-port 7781 ~/Documents/work-brain
```

The name qualifies everything the host sees — plugin `second-brain-work`, MCP
server key `brain-work`, hook marker `brain-work` — and persists in the brain's
`.env`, so container restarts restage the same identity with no flags. Start
the second container with its remapped ports and distinct container/volume
names (the init welcome text prints the exact command), then install its
plugin alongside the first:

```bash
claude plugin marketplace add ~/Documents/work-brain/.ai
claude plugin install second-brain-work
```

Renaming a brain later (`brain-init --brain-name <new>` against the same
vault) restages under the new identity and prints the exact host-side
cleanup commands: uninstall the old plugin, remove its marketplace entry,
then install the new name.

### Remote brain (tunnel / reverse proxy)

To reach a brain at a public URL instead of a local port, set the full MCP
endpoint at init — it is staged verbatim into the plugin's MCP config:

```bash
brain-init --brain-name work \
  --mcp-url https://work-brain.example.com/mcp/ ~/vaults/work-brain
```

Routing that URL to the container's port 7780 is your tunnel or reverse
proxy's job — no `-p` mapping is needed at all when the tunnel client reaches
the container over a Docker network. When the oauth tier is enabled, keep the
URL consistent with `BRAIN_AUTH_AUDIENCE` (see [auth.md](auth.md)).
