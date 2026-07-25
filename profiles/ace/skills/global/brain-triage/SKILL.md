---
name: brain-triage
description: Use when the user wants to triage their discovery notes, review unreviewed captures, or work through notes awaiting a decision. Triggers on "triage", "what's waiting for review", "review my notes", "what needs triaging".
---

# Brain Triage

Review notes with `status: raw` or no status set — one at a time. Promote, archive, or defer each one.

## MCP-Only Skill

Uses MCP tools only. The brain lives inside a Docker container — filesystem tools (Glob, Grep, Read, Edit) will search the host filesystem, not the brain.

## Flow

### 1. Find and sort notes awaiting review (subagent)

Dispatch a subagent with this task:

```
Run both queries in parallel:
- brain_query(status="raw")   — notes explicitly marked for review
- brain_query(status="unset") — notes with no status field at all

Merge and deduplicate. For each result, call brain_read(filepath) to get:
- title
- created (or captured for type: discovery)
- type
- A one-sentence excerpt from the note body

Sort by date ascending (oldest first).

Return: [{ "path": "...", "title": "...", "date": "YYYY-MM-DD", "type": "...", "excerpt": "..." }, ...]
```

Report to the user: "You have N notes awaiting review. Working through them oldest first."

### 2. Review one note at a time

For each note:

1. Read the full note with `brain_read(filepath)`
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

When the queue is empty or user stops:

```
Triage complete: 3 promoted, 2 archived, 4 deferred, 2 remaining
```

## Rules

- **One note at a time.** Never show multiple notes simultaneously.
- **Never delete.** Archive is the floor — `status: archived` only.
- **Don't promote without asking.** Always confirm the destination folder.
- **Defer is valid.** Not every note needs a decision today.
