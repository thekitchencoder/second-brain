#!/bin/sh
# Start the brain indexer in watch mode as a background service.
# Logs go to /brain/.ai/watch.log alongside the embeddings DB.
#
# The watcher requires only the embedding model to be reachable — it has
# no dependency on brain-init or zk. If the model is not yet available,
# the watcher will retry every 30 seconds until it connects.
if [ -d /brain ]; then
    mkdir -p /brain/.ai
    (
        while true; do
            brain-index watch >> /brain/.ai/watch.log 2>&1
            echo "$(date): brain-index watch exited, retrying in 30s..." >> /brain/.ai/watch.log
            sleep 30
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
exec "$@"
