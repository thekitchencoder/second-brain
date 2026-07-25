---
name: brain-daily
description: Use when the user wants to start their day, open today's daily note, or do a morning review. Triggers on "daily note", "start my day", "morning review", "what's on today", or at the start of a session with no specific topic.
---

# Brain Daily

Create or open today's daily note. Surface open items from the most recent previous daily note and wikilinks to notes awaiting review.

## Path Translation

`brain_search`, `brain_create`, and `brain_related` return absolute paths like `/brain/Cards/foo.md`. `brain_query` and `brain_backlinks` return brain-relative paths like `Cards/foo.md`.

- **Filesystem tools** (Glob, Grep, Read): strip `/brain/` prefix → `Cards/foo.md`
- **MCP tools** (brain_read, brain_edit, etc.): pass the path as returned — both formats accepted

## Flow

### 1. Check for today's note

Today's date: use the current date in `YYYY-MM-DD` format.

Run `Glob(pattern="Calendar/*YYYY-MM-DD*")` (substitute the actual date).

- **Exists** → Read it, surface its content, skip to step 3
- **Missing** → Run `brain_create(template="daily", title="YYYY-MM-DD", directory="Calendar/")` (substitute today's actual date as the title). Note the returned filepath. Populate using `brain_edit`, not `brain_write` — then go to step 2.

### 2. Seed today's note

Dispatch a subagent with this task:

```
Gather seed data for today's daily note. Run all three lookups, return structured results.

a. Most recent daily note's open items
   Today's date: <today-date>
   Glob(pattern="Calendar/*.md") to list all daily notes.
   Sort by filename descending and find the most recent one BEFORE today.
   (This handles weekends and gaps — don't assume yesterday has a note.)
   If a file is found, run:
   Grep(pattern="- \[ \]|TODO|open:|follow up", path=<that filepath>)
   Return the matching lines and the date of that note, or an empty list if none.

b. Notes awaiting review
   Run in parallel: brain_query(status="raw") and brain_query(status="unset")
   Merge and deduplicate. Exclude daily notes (Calendar/*.md).
   Extract the filename stem (without extension or directory) from each path — this is the wikilink target.
   Return a list of wikilink strings: ["[[filename-stem]]", ...]

c. Active efforts
   Run brain_query(status="active"). Filter to type: effort.
   Extract the filename stem from each path.
   Return a list of filename stems.

Return:
{
  "carried_forward": ["- [ ] item one", ...],       // or empty list
  "carried_from": "YYYY-MM-DD",                      // date of the source note, or null
  "inbox_wikilinks": ["[[filename-stem]]", ...],     // or empty list
  "active_efforts":  ["effort-slug", ...]            // or empty list
}
```

Use the subagent's result to populate sections:

```
brain_edit(op=replace_section, filepath=<filepath>, heading="Carried forward",
  body="<carried_forward lines joined with \n, or '<!-- nothing carried forward -->'>"
  If carried_from is not yesterday, prepend "<!-- from YYYY-MM-DD -->" so the source is clear.)

brain_edit(op=replace_section, filepath=<filepath>, heading="Inbox",
  body="<inbox_wikilinks joined with \n, or '<!-- nothing awaiting review -->'>")
```

If `active_efforts` is non-empty:
```
brain_edit(op=replace_section, filepath=<filepath>, heading="Today",
  body="**Active efforts:** [[slug-1]], [[slug-2]], ...")
```

### 3. Surface and hand off

Show the user today's note content and say: "Today's note is at `Calendar/YYYY-MM-DD.md`. Ready when you are."

## Rules

- Check with Glob before creating — skip `brain_create` if today's note already exists.
- Always use `brain_create` to create the note — never write template content manually. The template contains Go date format patterns (e.g. `2006-01-02`) that `zk` substitutes with the real date. Writing them literally produces wrong output.
- Use `brain_edit` after `brain_create`, not `brain_write` — preserves template frontmatter.
- Carried forward items are read-only suggestions. Don't auto-move or delete them from the source note.
- Keep the seeded content minimal. The note is a workspace, not a report.
- **Wikilinks must use filename stems, not titles.** Extract the filename without extension from the path returned by `brain_query` (e.g. `Efforts/pain-tracker.md` → `[[pain-tracker]]`). Title-based links like `[[Pain Tracker]]` won't resolve.
