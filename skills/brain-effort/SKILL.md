---
name: brain-effort
description: Use when the user wants a status overview of an effort, asks "where does X stand", "what's in the X effort", or wants to see all notes related to an ongoing area of work.
---

# Brain Effort

Surface all notes belonging to an effort, grouped by status. Identify gaps and orphans.

## MCP-Only Skill

This is a global skill — it uses MCP tools exclusively. Do NOT use Glob, Grep, Read, Edit, or other filesystem tools. The vault lives inside a Docker container and filesystem tools will search the wrong directory.

## Flow

### 1. Resolve the effort

Accept: effort name, slug, or directory path.

- `brain_search(query="<slug>")` to find the effort note
- If ambiguous, confirm with user

Read the effort note with `brain_read(filepath)`.

### 2. Collect all related notes (three passes, run in parallel)

**a. Semantic search** — `brain_search(effort name)` — notes elsewhere that discuss this effort

**b. Tag search** — `brain_query(tag=<effort-slug>)` — notes explicitly tagged to this effort. This also catches notes physically in the effort folder since they are typically tagged.

**c. Backlinks** — `brain_backlinks(Efforts/<slug>.md)` — notes that wikilink to the effort note

Deduplicate across all three passes.

**Note:** Notes physically in `Efforts/<slug>/` but without the tag may be missed. brain-hygiene flags these as orphans during vault audits.

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
