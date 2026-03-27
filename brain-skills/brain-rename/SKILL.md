---
name: brain-rename
description: Use when the user wants to rename a note or file in the vault. Triggers on "rename", "move this note", "change the title of". Updates all wikilinks across the vault automatically.
---

# Brain Rename

Rename a note and update every `[[wikilink]]` pointing to it across the vault.

## Path Translation

MCP paths: `/brain/X` → `X` (strip `/brain` prefix)

## Flow

### 1. Resolve the source note

Accept: relative path, MCP path, or title → `brain_search(title)` to find it.

Read the note. Confirm with the user: "Renaming `Cards/old-title.md` — is that the right note?"

### 2. Determine the new filename

- New filename: lowercase, hyphenated, `.md` extension
- New title: human-readable, as provided by user
- Confirm: "New filename will be `Cards/new-title.md` and title `New Title` — proceed?"

### 3. Find all wikilink variants

Run both in parallel:

**a. `brain_backlinks(old-path)`** — finds all notes linking by slug form: `[[old-title]]`, `[[old-title|display]]`, `[[Cards/old-title]]`

**b. Grep for title-case form** — `brain_backlinks` does not match by title, so grep separately for `[[Old Title]]` and `[[Old Title|` variants derived from the current `title:` frontmatter field

Merge and deduplicate.

### 4. Update wikilinks

For each file containing a match, use `brain_edit(op=find_replace)` to replace each variant (do **not** use `regex=true` — square brackets are regex metacharacters):
- `brain_edit(op=find_replace, filepath=..., find="[[old-title]]", replace="[[new-title]]")`
- `brain_edit(op=find_replace, filepath=..., find="[[Old Title]]", replace="[[New Title]]")`
- Preserve display text: `find="[[Old Title|"` → `replace="[[New Title|"` (prefix match — leaves the alias label intact)

Report files updated as you go.

### 5. Rename the file

Choose the approach based on your session context:

**Brain-native session** (Claude Code opened directly in the vault root — direct filesystem access available):
```bash
mv <old-path> <new-path>
```
Use the vault filesystem path (strip the `/brain` prefix if the path came from an MCP tool).

**MCP-only session** (external project with brain connected as MCP — no direct filesystem access):
```
brain_read(old_path)            → capture content
brain_write(new_path, content)  → write to new location
brain_trash(old_path)           → remove old file and clean from index
```

### 6. Update the note's own frontmatter

`brain_edit(op=update_frontmatter, filepath=<new-path>, frontmatter={"title": "<New Title>"})`

### 7. Report

```
Renamed: Cards/old-title.md → Cards/new-title.md
Updated wikilinks in 4 files:
  Efforts/jobs-guarantee.md
  Cards/related-idea.md
  ...
```

## Rules

- **Confirm before renaming.** Always show old path + new path and wait for approval.
- **Never silently drop display text.** `[[Old|label]]` → `[[New|label]]`, not `[[New]]`.
- **Check all variants.** Title case, slug form, with and without display text.
- **Update frontmatter title too.** The `title:` field should match the filename.
