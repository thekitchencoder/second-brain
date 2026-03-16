# second-brain Skills for Claude Code

These skills give Claude Code the ability to use your second-brain without any configuration beyond the MCP server being connected.

## Install

Copy the skill directories to your Claude skills folder:

```bash
cp -r skills/brain-* ~/.claude/skills/
```

## Skills

| Skill | Trigger | What it does |
|-------|---------|--------------|
| `brain-context` | Working on a topic/project | Searches the brain for prior context before starting work |
| `brain-save` | "remember", "save", "capture" | Saves something to the brain with correct frontmatter |
| `brain-project` | "start a new project" | Scaffolds a new project with context primer + project note |
| `brain-hygiene` | "tidy", "audit", "health-check" | Checks frontmatter completeness, orphans, broken links, stale drafts |

## Requirements

- The `brain` MCP server must be connected in Claude Code (`.mcp.json` configured)
- The brain container must be running (`docker compose up -d`)
