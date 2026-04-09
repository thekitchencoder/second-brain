---
name: brain-effort
description: Use when the user wants a status overview of an effort, asks "where does X stand", "what's in the X effort", or wants to see all notes related to an ongoing area of work.
---

# Brain Effort

Surface all notes belonging to an effort, grouped by status. Identify gaps and orphans.

## MCP-Only Skill

Uses MCP tools only. The vault lives inside a Docker container — filesystem tools (Glob, Grep, Read, Edit) will search the host filesystem, not the vault.

## Flow

### 1. Resolve the effort

Accept: effort name, slug, or directory path.

- `brain_search(query="<slug>")` to find the effort note
- If ambiguous, confirm with user

Read the effort note with `brain_read(filepath)`.

### 2. Collect and group related notes (subagent)

Dispatch a subagent with this task:

```
Collect all notes related to the effort at <filepath> (slug: <slug>).

Run these three searches in parallel:
- brain_search(query="<effort name>") — semantic matches
- brain_query(tag="<slug>") — notes tagged to this effort
- brain_backlinks(filepath="Efforts/<slug>.md") — notes wikilinked to the effort note

Deduplicate across all three. For each unique result, call brain_read(filepath) to get its
type, status, and title.

Return a grouped structure:
{
  "current":  [{ "path": "...", "title": "...", "excerpt": "..." }, ...],
  "draft":    [...],
  "raw":      [...],
  "archived": [...],
  "unknown":  [...]   // status absent or unrecognised
}

Also return two additional lists:
- "orphans": paths found above that are NOT wikilinked from Efforts/<slug>.md
  (check by reading the effort note and scanning for [[wikilinks]])
- "stubs": [[wikilinks]] in Efforts/<slug>.md that have no matching note in the vault
  (check each wikilink target against the results and any brain_search for that title)
```

### 3. Present grouped overview

Use the subagent's returned structure:

```
## Current (established)
  - Efforts/co-dependent-confabulation/context-primer.md
    "Background and goals for the Co-dependent Confabulation effort"

## Draft (in progress)
  - Efforts/co-dependent-confabulation/automation-research.md

## Raw (needs triage)
  - Efforts/co-dependent-confabulation/automation-idea.md
  - Cards/ubi-comparison.md

## Archived
  - Efforts/co-dependent-confabulation/old-scope.md
```

### 4. Identify gaps and orphans

**Orphans** — notes found in steps 2–3 that are not wikilinked from `Efforts/<slug>.md`:
```
Not linked from effort note:
  Cards/ubi-comparison.md — tagged co-dependent-confabulation but not linked from effort
```

**Missing links** — wikilinks in `Efforts/<slug>.md` that point to notes that don't exist yet (stubs):
```
Linked but missing:
  [[Policy Research]] — no note found
```

### 5. Offer actions

After the report, ask:
- "Want me to add wikilinks for the orphaned notes into `Efforts/<slug>.md`?" → if yes: `brain_edit(op=insert_wikilink, filepath=Efforts/<slug>.md, target=<note title>, context_heading="Notes")` for each orphan
- "Want to triage the raw notes now?" (hands off to `brain-triage` flow)

## Rules

- Report findings first; make changes only when asked.
- **Missing stubs are not errors** — they're future work, just flag them.
- **Surface the full effort note** — the user needs to see what's there before deciding what to change.
