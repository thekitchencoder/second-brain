# Development Guide

This guide is for developers who want to modify the second-brain, add new skills, or improve the MCP server.

## Project Structure

- `tools/lib/`: Python library for brain tools (indexing, search, MCP logic).
- `skills/`: Global Claude Code skills (MCP-only).
- `brain-skills/`: Brain-local Claude Code skills (filesystem access).
- `zk/templates/`: Note templates used by `zk`.
- `claude/`: MCP server entrypoint and configuration.
- `code-server/`: Browser IDE configuration.
- `scripts/`: Initialization and helper scripts.

## Local Development

The project uses `Task` (taskfile.dev) to manage common development workflows.

### 1. Build the dev image
```bash
task build
```

### 2. Start the dev container
The dev container bind-mounts the local `tools/lib` and `zk/templates` folders into the container, allowing for live-reloading of logic changes.
```bash
task up
```

### 3. Build and run the UI image
```bash
task build-ui
task up-ui
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

The `Dockerfile` and `Dockerfile.ui` are used to build the production images. 
- `Dockerfile`: Base image with MCP server and brain tools.
- `Dockerfile.ui`: Adds code-server on top of the base image.

When building the UI image, you can specify the base image:
```bash
docker build -f Dockerfile.ui --build-arg BASE_IMAGE=kitchencoder/second-brain:latest -t kitchencoder/second-brain:ui .
```
