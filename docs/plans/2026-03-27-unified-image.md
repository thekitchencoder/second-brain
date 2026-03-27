# Unified code-server Image Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Collapse the two-container setup (brain + code-server) into a single image based on `codercom/code-server:latest`, so brain tools are available directly in the VS Code terminal.

**Architecture:** The main `Dockerfile` is rebased from `python:3.12-slim` to `codercom/code-server:latest`. All brain tooling (Python, zk, sqlite-vec, brain scripts) is layered on top as root, then VS Code extensions are installed as the `coder` user. `tools/entrypoint.sh` is updated to start brain background services and then chain to codercom's own `/usr/bin/entrypoint.sh`, which starts code-server. `docker-compose.yml` collapses to a single service. `code-server/Dockerfile` is deleted.

**Tech Stack:** `codercom/code-server:latest` (Ubuntu base), Python 3 + pip, sqlite-vec (source build), zk, Claude Code CLI (npm), Foam + Markdown All in One + GitHub Markdown Preview (VS Code extensions).

---

## File Map

| Action | Path |
|--------|------|
| Modify | `Dockerfile` |
| Modify | `tools/entrypoint.sh` |
| Modify | `docker-compose.yml` |
| Modify | `code-server/settings.json` |
| Delete | `code-server/Dockerfile` |

---

### Task 1: Rewrite the main Dockerfile

**Files:**
- Modify: `Dockerfile`

**Step 1: Read the current Dockerfile**

Read `Dockerfile` to understand the current structure before overwriting.

**Step 2: Replace the Dockerfile**

Write the following content to `Dockerfile` (this is a complete replacement):

```dockerfile
FROM codercom/code-server:latest

LABEL version="0.3.0"

ARG ZK_VERSION=0.14.1
ARG SQLITE_VEC_VERSION=0.1.6

USER root

# Allow pip to install into the system Python without a venv
ENV PIP_BREAK_SYSTEM_PACKAGES=1

# System tools + Python
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    nodejs \
    npm \
    curl \
    fzf \
    ripgrep \
    bat \
    zsh \
    git \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/batcat /usr/local/bin/bat

# zk binary
RUN ARCH=$(dpkg --print-architecture) && \
    case "$ARCH" in \
      amd64) ZK_ARCH="linux-amd64" ;; \
      arm64) ZK_ARCH="linux-arm64" ;; \
      *) echo "Unsupported arch: $ARCH" && exit 1 ;; \
    esac && \
    curl -fsSL "https://github.com/zk-org/zk/releases/download/v${ZK_VERSION}/zk-v${ZK_VERSION}-${ZK_ARCH}.tar.gz" \
    | tar xz -C /usr/local/bin/ zk && \
    chmod +x /usr/local/bin/zk

# Python dependencies (excluding sqlite-vec — built from source below)
COPY requirements.txt /tmp/requirements.txt
RUN python3 -m pip install --no-cache-dir \
    $(grep -v sqlite-vec /tmp/requirements.txt | tr '\n' ' ')

# Build sqlite-vec from source (PyPI aarch64 wheel contains a 32-bit binary)
RUN apt-get update && apt-get install -y --no-install-recommends gcc libsqlite3-dev wget \
    && cd /tmp \
    && wget -q "https://github.com/asg017/sqlite-vec/releases/download/v${SQLITE_VEC_VERSION}/sqlite-vec-${SQLITE_VEC_VERSION}-amalgamation.tar.gz" \
    && tar xzf "sqlite-vec-${SQLITE_VEC_VERSION}-amalgamation.tar.gz" \
    && python3 -m pip install --no-cache-dir "sqlite-vec>=${SQLITE_VEC_VERSION}" \
    && SITE_PACKAGES=$(python3 -c "import site; print(site.getsitepackages()[0])") \
    && gcc -shared -fPIC -I/usr/include -o "${SITE_PACKAGES}/sqlite_vec/vec0.so" sqlite-vec.c -lm \
    && apt-get remove -y gcc libsqlite3-dev wget \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/* /tmp/sqlite-vec*

# Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Brain tools
COPY tools/ /usr/local/lib/brain-tools/
COPY zk/ /usr/local/lib/brain-tools/zk/
COPY vscode/ /usr/local/lib/brain-tools/vscode/
RUN chmod +x /usr/local/lib/brain-tools/brain-index \
              /usr/local/lib/brain-tools/brain-search \
              /usr/local/lib/brain-tools/brain-mcp-server \
              /usr/local/lib/brain-tools/brain-api \
              /usr/local/lib/brain-tools/brain-init \
              /usr/local/lib/brain-tools/brain-template-sync \
              /usr/local/lib/brain-tools/entrypoint.sh

# Shell environment for coder user (brain aliases, prompt)
COPY tools/brain.zshrc /home/coder/.zshrc
RUN chown coder:coder /home/coder/.zshrc

# Add brain tools to PATH and Python path (for all users)
ENV PATH="/usr/local/lib/brain-tools:$PATH"
ENV PYTHONPATH="/usr/local/lib/brain-tools"

EXPOSE 7779 8080

# VS Code extensions — must run as coder user
USER coder
RUN code-server --install-extension foam.foam-vscode \
    && code-server --install-extension yzhang.markdown-all-in-one \
    && code-server --install-extension bierner.markdown-preview-github-styles

# Bake in settings and keybindings
COPY --chown=coder:coder code-server/settings.json /home/coder/.local/share/code-server/User/settings.json
COPY --chown=coder:coder code-server/keybindings.json /home/coder/.local/share/code-server/User/keybindings.json

USER root

WORKDIR /brain
ENTRYPOINT ["/usr/local/lib/brain-tools/entrypoint.sh"]
CMD ["--auth", "none", "/brain"]
```

