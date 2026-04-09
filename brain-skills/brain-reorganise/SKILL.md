---
name: brain-reorganise
description: Use when the user wants to move notes into an effort, consolidate scattered notes, migrate documents, or says "move X into effort Y", "consolidate these into X", "pull these docs into Y", "reorganise effort X".
---

# Brain Reorganise

Move or consolidate notes into an effort. Delegates all per-file moves to `brain-rename` to preserve wikilink integrity across the brain.

## Path Translation

`brain_search`, `brain_create`, and `brain_related` return absolute paths like `/brain/Cards/foo.md`. `brain_query` and `brain_backlinks` return brain-relative paths like `Cards/foo.md`.

- **Filesystem tools** (Glob, Grep, Read): strip `/brain/` prefix → `Cards/foo.md`
- **MCP tools** (brain_read, brain_edit, etc.): pass the path as returned — both formats accepted

## Why brain-rename is required for every move

write+delete silently breaks all `[[wikilinks]]` pointing to the moved file across the brain. Every file move goes through `brain-rename`, which finds and updates wikilinks automatically before renaming.

## Flow

### 1. Identify the notes to move

Accept any of:
- Explicit list from the user
- A directory to move in bulk: run `Glob(pattern="<source dir>/**/*.md")`
- A search: run `brain_search(query=<topic>)` and confirm which results to include

### 2. Identify the destination effort

Accept: effort name, slug, or path.

Run `Glob(pattern="Efforts/<slug>.md")` to confirm it exists. If not found, ask the user to confirm the slug or create the effort first using the `brain-create-effort` skill.

### 3. Confirm before touching anything

Show the user a clear plan:

```
Moving N notes → Efforts/<slug>/

  Cards/some-idea.md          → Efforts/<slug>/some-idea.md
  Efforts/other/research.md   → Efforts/<slug>/research.md
  ...

Wikilinks will be updated in all files that reference these notes.
Proceed?
```

Do not move anything until the user confirms.

### 4. Move each file using brain-rename

For each note, invoke the `brain-rename` skill with:
- Source path: `<current filepath>`
- Destination path: `Efforts/<slug>/<filename>.md`
- Title: unchanged (same title, new location)

`brain-rename` will:
- Find all `[[wikilink]]` variants pointing to the old path
- Update them in every file across the brain
- Rename/move the file itself
- Update the note's own `title:` frontmatter if changed

Report each move as it completes.

### 5. Wire moved notes into the effort

After all moves, add wikilinks from the effort note to each moved note:

```
For each moved note:
  brain_edit(op=insert_wikilink, filepath=Efforts/<slug>.md, target=<note title>, context_heading="Notes")
```

`insert_wikilink` is idempotent — safe to call even if the link already exists.

### 6. Report

```
Moved 4 notes to Efforts/<slug>/:
  Cards/some-idea.md → Efforts/<slug>/some-idea.md (wikilinks updated in 3 files)
  ...
Added 4 links to Efforts/<slug>.md under ## Notes.
```

## Rules

- Always use brain-rename for file moves — write+delete breaks wikilinks.
- Confirm the plan before moving anything. Show source → destination for every file.
- The destination effort must already exist. If it doesn't, use `brain-create-effort` first.
- Report each move. Don't batch silently — the user needs to know what changed.

## Baseline Failures This Skill Addresses

Without this skill, agents either:
- Use `brain_read` + `brain_write`(new path) + `brain_trash`(old path) — silently breaking all wikilinks
- Skip wikilink updates entirely
- Don't wire the moved notes into the effort note
- Ask too many clarifying questions instead of showing a plan and acting

## Common Mistakes

| Mistake | Fix |
|---|---|
| Moving with write+delete | Always invoke `brain-rename` per file |
| Moving without confirming | Show the full plan and wait for approval |
| Forgetting to wire into effort note | After all moves, call `insert_wikilink` for each |
| Creating the destination effort mid-flow | Use `brain-create-effort` before starting the move |
