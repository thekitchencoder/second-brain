#!/bin/sh
# Start the brain indexer in watch mode as a background service.
# Logs go to /brain/.ai/watch.log alongside the embeddings DB.
if [ -d /brain ]; then
    mkdir -p /brain/.ai
    brain-index watch >> /brain/.ai/watch.log 2>&1 &
fi
exec "$@"
