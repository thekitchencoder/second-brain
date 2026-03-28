---
name: brain-triage
description: Use when the user wants to work through their discovery inbox, process raw notes, or clear out unreviewed captures. Triggers on "triage", "process my inbox", "what's in my inbox", "clear raw notes".
---

# Brain Triage

Work through `status: raw` discovery notes one at a time. Promote, archive, or defer each one.

## Path Translation

`brain_search`, `brain_create`, and `brain_related` return absolute paths like `/brain/Cards/foo.md`. `brain_query` and `brain_backlinks` return vault-relative paths like `Cards/foo.md`.

- **Filesystem tools** (Glob, Grep, Read): strip `/brain/` prefix → `Cards/foo.md`
- **MCP tools** (brain_read, brain_edit, etc.): pass the path as returned — both formats accepted

## Flow

### 1. Find the inbox

```bash
Grep for `status: raw` in frontmatter across the vault
```

Report: "You have N raw notes. Working through them oldest first."

Sort oldest first — read frontmatter for each and sort by `captured:` (discovery notes) or `created:` (all other types) ascending.

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
- `brain_edit(op=update_frontmatter, filepath=..., frontmatter={"status": "draft"})`
- Check if the note is in the right folder (infer from type/tags):
  - `type: discovery` with an effort tag → offer to move to `Efforts/<slug>/`
  - Generic idea → `Cards/` is fine
- Run `brain_related(filepath)` and for each top match: `brain_edit(op=insert_wikilink, filepath=<note being triaged>, target=<title>, context_heading="Related Notes")`
- If the note has a non-empty `effort:` field value: `brain_edit(op=insert_wikilink, filepath=Efforts/<slug>.md, target=<note title>, context_heading="Notes")`

**Archive:**
- `brain_edit(op=update_frontmatter, filepath=..., frontmatter={"status": "archived"})`

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
