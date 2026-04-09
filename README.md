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

# 3. Start the container (choose :ui for browser-based VS Code IDE)
docker run -d --name second-brain --restart unless-stopped \
  -v ~/Documents/brain:/brain \
  -v second-brain-claude:/home/coder/.claude \
  -v second-brain-zsh:/home/coder/.zsh-data \
  -p 7779:7779 -p 7780:7780 \
  kitchencoder/second-brain:latest
```

The `brain-init` wizard will guide you through picking your model provider and embedding model (presets for Docker Model Runner, Ollama, LM Studio, and Anthropic API).

## Documentation Index

### For Users
- [User Guide](docs/user-guide.md): Installation, Browser UI, Host configuration, and how to use the brain.
- [Brain Guide](docs/brain-guide.md): Philosophy and structure of your brain (folders, frontmatter, tags).
- [MCP Server](docs/mcp-server.md): How to connect your brain to AI clients (Claude Code, Claude Desktop, Open WebUI, etc).
- [Brain Skills](docs/skills.md): Detailed list of all AI skills available for managing your brain.

### For Developers
- [Development Guide](docs/development.md): How to build the image, run in development mode, and create new skills or tools.

---

## At a glance

- **Semantic Search**: Find notes by meaning, not just keywords.
- **MCP Server**: Expose your brain tools to any Model Context Protocol client.
- **Claude Code Integration**: Custom skills for note capture, triage, and management.
- **Multi-platform**: Runs anywhere Docker does; works with Obsidian and VS Code on the host.
- **Privacy First**: Designed to run with local models via Docker Model Runner or Ollama.
