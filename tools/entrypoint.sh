#!/bin/sh
# Base image entrypoint: shared setup + brain-api in foreground.
if [ "${1:-}" = "brain-init" ]; then shift; exec brain-init "$@"; fi
. /usr/local/lib/brain-tools/setup.sh
exec brain-api
