---
name: brain-effort
description: Use when the user wants a status overview of an effort, asks "where does X stand", "what's in the X effort", or wants to see all notes related to an ongoing area of work.
---

# Brain Effort

Surface all notes belonging to an effort, grouped by status. Identify gaps and orphans.

## Path Translation

MCP paths: `/brain/X` → `X` (strip `/brain` prefix)

## Flow

### 1. Resolve the effort

Accept: effort name, slug, or directory path.

- Glob for `Efforts/<slug>.md`
- If ambiguous, run `brain_search(effort name)` and confirm with user

Read `Efforts/<slug>.md`.

### 2. Collect all related notes (four passes, run in parallel)

**a. Directory scan** — Glob `Efforts/<slug>/**/*.md` — all notes physically in the effort folder

**b. Semantic search** — `brain_search(effort name)` — notes elsewhere that discuss this effort

**c. Tag search** — `brain_query(tag=<effort-slug>)` — notes explicitly tagged to this effort

**d. Backlinks** — `brain_backlinks(Efforts/<slug>.md)` — notes that wikilink to the effort note

Deduplicate across all four passes.

### 3. Group by status

```
## Current (established)
  - Efforts/jobs-guarantee/context-primer.md
    "Background and goals for the Jobs Guarantee effort"

## Draft (in progress)
  - Efforts/jobs-guarantee/automation-research.md

## Raw (inbox — needs triage)
  - Efforts/jobs-guarantee/automation-idea.md
  - Cards/ubi-comparison.md

## Archived
  - Efforts/jobs-guarantee/old-scope.md
```

### 4. Identify gaps and orphans

**Orphans** — notes found in steps 2–3 that are not wikilinked from `Efforts/<slug>.md`:
```
Not linked from effort note:
  Cards/ubi-comparison.md — tagged jobs-guarantee but not linked from effort
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

- **Report only — don't modify without asking.**
- **Missing stubs are not errors** — they're future work, just flag them.
- **Surface the full effort note** — the user needs to see what's there before deciding what to change.
