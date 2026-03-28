#!/bin/sh
# Idempotently seed Claude Code user config from the baked-in seed directory.
# Files are only written on first run — edits in the volume survive rebuilds.
# ~/.claude.json lives inside the volume and is symlinked from the home dir
# so Claude Code can write session state without clobbering it on rebuild.
CLAUDE_DIR=/home/coder/.claude
SEED_DIR=/usr/local/lib/brain-tools/claude-seed
mkdir -p "$CLAUDE_DIR"
for f in "$SEED_DIR"/*; do
    dest="$CLAUDE_DIR/$(basename "$f")"
    [ ! -e "$dest" ] && cp -r "$f" "$dest"
done
if [ ! -f "$CLAUDE_DIR/.claude.json" ]; then
    cp "$SEED_DIR/.claude.json" "$CLAUDE_DIR/.claude.json"
fi
ln -sf "$CLAUDE_DIR/.claude.json" /home/coder/.claude.json

# Start brain background services, then hand off to code-server.
#
# The watcher requires only the embedding model to be reachable — it has
# no dependency on brain-init or zk. If the model is not yet available,
# the watcher will retry every 30 seconds until it connects.
if [ -d /brain ]; then
    mkdir -p /brain/.ai
    (
        RETRY_DELAY=30
        while true; do
            brain-index watch >> /brain/.ai/watch.log 2>&1
            EXIT_CODE=$?
            if [ "$EXIT_CODE" -eq 1 ]; then
                echo "$(date): brain-index watch exited with error (code $EXIT_CODE) — not retrying. Check watch.log for details." >> /brain/.ai/watch.log
                break
            fi
            echo "$(date): brain-index watch exited (code $EXIT_CODE), retrying in ${RETRY_DELAY}s..." >> /brain/.ai/watch.log
            sleep "$RETRY_DELAY"
        done
    ) &
    # Start the REST API server (unless explicitly disabled)
    if [ "${BRAIN_API_DISABLED:-}" != "1" ]; then
        brain-api >> /brain/.ai/api.log 2>&1 &
    fi
    # Optionally start the MCP server in HTTP mode for remote MCP clients
    if [ "${BRAIN_MCP_TRANSPORT:-}" = "http" ]; then
        BRAIN_MCP_TRANSPORT=http brain-mcp-server >> /brain/.ai/mcp-http.log 2>&1 &
    fi
fi
# Hand off to code-server's entrypoint (passes "$@" = "--auth none /brain")
exec /usr/bin/entrypoint.sh "$@"