Key changes from the old Dockerfile:
- `FROM` changed to `codercom/code-server:latest`
- `python3` and `python3-pip` installed via apt (Ubuntu package names)
- `nodejs` and `npm` installed via apt (needed for Claude Code; not on root PATH in codercom base)
- `PIP_BREAK_SYSTEM_PACKAGES=1` set so pip can install system-wide without a venv
- sqlite-vec `.so` path is now detected dynamically via `site.getsitepackages()` instead of hardcoded `python3.12`
- Claude Code installed via npm (now in the same image)
- `brain.zshrc` copied to `/home/coder/.zshrc` (not `/root/.zshrc`)
- VS Code extension installation and settings COPY moved into this Dockerfile
- `EXPOSE 8080` added alongside 7779
- `CMD` changed from `["zsh"]` to `["--auth", "none", "/brain"]`

**Step 3: Verify it looks right**

Read the updated `Dockerfile` and confirm the structure looks correct.

**Step 4: Commit**

```bash
git add Dockerfile
git commit -m "feat: rebase image on codercom/code-server, merge brain tools into single image"
```

---

### Task 2: Update entrypoint.sh to chain to code-server

**Files:**
- Modify: `tools/entrypoint.sh`

**Step 1: Read the current entrypoint**

Read `tools/entrypoint.sh` to understand the current structure.

**Step 2: Replace the final `exec "$@"` line**

