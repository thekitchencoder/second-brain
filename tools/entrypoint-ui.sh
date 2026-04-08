#!/bin/sh
# UI image entrypoint: shared setup + brain-api in background + code-server.
if [ "${1:-}" = "brain-init" ]; then shift; exec brain-init "$@"; fi
. /usr/local/lib/brain-tools/setup.sh
if [ "${BRAIN_API_DISABLED:-}" != "1" ]; then
    brain-api >> /brain/.ai/api.log 2>&1 &
fi
exec code-server --bind-addr 0.0.0.0:7778 \
    --user-data-dir /home/coder/.local/share/code-server \
    --auth none \
    /brain
