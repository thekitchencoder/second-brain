---
name: brain-save
description: Use when the user says "remember", "save", "capture", "note down", or asks Claude to record something for future sessions.
---

# Brain Save

Save something to the second-brain with correct frontmatter and placement.

## Path Notes

The vault lives inside a Docker container. Do NOT use Glob or filesystem tools to inspect vault paths — they will search the wrong directory. Use MCP tools only. When MCP tools return absolute paths like `/brain/Cards/foo.md`, pass them directly back to other MCP tools unchanged.

## Steps

1. **Call `brain_search(query=<topic>)` NOW.** Do not proceed until you have results. If a match is found, call `brain_read(filepath)` to get the full content, then offer to update it rather than create a duplicate.

2. **Call `brain_query(type="effort")` NOW** to see existing effort areas and infer where similar content belongs. Suggest a location based on the results. Valid top-level folders: `Atlas/`, `Efforts/`, `Cards/`, `Calendar/`, `Sources/`.

3. Agree the location with the user if ambiguous.

4. **Call `brain_templates()` NOW** to see what templates are available. If no templates are returned, ask the user to run `brain-init` to set up the vault, then stop. Otherwise call `brain_create(template=<template>, title=<title>, directory=<directory>)` — pass the target subdirectory so the file is created in the right place, not the brain root. If unsure which template fits, ask the user. **Note the returned filepath exactly.**

5. **Call `brain_edit(op=update_frontmatter, filepath=<filepath>, frontmatter={...})` NOW** to set any frontmatter fields that differ from the template defaults:

```yaml
type:     # infer from content — only set if different from template
title:    # human-readable, descriptive
status:   # draft | current | archived (only set if different from template default)
created:  # today YYYY-MM-DD (only set if not already set by template)
tags:     # array, lowercase, hyphenated — at least one tag
```

Only set fields you need to change. Do NOT overwrite the full frontmatter.

6. **Call `brain_edit(op=replace_section, ...)` NOW** to write the body content into the appropriate section. Use the heading that matches the template:

| Template | Main section heading |
|---|---|
| `discovery` | `Idea` |
| `effort` | `Goal` |
| `context-primer` | `Background` |
| `spec` | `Overview` |
| `meeting` | `Notes` |
| `daily` | `Notes` |
| any other | `Notes` |

Example: `brain_edit(op=replace_section, filepath=<filepath>, heading="Idea", body="<content to save>")`

Write exactly what was asked to be saved — nothing more. Add wikilinks to related notes found in step 1 using `brain_edit(op=insert_wikilink, ...)`.

**Never call `brain_write` on a file just created by `brain_create`.**

## Rules

- **No invented fields.** Only the five fields listed above unless the user explicitly requests more.
- **No elaboration.** Write what was asked, stop there.
- **No folder invention.** Infer location from existing brain structure — do not create new top-level folders.
- **Check first.** Always search before creating. A duplicate is worse than an update.
- **`brain_edit` not `brain_write`** after `brain_create` — preserves template-generated frontmatter.
