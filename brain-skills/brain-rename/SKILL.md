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

Grep across the vault for every way this note might be linked.

Common variants to search for:
```
[[Old Title]]
[[old-title]]
[[Old Title|display text]]
[[old-title|display text]]
```

Derive search terms from both the current filename (strip `.md`, un-hyphenate) and the current `title:` frontmatter field.

### 4. Update wikilinks

For each file containing a match:
- Use `Edit` to replace each variant with the new title/slug
- Preserve display text: `[[Old Title|display text]]` → `[[New Title|display text]]`

Report files updated as you go.

### 5. Rename the file

```bash
mv <old-path> <new-path>
```

### 6. Update the note's own frontmatter

Patch the `title:` field in the renamed file to match the new title.

### 7. Report

```
Renamed: Cards/old-title.md → Cards/new-title.md
Updated wikilinks in 4 files:
  Projects/jobs-guarantee/_index.md
  Cards/related-idea.md
  ...
```

## Rules

- **Confirm before renaming.** Always show old path + new path and wait for approval.
- **Never silently drop display text.** `[[Old|label]]` → `[[New|label]]`, not `[[New]]`.
- **Check all variants.** Title case, slug form, with and without display text.
- **Update frontmatter title too.** The `title:` field should match the filename.
