# Code-Server UI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a browser-accessible VS Code (code-server) service to the second-brain Docker stack, pre-configured as a minimal markdown IDE with wikilink navigation and Claude Code in the terminal.

**Architecture:** A separate `code-server` Docker service alongside the existing `brain` service, sharing the same vault volume mount. The code-server image bakes in Foam (wikilinks), Markdown All in One, and a trimmed VS Code `settings.json` at build time. Claude Code CLI is pre-installed so users can run it in the integrated terminal. No changes to the brain container.

**Tech Stack:** `codercom/code-server:latest`, Foam (`foam.foam-vscode`), Markdown All in One (`yzhang.markdown-all-in-one`), GitHub Markdown Preview Styles (`bierner.markdown-preview-github-styles`), Node.js npm (for Claude Code CLI, already in codercom base image).

---

## File Map

| Action | Path |
|--------|------|
| Create | `code-server/Dockerfile` |
| Create | `code-server/settings.json` |
| Create | `code-server/keybindings.json` |
| Modify | `docker-compose.yml` |
| Modify | `.env.example` |

---

### Task 1: Create code-server directory and settings

**Files:**
- Create: `code-server/settings.json`
- Create: `code-server/keybindings.json`

**Step 1: Create the VS Code settings file**

`code-server/settings.json` — minimal chrome, markdown-optimised:

```json
{
  "workbench.activityBar.visible": false,
  "workbench.statusBar.visible": false,
  "editor.minimap.enabled": false,
  "editor.wordWrap": "on",
  "editor.lineNumbers": "off",
  "editor.renderLineHighlight": "none",
  "editor.scrollBeyondLastLine": false,
  "workbench.startupEditor": "none",
  "security.workspace.trust.enabled": false,
  "files.defaultLanguage": "markdown",
  "files.watcherExclude": {
    "**/.ai/**": true,
    "**/.git/**": true,
    "**/.trash/**": true
  },
  "markdown.preview.breaks": true,
  "foam.links.hover.enable": true,
  "foam.edit.linkReferenceDefinitions": "withExtensions",
  "editor.fontFamily": "ui-monospace, 'Cascadia Code', 'Source Code Pro', Menlo, monospace",
  "editor.fontSize": 14,
  "workbench.colorTheme": "Default Dark Modern",
  "explorer.confirmDelete": false,
  "explorer.confirmDragAndDrop": false
}
```

**Step 2: Create the keybindings file**

`code-server/keybindings.json` — toggle read/edit mode with Ctrl+Shift+P shortcut (preview is built-in via Ctrl+Shift+V):

```json
[]
```

