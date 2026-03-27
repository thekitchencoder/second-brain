#!/bin/sh
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
# When using Docker Model Runner, write a Claude Code settings.json that sets
# the default model — so the user can just run "claude" without --model.
# Only written if ANTHROPIC_BASE_URL points at model-runner and the file is absent.
if [ "${ANTHROPIC_BASE_URL:-}" = "http://model-runner.docker.internal:12434" ] \
   && [ ! -f /home/coder/.claude/settings.json ]; then
    mkdir -p /home/coder/.claude
    printf '{"model":"gpt-oss:32k"}\n' > /home/coder/.claude/settings.json
fi
# Hand off to code-server's entrypoint (passes "$@" = "--auth none /brain")
exec /usr/bin/entrypoint.sh "$@"
