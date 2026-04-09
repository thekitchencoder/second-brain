---
name: brain-capture
description: Use when the user mentions a topic, idea, project, meeting, or anything they want to capture in their brain. Triggers on "I've had an idea", "I was thinking about", "we had a meeting", "I want to spec out", or any new thing to record.
---

# Brain Capture

Conversational idea capture with inline wiring after the user finishes editing.

## MCP-Only Skill

Uses MCP tools only. The brain lives inside a Docker container — filesystem tools (Glob, Grep, Read, Edit) will search the host filesystem, not the brain.

## Flow

### 0. Route check

Read the user's request carefully. If it matches any of these patterns, switch to the correct skill instead:

| User says | Action |
|---|---|
| "note for today", "daily note", "today's log", "start my day", "morning review", "what's on today", "daily log" | Switch to brain-daily instead. |

Only continue below if the request is clearly NOT a daily note.

### 1. Search first

Run `brain_search(query=<topic>)` before anything else.

- **Strong match** → read it, surface it, offer to update rather than duplicate
- **Weak matches** → note filepaths for the wiring step

### 2. Converse

Extract the idea through dialogue — one question at a time.

Infer note type from what the user says:

| What they say | Template |
|---|---|
| Vague idea / half-formed thought | `discovery` |
| "We had a meeting / talked to X" | `meeting` |
| "I want to build / spec out X" | `spec` |
| Ongoing area of focus | `effort` |

Only ask about type if genuinely ambiguous.

### 3. Create

Run `brain_create(template=<template>, title=<title>, directory=<directory>)`. Note the returned filepath exactly.

Infer directory from context:
- Known effort → `Efforts/<slug>/`
- Atomic idea or unclear → `Cards/`

Populate using `brain_edit`, not `brain_write` — `brain_write` clobbers template frontmatter.

**a. Update frontmatter fields that differ from template defaults:**
```
brain_edit(op=update_frontmatter, filepath=<filepath>, frontmatter={effort: "<slug or empty>", tags: [<tags>]})
```
Only set fields you need to change. The template already sets `type`, `status`, and `created` correctly — do not overwrite them.

**b. Write body content into the appropriate section for the template type:**

| Template | Call |
|---|---|
| `discovery` | `brain_edit(op=replace_section, filepath=<filepath>, heading="Idea", body="<captured content>")` |
| `meeting` | `brain_edit(op=replace_section, filepath=<filepath>, heading="Notes", body="<captured content>")` |
| `spec` | `brain_edit(op=replace_section, filepath=<filepath>, heading="Overview", body="<captured content>")` |
| `effort` | `brain_edit(op=replace_section, filepath=<filepath>, heading="Goal", body="<captured content>")` |

Tell the user: "Draft at `<filepath>` — let me know when you've finished editing."

### 4. Wait

Do not proceed until the user signals they are done editing.

### 5. Wire

After the user confirms done:

1. Run in parallel: `brain_search(query=<title>)` and `brain_related(filepath=<filepath>)`.
2. For each strong match: `brain_edit(op=insert_wikilink, filepath=<new note>, target=<match title>, context_heading="Related Notes")` — idempotent, safe to call without pre-checking
3. If the note has a non-empty `effort:` field value: verify the effort exists with `brain_search(query=<slug>)`, then `brain_edit(op=insert_wikilink, filepath=Efforts/<slug>.md, target=<note title>, context_heading="Notes")`
4. Report: "Linked to 3 notes, added reference to `Efforts/renewable-energy.md`"

## Rules

- **No folder invention.** Only: Atlas, Efforts, Cards, Calendar, Sources
- **Search before creating.** Duplicates are worse than updates.
- **Write only what was captured.** No elaboration, no invented content.
- **`status: raw` on discovery notes** — keep it as set by the template during capture.
- **One note per idea.**
- Use `brain_edit` after `brain_create`, not `brain_write` — preserves template frontmatter.

## Common Mistakes

| Mistake | Fix |
|---|---|
| Creating without searching first | Always run `brain_search` before `brain_create` |
| Calling `brain_write` after `brain_create` | Use `brain_edit(op=replace_section)` to populate content |
| Placing notes in the brain root | Always pass a `directory` to `brain_create` |
| Wiring before the user is done | Wait for explicit confirmation before step 5 |
| Wiring to a non-existent effort note | Use `brain_search(query="<slug>")` to verify the effort exists before patching |
| Routing daily notes through this skill | Check step 0 — daily notes go to brain-daily |
