# Second Brain — Vault Instructions

You are working directly in the vault root. You have both MCP tools and direct filesystem access.

## Filesystem + MCP

Use MCP tools for semantic operations (search, edit, create). Use filesystem tools (Glob, Grep, Read, Edit) for structural operations — they are faster for batch scans and pattern matching.

## Additional Vault Skills

These skills require direct filesystem access and are only available when Claude Code is opened in the vault root:

| Say this | Skill invoked |
|---|---|
| "Start my day" / "daily note" | `brain-daily` |
| "Pull ideas out of this note" | `brain-extract` |
| "Tidy" / "audit" / "health-check" | `brain-hygiene` |
| "Rename this note" | `brain-rename` |
| "Move X into effort Y" / consolidate notes | `brain-reorganise` |

These extend the global skills (brain-capture, brain-connect, brain-context, brain-create-effort, brain-effort, brain-project, brain-save, brain-setup, brain-surface, brain-triage) which are also available here.
