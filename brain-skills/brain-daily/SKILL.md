---
name: brain-daily
description: Use when the user wants to start their day, open today's daily note, or do a morning review. Triggers on "daily note", "start my day", "morning review", "what's on today", or at the start of a session with no specific topic.
---

# Brain Daily

Create or open today's daily note. Surface yesterday's open items and the current inbox count.

## Path Translation

`brain_search`, `brain_create`, and `brain_related` return absolute paths like `/brain/Cards/foo.md`. `brain_query` and `brain_backlinks` return vault-relative paths like `Cards/foo.md`.

- **Filesystem tools** (Glob, Grep, Read): strip `/brain/` prefix → `Cards/foo.md`
- **MCP tools** (brain_read, brain_edit, etc.): pass the path as returned — both formats accepted

## Flow

### 1. Check for today's note

Today's date: use the current date in `YYYY-MM-DD` format.

**Call `Glob(pattern="Calendar/*YYYY-MM-DD*")` NOW** (substitute the actual date). Do not proceed until you have the result.

- **Exists** → Read it, surface its content, skip to step 3
- **Missing** → **Call `brain_create(template="daily", title="", directory="Calendar/")` NOW.** Note the returned filepath. Do NOT call `brain_write` on this file — go to step 2.

### 2. Seed today's note

Run all three lookups in parallel NOW — do not skip any:

**a. Yesterday's open items** — **Call `Glob(pattern="Calendar/*<yesterday-date>*")` NOW.** If found, **Call `Grep(pattern="- \\[ \\]|TODO|open:|follow up", path=<yesterday filepath>)` NOW.** Collect any matching lines.

**b. Inbox count** — **Call `Grep(pattern="^status: raw", glob="**/*.md")` NOW.** Count the matching files.

**c. Active efforts** — **Call `brain_query(status="active")` NOW.** Filter the results to `type: effort`. Collect effort titles.

Then populate sections using `brain_edit` — do NOT use `brain_write`:

```
brain_edit(op=replace_section, filepath=<filepath>, heading="Carried forward", body="<unresolved items from yesterday, or '<!-- nothing carried forward -->'>"  )
brain_edit(op=replace_section, filepath=<filepath>, heading="Inbox", body="<!-- <N> raw notes pending triage -->")
```

If there are active efforts, add them as a brief list under `## Today`:
```
brain_edit(op=replace_section, filepath=<filepath>, heading="Today", body="**Active efforts:**\n<effort list>")
```

### 3. Surface and hand off

Show the user today's note content and say: "Today's note is at `Calendar/YYYY-MM-DD.md`. Ready when you are."

## Rules

- **Never create a duplicate.** Check with Glob before creating.
- **Never call `brain_write` on a file just created by `brain_create`.** Always use `brain_edit(op=replace_section)` to populate sections.
- **Carried forward items are read-only suggestions.** Don't auto-move or delete them from yesterday's note.
- **Keep the seeded content minimal.** The note is a workspace, not a report.
