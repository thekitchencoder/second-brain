# Brain Container — Global Instructions

**CRITICAL: Never fabricate vault content.** Always use MCP tools to read real data.

- To find notes: call `brain_search` or `brain_query`
- To read a note: call `brain_read`
- To get today's date: it is injected into your context — use it exactly
- If a tool call returns no results, say so — do not invent content

You are connected to the brain MCP server. All brain tools are available and pre-approved. Use them.

## Vault structure

Notes are organised into five top-level folders:

| Folder | Contents |
|---|---|
| `Atlas/` | Evergreen knowledge, MOCs |
| `Efforts/` | Active ongoing work — one note per effort at `Efforts/<slug>.md`, subfolder for related notes |
| `Cards/` | Atomic ideas and concepts |
| `Calendar/` | Daily notes and time-anchored entries |
| `Sources/` | Reference material, articles, papers |

## Available skills

Skills are pre-loaded in `~/.claude/skills/`. Invoke them for vault operations — they encode correct conventions and prevent common mistakes.

| Say this | Skill invoked |
|---|---|
| "Start my day" / "daily note" | `brain-daily` |
| "I've had an idea" / capture something | `brain-capture` |
| "Create a new effort for X" | `brain-create-effort` |
| "Move X into effort Y" / consolidate notes | `brain-reorganise` |
| "What's simmering?" / surface parked work | `brain-surface` |
| "Where does effort X stand?" | `brain-effort` |
| "Process my inbox" / triage raw notes | `brain-triage` |
| "Rename this note" | `brain-rename` |
| "Find connections for this note" | `brain-connect` |
| "Pull ideas out of this note" | `brain-extract` |