The only change is the last line: instead of `exec "$@"` (which would exec whatever CMD is — now `--auth none /brain`, which isn't a valid command), we chain to codercom's own entrypoint which knows how to start code-server.

Change the last line from:
```sh
exec "$@"
```

To:
```sh
exec /usr/bin/entrypoint.sh "$@"
```

The full updated file:
```sh
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
# Hand off to code-server's entrypoint (passes "$@" = "--auth none /brain")
exec /usr/bin/entrypoint.sh "$@"
```

**Step 3: Commit**

```bash
git add tools/entrypoint.sh
git commit -m "feat: chain entrypoint to code-server after starting brain services"
```

---

### Task 3: Add zsh as the default VS Code terminal profile

**Files:**
- Modify: `code-server/settings.json`

**Step 1: Read current settings.json**

Read `code-server/settings.json`.

**Step 2: Add the terminal profile setting**

Add `"terminal.integrated.defaultProfile.linux": "zsh"` to the settings so the VS Code integrated terminal opens zsh (which loads `/home/coder/.zshrc` with the brain aliases).

Add before the closing `}`:
```json
  "terminal.integrated.defaultProfile.linux": "zsh"
```

**Step 3: Commit**

```bash
git add code-server/settings.json
git commit -m "feat: set zsh as default terminal profile so brain aliases are available"
```

---

### Task 4: Collapse docker-compose.yml to a single service

**Files:**
- Modify: `docker-compose.yml`

**Step 1: Read current docker-compose.yml**

Read `docker-compose.yml`.

**Step 2: Replace with single-service compose file**

Write the following complete replacement:

```yaml
services:
  brain:
    build: .
    image: kitchencoder/second-brain:latest
    container_name: brain
    volumes:
      # BRAIN_HOST_PATH must be set in the shell environment before running
      # docker compose — it is not reliably read from .env across all platforms.
      # Set it explicitly: export BRAIN_HOST_PATH=~/Documents/brain
      - ${BRAIN_HOST_PATH}:/brain
      - code-server-data:/home/coder/.local/share/code-server
    env_file:
      - .env
    ports:
      - "${BRAIN_API_PORT:-7779}:7779"
      - "${CODE_SERVER_PORT:-8080}:8080"
    stdin_open: true
    tty: true
    restart: unless-stopped

volumes:
  code-server-data:
```

Notes:
- `build: .` causes `docker compose up --build` to build from the root `Dockerfile`
- `image:` still names it `kitchencoder/second-brain:latest` for the release pipeline
- Both ports exposed in the single service
- `code-server-data` volume retained so UI state (hidden panels, etc.) persists
- `stdin_open: true` + `tty: true` retained for MCP stdio transport
- No `command:` override — the Dockerfile `CMD ["--auth", "none", "/brain"]` is used

**Step 3: Verify compose config is valid**

```bash
BRAIN_HOST_PATH=/tmp docker compose config
```

Expected: single `brain` service with both ports, no `code-server` service.

**Step 4: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: collapse to single service in docker-compose"
```

---

### Task 4a: Mount host Claude config into the container

**Files:**
- Modify: `docker-compose.yml`

**Step 1: Add the Claude config bind mount**

Add one line to the `volumes:` block of the `brain` service:

```yaml
      - ${HOME}/.claude:/home/coder/.claude:ro
```

The `:ro` flag makes it read-only so the container can use your config, skills, memory, and MCP settings without being able to modify them.

Full updated `volumes:` block for reference:
```yaml
    volumes:
      - ${BRAIN_HOST_PATH}:/brain
      - ${HOME}/.claude:/home/coder/.claude:ro
      - code-server-data:/home/coder/.local/share/code-server
```

**Step 2: Verify compose config**

```bash
BRAIN_HOST_PATH=/tmp docker compose config
```

Expected: `~/.claude` bind mount appears in the brain service volumes list.

**Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: mount host ~/.claude into container for Claude Code config and skills"
```

---

### Task 5: Delete code-server/Dockerfile

**Files:**
- Delete: `code-server/Dockerfile`

`code-server/settings.json` and `code-server/keybindings.json` are **kept** — they are still referenced by COPY in the root Dockerfile.

**Step 1: Delete the file**

```bash
git rm code-server/Dockerfile
```

**Step 2: Commit**

```bash
git commit -m "chore: remove code-server/Dockerfile (absorbed into root Dockerfile)"
```

---

### Task 6: Build and smoke test

**Goal:** Verify the unified image builds, starts correctly, and all features work.

**Step 1: Build the unified image**

```bash
export BRAIN_HOST_PATH=~/path/to/your/vault
docker compose up --build
```

This will take several minutes on first build. Watch for:
- Python deps installing cleanly
- sqlite-vec `.so` compiling without errors
- Claude Code npm install succeeding
- VS Code extensions installing as coder user
- Container starting and code-server coming up on port 8080

If the build fails at the sqlite-vec step with a path error, the `site.getsitepackages()` approach likely returned a path where the `.so` doesn't need to go. Verify by running `python3 -c "import site; print(site.getsitepackages())"` inside the container.

If `python3` gives Python 3.10 and brain tools fail on syntax, the codercom base image is Ubuntu 22.04. Install Python 3.12 via the deadsnakes PPA (see Appendix below).

**Step 2: Open the UI**

Navigate to `http://localhost:8080`. Expected:
- VS Code loads, vault opens
- Activity bar and status bar hidden
- No minimap

**Step 3: Test the terminal**

Open terminal (`Ctrl+` `` ` ``). Expected:
- Shell is zsh (not bash)
- Prompt shows `[brain] ~/...`
- `brain-search "test query"` runs without "command not found"
- `zk list` runs without "command not found"
- `claude --version` shows a version string

**Step 4: Test wikilinks**

Open a note with `[[wikilinks]]`. Hover to see preview, Ctrl+click to navigate.

**Step 5: Test the brain API**

```bash
curl http://localhost:7779/api/health
```

Expected: `{"status": "ok"}` or similar.

**Step 6: Test MCP stdio**

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}' \
  | docker exec -i brain brain-mcp-server
```

Expected: JSON response with server capabilities.

**Step 7: Commit a smoke test marker**

```bash
git commit --allow-empty -m "chore: unified image smoke test passing"
```

---

### Task 7: Update README

**Files:**
- Modify: `README.md`

**Step 1: Read the current README**

Read `README.md`.

**Step 2: Update the setup/services section**

Update the README to reflect:
- Single image, single service
- Both the brain API (7779) and the VS Code UI (8080) come from the same container
- Brain tools (`brain-search`, `zk`, `brain-index`) are available in the VS Code terminal
- Remove any reference to a separate `code-server` service

**Step 3: Commit**

```bash
git add README.md
git commit -m "docs: update README for unified single-image setup"
```

---

## Appendix: Python 3.12 via deadsnakes (if needed)

If the codercom base is Ubuntu 22.04 and Python 3.10 causes compatibility errors, replace the Python install block in the Dockerfile with:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
    python3.12 \
    python3.12-distutils \
    python3-pip \
    ...
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1
```

Then use `python3.12 -m pip` instead of `python3 -m pip` throughout.

## Known Trade-offs vs Two-Image Setup

| Concern | Impact |
|---|---|
| Larger single image | Expected — codercom Ubuntu base is larger than python:3.12-slim. Total size is likely less than two images combined. |
| Ubuntu Python vs Debian Python | May be 3.10 instead of 3.12. sqlite-vec path is now dynamic so that specific issue is resolved. |
| Release pipeline | `image: kitchencoder/second-brain:latest` is still set, so the existing GitHub release workflow works unchanged. |
