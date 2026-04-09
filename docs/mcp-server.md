# MCP server

The second-brain exposes an Model Context Protocol (MCP) server with two transports that can run **simultaneously**:

- **stdio** — on-demand via `docker exec` (always available, no config needed)
- **HTTP** — Streamable HTTP on port 7780 (persistent daemon, started when `BRAIN_MCP_TRANSPORT=http`)

Both transports share the same tools and handler logic. When you set `BRAIN_MCP_TRANSPORT=http`, the entrypoint starts the HTTP daemon as a background process alongside the indexer and REST API. The stdio transport remains available via `docker exec` regardless — it spawns a fresh process per invocation.

## Enabling HTTP transport

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

## Claude Code

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

## Claude Desktop

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

## Open WebUI

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

## LM Studio

LM Studio runs on the host and connects to the brain's HTTP transport.

With the recommended setup above (HTTP enabled, port 7780 exposed), add an MCP server in LM Studio:

- **URL:** `http://localhost:7780/mcp/`
- **Transport:** Streamable HTTP

LM Studio requires a model that supports tool/function calling (e.g. Qwen 2.5, Llama 3.x, Mistral). The model must be loaded with tool use enabled for the brain tools to appear.

## Docker MCP Toolkit (Docker Desktop 4.48+)

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

## HTTP transport reference

| Variable | Default | Description |
|---|---|---|
| `BRAIN_MCP_TRANSPORT` | `stdio` | Set to `http` to start the HTTP daemon in the entrypoint |
| `BRAIN_MCP_HOST` | `0.0.0.0` | Bind address for HTTP mode |
| `BRAIN_MCP_PORT` | `7780` | Port for HTTP mode |

The HTTP endpoint is `http://<host>:<port>/mcp/` and implements the MCP Streamable HTTP protocol (JSON-RPC over HTTP POST with SSE responses).

## Available tools

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
