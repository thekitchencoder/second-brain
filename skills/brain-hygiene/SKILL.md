---
name: brain-hygiene
description: Use when asked to tidy, audit, or health-check the second-brain — checks frontmatter completeness, orphaned notes, broken wikilinks, and stale drafts.
---

# Brain Hygiene

Systematic audit of the second-brain. Four checks in order. Fix what is unambiguous; flag everything else.

## Check 1: Frontmatter Completeness

Use Glob to find all `.md` files excluding the `templates/` directory. Read each file. Flag any missing one or more of these required fields:

```
type, title, status, created, tags
```

**Fix:** if `created` is missing and the file has a filesystem mtime, use that date. For all other missing fields, propose a value based on the content and ask before writing.

**Do not** batch-fix without reading the content first.

## Check 2: Orphaned Notes

**Outbound orphans:** Use Grep to find `.md` files containing no `[[wikilinks]]`. These notes link to nothing.

**Inbound orphans:** Build a list of all filenames (without extension). Grep for `[[filename]]` patterns across all files. Notes with no inbound links are unreferenced.

Report both sets with title and path. Do not delete.

## Check 3: Broken Wikilink Targets

1. Build a filename index: collect all `.md` filenames (without extension) via Glob
2. Grep all files for `[[...]]` patterns
3. For each target, check if it exists in the index
4. Flag any target not found — do not create stub documents

## Check 4: Stale Drafts

Run `brain_query(status=draft)`. Report each result with its title and `created` date.

Present to the user for a decision on each: promote to `current`, move to `archived`, or delete.

**Do not auto-promote.** Drafts are promoted by the human.

---

## Fix vs Flag

| Issue | Action |
|-------|--------|
| Missing `created` (mtime available) | Fix |
| Missing `type`, `title`, `status`, `tags` | Propose + ask |
| Outbound orphan (no links out) | Flag |
| Inbound orphan (nothing links to it) | Flag |
| Broken wikilink target | Flag — do not create stub |
| Stale draft | Flag — do not auto-promote |
| Empty file | Flag — do not delete without confirmation |

## Rules

- Read the file before proposing any fix.
- Never delete anything without explicit user confirmation.
- Never create stub documents for missing wikilink targets.
- Never auto-promote `status: draft` notes.
