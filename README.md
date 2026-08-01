# second-brain

> [!WARNING]
> **Mothballed — August 2026. This repository is archived and read-only.**
>
> second-brain v2 is end-of-life. It carried too much v1 baggage, and the profile
> mechanism never worked as intended in real use. A ground-up successor — **stacks**,
> designed from scratch against actual requirements rather than v2's constraints — is
> in development and will take its place. It is not public yet.
>
> The published images (`kitchencoder/second-brain:latest`, `:oauth`, `:full`) remain
> pullable and existing containers keep running, but there will be no further releases,
> fixes, or support. Everything below describes v2 as it was left at
> [v2.0.0](https://github.com/thekitchencoder/second-brain/releases/tag/v2.0.0).

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
- [CHANGELOG](CHANGELOG.md): What has landed in each release.

---

## At a glance

- **Semantic Search**: Find notes by meaning, not just keywords.
- **MCP Server**: Expose your brain tools to any Model Context Protocol client.
- **Claude Code Integration**: Custom skills for note capture, triage, and management.
- **Profiles**: One engine runs many brains — the default [ace profile](https://github.com/thekitchencoder/brain-profile-ace) is cloned on first init; flavours like [obsidian](https://github.com/thekitchencoder/brain-profile-obsidian) and custom forks (folders, skills, templates, queryable fields) are one env var away.
- **Multi-platform**: Runs anywhere Docker does; works with Obsidian and VS Code on the host.
- **Privacy First**: Designed to run with local models via Docker Model Runner or Ollama.

## Roadmap

The **profile refactor** shipped in 2.0.0: the *engine* (this Docker image: search, MCP,
editing, auth) is fully separated from the *profile* (a brain's folders, templates,
skills, identity, and queryable fields) — **one engine, many brains, no fork**.

**Landed:**
- Profile-driven engine — a brain self-describes via `<brain>/.brain/`
- Profiles live in their own public repos ([ace](https://github.com/thekitchencoder/brain-profile-ace), [obsidian](https://github.com/thekitchencoder/brain-profile-obsidian)); the default is cloned from `brain-profile-ace` on first init, with `profile.toml` schema versioning
- Profile-driven queries — metadata filters adapt to each profile's fields
- Auth — static per-principal bearer tokens and an OAuth 2.1 authorization server behind
  `profile.auth.mode` (default `none`). See the [Authentication guide](docs/auth.md).
- Content visibility / RBAC — role-based read/write layers, oracle-safe. See [docs/rbac.md](docs/rbac.md).
- Full-stack tier — Postgres/pgvector index store, admin plane + agent credentials,
  per-principal retrieval log
- Per-brain host identity (`brain-init --brain-name`) and a configurable MCP endpoint for
  tunnel/reverse-proxy deployments

**Planned:**
- Admin UI for the RBAC tier
- Community profiles

Custom profiles are covered in the [User Guide](docs/user-guide.md); the running record
is in the [CHANGELOG](CHANGELOG.md).
