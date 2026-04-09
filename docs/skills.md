# Brain Skills

There are two tiers of skills in the second-brain:

- **Global** (`skills/`) — for Claude Code on the host machine, from any project directory. Use MCP tools only. Installed via the Claude Code plugin.
- **Brain-local** (`brain-skills/`) — auto-installed by `brain-init` into `<brain>/.claude/skills/`. Load when Claude Code is opened at the brain root. Use MCP for semantic search and direct filesystem tools for file I/O.

## Global skills (host install via plugin)

Global skills let Claude Code access your brain from any project on your host machine (e.g. while coding, save context back to the brain). `brain-init` stages them as a Claude Code plugin:

```bash
claude plugin marketplace add ~/Documents/brain/.ai
claude plugin install second-brain
```

This also registers the brain MCP server — no separate `claude mcp add` needed.

| Skill | Trigger | What it does |
|---|---|---|
| `brain-capture` | "I've had an idea about X" | Conversational capture → creates note → waits for edit → wires in wikilinks |
| `brain-connect` | "Find connections for this note" | Surfaces related notes, offers to patch wikilinks |
| `brain-context` | Working on a named topic or project | Searches the brain for prior context before starting work |
| `brain-create-effort` | "Create a new effort for X" | Scaffolds a new effort note with goal, intensity state, and optional context primer |
| `brain-effort` | "Where does X effort stand?" | Status overview of all notes in an effort, flags orphans and missing stubs |
| `brain-project` | "start a new project" | Scaffolds a new effort with context primer |
| `brain-save` | "remember", "save", "capture" | Saves something to the brain with correct frontmatter and placement |
| `brain-setup` | "Set up my brain" / first-time brain setup | Guided brain setup flow with pre-flight check and step-by-step instructions |
| `brain-surface` | "What's simmering?" | Surfaces efforts with `intensity: simmering`, shows saved next steps, offers to resume |
| `brain-triage` | "Process my inbox" | Works through `status: raw` notes one at a time — promote, archive, or defer |
| `brain-distil` | "Distil my research into a primer" | Synthesises one or more source notes into a concise context primer for an effort |

## Brain-local skills (auto-installed)

These are installed automatically when the container starts or when you run `brain-init`. No manual setup needed.

| Skill | Trigger | What it does |
|---|---|---|
| `brain-daily` | "Start my day" | Creates today's daily note, carries forward open items, shows inbox count |
| `brain-extract` | "Pull the ideas out of this note" | Extracts atomic ideas from a long note into separate Cards with wikilinks back |
| `brain-hygiene` | "tidy", "audit", "health-check" | Checks frontmatter, orphaned notes, broken wikilinks, stale drafts |
| `brain-rename` | "Rename this note" | Renames a file and updates every `[[wikilink]]` pointing to it across the brain |
| `brain-reorganise` | "Move X into effort Y" | Moves/consolidates notes into an effort via `brain-rename` to preserve all wikilinks |

## Claude Desktop / claude.ai

Global skills can be uploaded as ZIP files:

```bash
cd skills && for d in brain-*/; do zip -r "${d%/}.zip" "$d"; done
```

- **Claude Desktop:** Settings → Customize → Skills → upload each `.zip`
- **claude.ai:** Open a Project → Project settings → Skills → upload each `.zip`

See [`skills/README.md`](../skills/README.md) for details on what each skill does.
