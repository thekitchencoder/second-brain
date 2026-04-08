---
name: brain-daily
description: Use when the user wants to start their day, open today's daily note, or do a morning review. Triggers on "daily note", "start my day", "morning review", "what's on today", or at the start of a session with no specific topic.
---

# Brain Daily

Create or open today's daily note. Surface yesterday's open items and wikilinks to notes awaiting review.

## Path Translation

`brain_search`, `brain_create`, and `brain_related` return absolute paths like `/brain/Cards/foo.md`. `brain_query` and `brain_backlinks` return vault-relative paths like `Cards/foo.md`.

- **Filesystem tools** (Glob, Grep, Read): strip `/brain/` prefix → `Cards/foo.md`
- **MCP tools** (brain_read, brain_edit, etc.): pass the path as returned — both formats accepted

## Flow

### 1. Check for today's note

Today's date: use the current date in `YYYY-MM-DD` format.

Run `Glob(pattern="Calendar/*YYYY-MM-DD*")` (substitute the actual date).

- **Exists** → Read it, surface its content, skip to step 3
- **Missing** → Run `brain_create(template="daily", title="", directory="Calendar/")`. Note the returned filepath. Populate using `brain_edit`, not `brain_write` — then go to step 2.

### 2. Seed today's note

Dispatch a subagent with this task:

```
Gather seed data for today's daily note. Run all three lookups, return structured results.

a. Yesterday's open items
   Yesterday's date: <yesterday-date>
   Glob(pattern="Calendar/*<yesterday-date>*"). If a file is found, run:
   Grep(pattern="- \[ \]|TODO|open:|follow up", path=<yesterday filepath>)
   Return the matching lines as a list, or an empty list if none.

b. Notes awaiting review
   Run in parallel: brain_query(status="raw") and brain_query(status="unset")
   Merge and deduplicate. For each path, call brain_read(filepath) to get the title field.
   Fall back to the filename stem (without extension) if title is absent.
   Return a list of wikilink strings: ["[[Note Title One]]", "[[Note Title Two]]", ...]

c. Active efforts
   Run brain_query(status="active"). Filter to type: effort.
   Return a list of effort titles.

Return:
{
  "carried_forward": ["- [ ] item one", ...],   // or empty list
  "inbox_wikilinks": ["[[Title]]", ...],         // or empty list
  "active_efforts":  ["Jobs Guarantee", ...]     // or empty list
}
```

Use the subagent's result to populate sections:

```
brain_edit(op=replace_section, filepath=<filepath>, heading="Carried forward",
  body="<carried_forward lines joined with \n, or '<!-- nothing carried forward -->'>")

brain_edit(op=replace_section, filepath=<filepath>, heading="Inbox",
  body="<inbox_wikilinks joined with \n, or '<!-- nothing awaiting review -->'>")
```

If `active_efforts` is non-empty:
```
brain_edit(op=replace_section, filepath=<filepath>, heading="Today",
  body="**Active efforts:**\n<effort titles as bullet list>")
```

### 3. Surface and hand off

Show the user today's note content and say: "Today's note is at `Calendar/YYYY-MM-DD.md`. Ready when you are."

## Rules

- Check with Glob before creating — skip `brain_create` if today's note already exists.
- Use `brain_edit` after `brain_create`, not `brain_write` — preserves template frontmatter.
- Carried forward items are read-only suggestions. Don't auto-move or delete them from yesterday's note.
- Keep the seeded content minimal. The note is a workspace, not a report.
