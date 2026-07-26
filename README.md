# second-brain

Docker container for brain management: zk, semantic search, and Model Context Protocol (MCP) server for Claude Code and Claude Desktop.

The second-brain provides a set of tools and skills to manage a brain of markdown notes using semantic search, structured metadata, and AI capabilities.

## Quick start

No repository clone is required to run the second-brain — the Docker image includes everything needed.

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

The `brain-init` wizard will guide you through picking your model provider and embedding model (presets for Docker Model Runner, Ollama, LM Studio, and Anthropic API).

**Tiers:** the quickstart above is the core image (MCP + brain tools only). Want a browser IDE on top? See the [code-server recipe](docs/recipes/code-server.md). Want vectors in Postgres instead of the embedded SQLite index? See the [full-stack compose recipe](docs/recipes/full-stack-compose.md).

## Documentation Index

### For Users
- [User Guide](docs/user-guide.md): Installation, Host configuration, and how to use the brain.
- [Brain Guide](docs/brain-guide.md): Philosophy and structure of your brain (folders, frontmatter, tags).
- [MCP Server](docs/mcp-server.md): How to connect your brain to AI clients (Claude Code, Claude Desktop, Open WebUI, etc).
- [Brain Skills](docs/skills.md): Detailed list of all AI skills available for managing your brain.
- [Authentication](docs/auth.md): Gate the REST API and MCP HTTP transport behind static tokens or OAuth 2.1 (`profile.auth.mode`, default off).
- [Recipes](docs/recipes/): Browser IDE (code-server) and full-stack (Postgres/pgvector) layers on top of the core image.

### For Developers
- [Development Guide](docs/development.md): How to build the image, run in development mode, and create new skills or tools.
- [CHANGELOG](CHANGELOG.md): What has landed on `main`, and the release cadence during the profile refactor.

---

## At a glance

- **Semantic Search**: Find notes by meaning, not just keywords.
- **MCP Server**: Expose your brain tools to any Model Context Protocol client.
- **Claude Code Integration**: Custom skills for note capture, triage, and management.
- **Profiles**: One engine runs many brains — the bundled `ace` profile is the zero-config default; custom profiles (folders, skills, templates, queryable fields) are cloneable and forkable.
- **Multi-platform**: Runs anywhere Docker does; works with Obsidian and VS Code on the host.
- **Privacy First**: Designed to run with local models via Docker Model Runner or Ollama.

## Roadmap

second-brain is mid-way through a **profile refactor** — separating the *engine* (this
Docker image: search, MCP, editing) from a *profile* (a brain's folders, templates,
skills, identity, and queryable fields). The goal: **one engine, many brains, no fork** —
so the same image can run a work brain, a home brain, and a private one, each with its own
character.

**Landed on `main`** (unreleased):
- Profile-driven engine — a brain self-describes via `<brain>/.brain/`
- Custom-profile distribution — clone/update a profile; bundled `ace` stays the zero-config default
- Profile-driven queries — metadata filters adapt to each profile's fields
- Auth gate (Seam 6) — static per-principal bearer tokens and an OAuth 2.1 authorization
  server, shipped behind `profile.auth.mode = "oauth"` (default `none`, a total no-op). See
  the [Authentication guide](docs/auth.md).

**Planned:**
- Content visibility / RBAC enforcement built on top of the auth gate (Seam 7)
- Public, forkable profile repositories (community profiles)

These land as **interim pull requests that merge without cutting a release** — the image on
`:latest` is the last tagged version, and a version bump and new release will come once the
refactor reaches its end state. Custom profiles are covered in the
[User Guide](docs/user-guide.md); the running record is in the [CHANGELOG](CHANGELOG.md).
