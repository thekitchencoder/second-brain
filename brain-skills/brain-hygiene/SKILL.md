---
name: brain-hygiene
description: Use when asked to tidy, audit, or health-check the second-brain — checks frontmatter completeness, orphaned notes, broken wikilinks, and stale drafts. Can fix broken wikilinks and restructure files.
---

# Brain Hygiene

Systematic audit of the second-brain. Five checks in order. Fix what is unambiguous; flag everything else.

This skill runs in the vault root with full filesystem access (Glob, Grep, Read, Edit). Use MCP tools for semantic operations, filesystem tools for structural scans and repairs.

## Check 1: Frontmatter Completeness

Use `brain_query` (or `brain_search` broadly) to enumerate notes, then `Read` each file to inspect its frontmatter. For batch inspection, Read is faster than `brain_read` since there is no MCP round-trip.

**Required universal fields (all types):**
```
type, title, status, tags
```
Plus a date field: `created` for all types except `discovery`, which uses `captured` instead.

**Valid types:** `effort`, `discovery`, `context-primer`, `spec`, `adr`, `source`, `meeting`, `daily`

**Deprecated types — fix on sight:**
- `type: project` → migrate to `type: effort`
- `type: moc` → migrate to `type: effort`

**Deprecated fields — remove on sight:**
`project:` (as a field; use `^project:\s` as the regex to avoid matching keys like `project-id:`), `scope:`, `technical-level:`, `phase:`, `stack:`, `repo:`, `agents:`, `priority:`, `complexity:`, `delegate:`, `assignee:`

Exceptions for `adr` notes: `id:` and `date:` (the decision date, distinct from `created:`) are both valid.

**Fixing deprecated types** (after confirming with user):
- `brain_edit(op=update_frontmatter, filepath=..., frontmatter={"type": "effort"})`

**Fixing deprecated fields** — `update_frontmatter` cannot remove keys; use find_replace instead:
- `brain_edit(op=find_replace, filepath=..., find="^scope:.*\n", replace="", regex=true)`
- Apply the same pattern for each deprecated scalar field name
- **Exception for list-valued fields** (`stack:`, `agents:`): the key line plus its indented items must be removed manually — a single-line regex will only strip the key and leave orphaned `  - ""` lines. Read the note, identify the full block, and use a multiline `find_replace` to remove it.

**Fixing missing `created`:** use `update_frontmatter` with the mtime date.

**`captured:` on discovery notes:** this is the canonical date field for `type: discovery` (not `created:`). Older notes may have a datetime value (`2024-03-01T15:04:05`) rather than date-only — that format difference is harmless, do not migrate unless the user asks.

**Do not** batch-fix without reading the content first.

## Check 2: Orphaned Notes

**Outbound orphans:** Read each file and check for absence of `[[wikilinks]]`. These notes link to nothing.

**Inbound orphans:** For each note, call `brain_backlinks(filepath)`. Notes where backlinks returns empty are unreferenced. No need to build a manual filename index.

Report both sets with title and path. Do not delete.

## Check 3: Broken Wikilink Targets

1. Build a filename index: collect all `.md` filenames (without extension) via `Glob(pattern="**/*.md")`
2. `Grep(pattern="\\[\\[([^\\]|]+)", glob="**/*.md")` to extract all wikilink targets
3. For each target, check if it exists in the index
4. Flag any target not found

### Wikilink Repair

After flagging broken targets, offer to **fix** them:

1. For each broken `[[target]]`, fuzzy-match against the filename index (case-insensitive, ignore hyphens vs spaces)
2. If a single close match is found, propose: `[[broken-target]]` → `[[correct-target]]`
3. If multiple candidates, show them and ask the user to pick
4. Apply fixes with `brain_edit(op=find_replace, filepath=..., find="[[broken-target]]", replace="[[correct-target]]")`
5. If no match is found, flag only — do not create stub documents

Report all repairs: "Fixed 3 broken wikilinks across 5 files."

## Check 4: Stale Drafts

Run `brain_query(status=draft)`. Report each result with its title and `created` date.

Present to the user for a decision on each: promote to `current`, move to `archived`, or delete.

**Do not auto-promote.** Drafts are promoted by the human.

## Check 5: Trash

`Glob(pattern=".trash/**/*.md")`. If the result is empty, skip this check.

For each file found:
- Derive the original path: `Read` the `.origin` sidecar (same stem, `.origin` extension) if present; otherwise strip the `.trash/` prefix from the path.
- Show: original path, trashed date (file mtime), current trash path.
- Ask the user: **[restore]** | **[permanently delete]** | **[skip]**

**Restore:** `brain_restore(trash_path)`

**Permanently delete:** remove the `.md` file and its `.origin` sidecar (if present) via `rm`. This is irreversible — confirm per file.

Never auto-empty the trash.

---

## Fix vs Flag

| Issue | Action |
|-------|--------|
| Missing `created` (mtime available) | Fix — `update_frontmatter` |
| Missing `type`, `title`, `status`, `tags` | Propose + ask — `update_frontmatter` |
| `type: project` or `type: moc` | Propose migration + ask — `update_frontmatter` |
| Deprecated field present | Propose removal + ask — `find_replace` with regex |
| Outbound orphan (no links out) | Flag |
| Inbound orphan (`brain_backlinks` returns empty) | Flag |
| Broken wikilink target | Fix — fuzzy-match and `find_replace` (confirm first) |
| Stale draft | Flag — do not auto-promote |
| Empty file | Flag — do not delete without confirmation |

## Rules

- Read the file before proposing any fix.
- Never delete anything without explicit user confirmation.
- Never create stub documents for missing wikilink targets.
- Never auto-promote `status: draft` notes.
- Use filesystem tools (Glob, Grep, Read) for structural scans — they are faster than MCP for batch operations.
- Use MCP tools (brain_edit, brain_query, brain_backlinks) for semantic operations and edits.