(Empty for now — VS Code's built-in Ctrl+Shift+V for markdown preview and Ctrl+K V for side-by-side are sufficient.)

**Step 3: Commit**

```bash
git add code-server/
git commit -m "feat: add code-server VS Code settings"
```

---

### Task 2: Create code-server Dockerfile

**Files:**
- Create: `code-server/Dockerfile`

**Step 1: Write the Dockerfile**

`code-server/Dockerfile`:

```dockerfile
FROM codercom/code-server:latest

USER root

# Install Claude Code CLI (requires Node.js — already present in codercom base)
RUN npm install -g @anthropic-ai/claude-code

USER coder

# Pre-install VS Code extensions
RUN code-server --install-extension foam.foam-vscode \
    && code-server --install-extension yzhang.markdown-all-in-one \
    && code-server --install-extension bierner.markdown-preview-github-styles

# Bake in settings and keybindings
COPY --chown=coder:coder settings.json /home/coder/.local/share/code-server/User/settings.json
COPY --chown=coder:coder keybindings.json /home/coder/.local/share/code-server/User/keybindings.json

# Vault is mounted at /brain — open it as the default workspace
WORKDIR /brain
```

**Step 2: Verify it builds (from repo root)**

```bash
docker build -t brain-code-server code-server/
```

Expected: build completes, extensions install without errors. This will take a few minutes on first run — the codercom base image is ~1.3 GB.

If the `@anthropic-ai/claude-code` package name is wrong (npm 404), check the current install docs at https://docs.anthropic.com/claude-code and update the package name in the RUN line.

**Step 3: Commit**

```bash
git add code-server/Dockerfile
git commit -m "feat: add code-server Dockerfile with Foam and Claude Code"
```

---

### Task 3: Add code-server service to docker-compose.yml

**Files:**
- Modify: `docker-compose.yml`

**Step 1: Read the current docker-compose.yml**

Current content (for reference):
```yaml
services:
  brain:
    image: kitchencoder/second-brain:latest
    container_name: brain
    volumes:
      - ${BRAIN_HOST_PATH}:/brain
    env_file:
      - .env
    ports:
      - "${BRAIN_API_PORT:-7779}:7779"
    stdin_open: true
    tty: true
    restart: unless-stopped
```

**Step 2: Add the code-server service**

Append the following service to `docker-compose.yml`:

```yaml
  code-server:
    build: ./code-server
    container_name: brain-ui
    volumes:
      - ${BRAIN_HOST_PATH}:/brain
    environment:
      - PASSWORD=${CODE_SERVER_PASSWORD:-changeme}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}
    ports:
      - "${CODE_SERVER_PORT:-8080}:8080"
    restart: unless-stopped
    command: --auth password /brain
```

The `command` line:
- `--auth password` — enables the built-in password prompt (password set via `PASSWORD` env var)
- `/brain` — opens the vault as the default workspace

**Step 3: Verify compose config is valid**

```bash
BRAIN_HOST_PATH=/tmp docker compose config
```

Expected: full merged config prints without errors.

**Step 4: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: add code-server service to docker-compose"
```

---

### Task 4: Update .env.example

**Files:**
- Modify: `.env.example`

**Step 1: Read .env.example**

Check the current contents first with Read tool.

**Step 2: Add code-server variables**

Add this section to `.env.example`:

```bash
# ─── Code-Server UI ────────────────────────────────────────────────────────
# Browser-accessible VS Code. Access at http://localhost:8080
CODE_SERVER_PASSWORD=changeme
CODE_SERVER_PORT=8080

# Pass your Anthropic API key so Claude Code works in the integrated terminal
ANTHROPIC_API_KEY=
```

**Step 3: Commit**

```bash
git add .env.example
git commit -m "feat: add code-server env vars to .env.example"
```

---

### Task 5: Smoke test the full stack

**Goal:** Verify the complete setup works end-to-end before writing docs.

**Step 1: Start the stack**

```bash
export BRAIN_HOST_PATH=~/path/to/your/vault
docker compose up --build code-server
```

(Start just code-server first to validate it independently.)

**Step 2: Open the UI**

Navigate to `http://localhost:8080` in a browser. Enter the password from `.env` (default: `changeme`).

Expected:
- VS Code loads in the browser
- The vault folder (`/brain`) opens in the Explorer
- Activity bar and status bar are hidden
- No minimap

**Step 3: Test wikilinks**

Open any note that contains a `[[wikilink]]`. Hover over it — Foam should show a preview. Ctrl+click (or Cmd+click on Mac) should navigate to the linked note.

If Foam hasn't activated: check the Extensions panel (Ctrl+Shift+X) — Foam should show as installed. If not, the extension install step in the Dockerfile failed; rebuild with `docker compose build --no-cache code-server`.

**Step 4: Test read mode**

Open a markdown note. Press `Ctrl+Shift+V` to open the preview pane. Verify it renders cleanly with the GitHub styling.

**Step 5: Test Claude Code in terminal**

Open the integrated terminal (`Ctrl+` ` `). Run:

```bash
claude --version
```

Expected: version string. If `command not found`, the npm install in the Dockerfile failed — check build logs.

**Step 6: Commit test confirmation (no code change — just a marker commit if all passes)**

```bash
git commit --allow-empty -m "chore: smoke test code-server stack passing"
```

---

### Task 6: Update README

**Files:**
- Modify: `README.md`

**Step 1: Read the current README**

Read `README.md` to find where services/access methods are documented.

**Step 2: Add a Code-Server UI section**

Add a new section (after the existing "Access" or "Services" section) with:

```markdown
## Browser UI (Code-Server)

A browser-accessible VS Code is available at `http://localhost:8080`.

Pre-installed extensions:
- **Foam** — `[[wikilink]]` navigation and backlinks
- **Markdown All in One** — table formatting, TOC, list continuation
- **GitHub Markdown Preview** — clean rendered preview (Ctrl+Shift+V)

**Read mode:** `Ctrl+Shift+V` opens a rendered preview pane alongside the editor.
**Edit mode:** The editor pane is always active; click it to return focus.

**Claude Code in the terminal:**
1. Open the integrated terminal: `Ctrl+` ` `
2. Set your API key: `export ANTHROPIC_API_KEY=sk-...` (or add to `.env` before starting)
3. Run: `claude`

**Password:** Set `CODE_SERVER_PASSWORD` in `.env` (default: `changeme` — change before exposing on a network).
```

**Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add code-server UI section to README"
```

---

## Known Limitations (Phase 1)

- VS Code chrome is never fully hidden — activity bar and status bar can be removed but the tab bar and title bar remain. This is a VS Code architectural constraint.
- Zen Mode (`Ctrl+K Z`) hides most chrome but must be triggered manually each session.
- `ANTHROPIC_API_KEY` must be set in `.env` before `docker compose up` — passing it at runtime in the terminal also works.
- Microsoft Marketplace extensions (Copilot) are not available in code-server (Open VSX only).
- Image size: the code-server service adds ~1.3 GB. This is a known trade-off vs a custom UI.

## Phase 2 Opportunity

If the VS Code chrome is too noisy, the natural next step is a custom SPA using CodeMirror 6 wired to the existing FastAPI. That work builds on the API that already exists — the code-server phase validates the workflow and UX requirements before investing in a custom frontend.
