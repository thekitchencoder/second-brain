# second-brain Skills for Claude Code

Skills give Claude Code the ability to operate your second-brain without any configuration beyond the MCP server being connected.

There are two tiers:

- **`skills/`** — global skills (MCP-only), available in any Claude Code session
- **`brain-skills/`** — vault-level skills (filesystem access), auto-load when Claude Code is opened inside the vault

## Install

**Global skills** — available everywhere the brain MCP is connected:

```bash
# Symlink (recommended — picks up updates automatically)
for d in skills/brain-*/; do ln -sf "$PWD/$d" ~/.claude/skills/; done

# Or copy (one-off)
cp -r skills/brain-* ~/.claude/skills/
```

**Vault-level skills** — auto-load when Claude Code opens the vault root:

```bash
# Symlink
for d in brain-skills/brain-*/; do ln -sf "$PWD/$d" "$BRAIN_HOST_PATH/.claude/skills/"; done

# Or copy
cp -r brain-skills/brain-* "$BRAIN_HOST_PATH/.claude/skills/"
```

## Global skills (`skills/`)

These use MCP tools only — no direct filesystem access needed. Work from any project directory.

| Skill | Trigger | What it does |
|---|---|---|
| `brain-capture` | "I've had an idea about X" | Conversational capture → creates note → waits for edit → wires in wikilinks |
| `brain-connect` | "Find connections for this note" | Surfaces related notes via semantic search + keyword search, offers to patch wikilinks |
| `brain-context` | Working on a named topic or project | Searches the brain for prior context before starting work |
| `brain-create-effort` | "Create a new effort for X" | Scaffolds a new effort note with goal, intensity state, and optional context primer |
| `brain-distil` | "Create a context primer from these sources" | Synthesises one or more source notes into a concise context primer for an effort |
| `brain-effort` | "Where does X effort stand?" | Status overview of all notes in an effort — groups by status, flags orphans |
| `brain-project` | "start a new project", "set up a project" | Scaffolds a new effort with context primer — two seed documents |
| `brain-save` | "remember", "save", "capture", "note down" | Saves something to the brain with correct frontmatter and placement |
| `brain-surface` | "What's simmering?", "surface parked work" | Surfaces `intensity: simmering` efforts oldest-first, shows saved next steps |
| `brain-triage` | "Process my inbox", "triage" | Works through `status: raw` notes one at a time — promote, archive, or defer |

## Vault-level skills (`brain-skills/`)

These load only when Claude Code is opened at the vault root. They need direct filesystem access (Glob, Grep, Read, Edit, `mv`).

| Skill | Trigger | What it does |
|---|---|---|
| `brain-daily` | "Start my day", "daily note" | Creates today's daily note, carries forward open items, shows inbox count |
| `brain-extract` | "Pull ideas out of this note" | Extracts atomic ideas from a long note into separate Cards with wikilinks back |
| `brain-hygiene` | "tidy", "audit", "health-check" | Checks frontmatter, orphaned notes, broken wikilinks (with repair), stale drafts, trash |
| `brain-rename` | "Rename this note" | Renames a file and updates every `[[wikilink]]` pointing to it across the vault |
| `brain-reorganise` | "Move X into effort Y", "consolidate" | Moves notes into an effort via `brain-rename` to preserve all wikilinks |

## Requirements

- The `brain` MCP server must be connected in Claude Code (`.mcp.json` configured)
- The brain container must be running (`docker compose up -d`)
