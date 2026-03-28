---
name: brain-daily
description: Use when the user wants to start their day, open today's daily note, or do a morning review. Triggers on "daily note", "start my day", "morning review", "what's on today", or at the start of a session with no specific topic.
---

# Brain Daily

Create or open today's daily note. Surface yesterday's open items and the current inbox count.

## Path Translation

MCP paths: `/brain/X` → `X` (strip `/brain` prefix)

## Flow

### 1. Check for today's note

Today's date: use the current date in `YYYY-MM-DD` format.

Glob for `Calendar/*YYYY-MM-DD*` to see if today's note already exists.

- **Exists** → Read it, surface its content, skip to step 3
- **Missing** → `brain_create(daily, "", Calendar/)` then `brain_write` with the template below

### 2. Seed today's note

Pull in context before the user starts writing:

**Yesterday's note** — Glob for yesterday's date in `Calendar/`. If found, Grep for any lines that look like unresolved items (lines starting with `- [ ]`, `TODO`, `open:`, `follow up`). List them under `## Carried forward`.

**Inbox count** — Grep for `status: raw` across the vault. Report count only: "3 raw notes in inbox."

**Active efforts** — Grep for `status: current` in `Efforts/*/\_index.md`. List effort titles.

Write all of this into today's note via `brain_write`.

### Daily note structure

```markdown
---
type: daily
title: YYYY-MM-DD
status: current
created: YYYY-MM-DD
tags: [daily]
---

## Carried forward
<!-- unresolved items from yesterday, if any -->

## Today

## Notes

## Inbox
<!-- N raw notes pending triage -->
```

### 3. Surface and hand off

Show the user today's note content and say: "Today's note is at `Calendar/YYYY-MM-DD.md`. Ready when you are."

## Rules

- **Never create a duplicate.** Check with Glob before creating.
- **Carried forward items are read-only suggestions.** Don't auto-move or delete them from yesterday's note.
- **Keep the seeded content minimal.** The note is a workspace, not a report.
