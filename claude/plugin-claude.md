# Second Brain — Global Instructions

You are connected to a second-brain via MCP. All brain tools are available and pre-approved.

**CRITICAL: Never fabricate vault content.** Always use MCP tools to read real data. If a tool call returns no results, say so — do not invent content.

## MCP-Only — No Filesystem Access

The vault lives inside a Docker container. Do NOT use Glob, Grep, Read, Edit, or other filesystem tools — they will search the wrong directory. Use MCP tools exclusively:

- To find notes: `brain_search` or `brain_query`
- To read a note: `brain_read`
- To create a note: `brain_create` then `brain_edit` (never `brain_write` on a freshly created file)
- To modify a note: `brain_edit`
- To find related notes: `brain_related` or `brain_backlinks`

## Vault Structure

| Folder | Contents |
|---|---|
| `Atlas/` | Evergreen knowledge, MOCs |
| `Efforts/` | Active ongoing work — one note per effort at `Efforts/<slug>.md`, subfolder for related notes |
| `Cards/` | Atomic ideas and concepts |
| `Calendar/` | Daily notes and time-anchored entries |
| `Sources/` | Reference material, articles, papers |

## Available Skills

Skills are pre-loaded and encode correct conventions. Use them instead of manual tool sequences.

| Say this | Skill invoked |
|---|---|
| "I've had an idea" / capture something | `brain-capture` |
| "Find connections for this note" | `brain-connect` |
| Working on a named topic or project | `brain-context` |
| "Create a new effort for X" | `brain-create-effort` |
| "Where does effort X stand?" | `brain-effort` |
| "Start a new project for X" | `brain-project` |
| "Remember this" / "save this" | `brain-save` |
| "What's simmering?" / surface parked work | `brain-surface` |
| "Process my inbox" / triage raw notes | `brain-triage` |

## Frontmatter Conventions

All notes require: `type`, `title`, `status`, `tags`, and a date field (`created` or `captured` for discoveries).

Valid types: `effort`, `discovery`, `context-primer`, `spec`, `adr`, `source`, `meeting`, `daily`

Valid statuses: `raw`, `draft`, `current`, `established`, `archived`
