# Development Guide

This guide is for developers who want to modify the second-brain, add new skills, or improve the MCP server.

## Project Structure

- `tools/lib/`: Python library for brain tools (indexing, search, MCP logic).
- `profiles/ace/`: The bundled default profile — its `skills/global/` (MCP-only) and `skills/vault/` (filesystem-access) skills, `templates/`, hooks, and `profile.toml`. Skills and templates are sourced from the active profile, not top-level dirs.
- `claude/seed/`: The container's own Claude Code config seed.
- `scripts/`: Initialization and helper scripts.

## Local Development

The project uses `Task` (taskfile.dev) to manage common development workflows.

### 1. Build the dev image
```bash
task build
```

### 2. Start the dev container
The dev container bind-mounts the local `tools/lib` and `profiles/ace/templates` folders into the container, allowing for live-reloading of logic and template changes.
```bash
task up
```

## Developing Skills

### Syncing skills live
If you're modifying skills and want to test them without restarting the container:
```bash
task sync-skills
```
Then run `/reload` in your Claude Code session.

### Full sync (Code + Skills + Templates)
To sync everything without a rebuild:
```bash
task sync
```

## Testing

Run unit tests (requires `pytest` and project dependencies installed locally):
```bash
task test
```

Integration tests usually require the container to be running.

## Building for Release

The `Dockerfile` and `Dockerfile.full` are used to build the production images.
- `Dockerfile`: Base image with MCP server and brain tools — published as `:latest` (plus `:oauth` twin tags).
- `Dockerfile.full`: Adds `psycopg` on top of the base image, for the Postgres/pgvector tier — published as `:full`.

When building the full-stack image, you can specify the base image:
```bash
docker build -f Dockerfile.full --build-arg BASE_IMAGE=kitchencoder/second-brain:latest -t kitchencoder/second-brain:full .
```

Want a browser IDE instead? The `:ui` image is no longer published — see the [code-server recipe](recipes/code-server.md) for a build-your-own layer.
