---
name: brain-triage
description: Use when the user wants to work through their discovery inbox, process raw notes, or clear out unreviewed captures. Triggers on "triage", "process my inbox", "what's in my inbox", "clear raw notes".
---

# Brain Triage

Work through `status: raw` discovery notes one at a time. Promote, archive, or defer each one.

## Path Translation

MCP paths: `/brain/X` → `X` (strip `/brain` prefix)

## Flow

### 1. Find the inbox

```bash
Grep for `status: raw` in frontmatter across the vault
```

Report: "You have N raw notes. Working through them oldest first."

Sort by `created` date ascending (oldest first) — use Grep `-l` to get paths, then read frontmatter.

### 2. Process one note at a time

For each note:

1. Read the full note
2. Summarise it in 1-2 sentences
3. Ask the user to choose:

```
[p] Promote → mark as draft, confirm or move to correct folder
[a] Archive → mark as archived
[d] Defer   → leave as raw, skip for now
[s] Stop    → end triage session
```

### 3. Act on the decision

**Promote:**
- Update `status: raw` → `status: draft` via `Edit`
- Check if the note is in the right folder (infer from type/tags):
  - `type: discovery` with a project tag → offer to move to `Projects/<slug>/`
  - Generic idea → `Cards/` is fine
- Run `brain_related(filepath)` and add top `[[wikilinks]]` if none exist
- Find nearest `_index.md` and add a reference line

**Archive:**
- Update `status: raw` → `status: archived` via `Edit`

**Defer:**
- No changes — move to next note

### 4. Summary

When inbox is empty or user stops:

```
Triage complete: 3 promoted, 2 archived, 4 deferred, 2 remaining
```

## Rules

- **One note at a time.** Never show multiple notes simultaneously.
- **Never delete.** Archive is the floor — `status: archived` only.
- **Don't promote without asking.** Always confirm the destination folder.
- **Defer is valid.** Not every note needs a decision today.
