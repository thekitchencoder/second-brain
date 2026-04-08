#!/usr/bin/env bash
# Syncs the version from pyproject.toml into Dockerfile LABEL
# Run after updating pyproject.toml version field.
set -euo pipefail

# Always run from the repo root regardless of where the script is invoked from
cd "$(dirname "$0")/.."

VERSION=$(grep '^version' pyproject.toml | sed 's/version = "\(.*\)"/\1/')
[[ -n "$VERSION" ]] || { echo "ERROR: could not parse version from pyproject.toml" >&2; exit 1; }

echo "Syncing version $VERSION to Dockerfile..."
perl -i -pe "s/^LABEL version=.*/LABEL version=\"$VERSION\"/" Dockerfile
echo "Synced Dockerfile."
perl -i -pe "s/^LABEL version=.*/LABEL version=\"$VERSION\"/" Dockerfile.ui
echo "Synced Dockerfile.ui."
echo "Done."
