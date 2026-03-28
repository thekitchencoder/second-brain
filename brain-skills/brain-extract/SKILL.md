---
name: brain-extract
description: Use when the user wants to break a long note into atomic pieces, extract ideas from a source note into separate cards, or says "pull the ideas out of this note". Useful for processing meeting notes, articles, or long discoveries.
---

# Brain Extract

Extract atomic ideas from a long note into separate Cards (or other typed notes). Leaves the source note intact with wikilinks to the extracted notes.

## Path Translation

`brain_search`, `brain_create`, and `brain_related` return absolute paths like `/brain/Cards/foo.md`. `brain_query` and `brain_backlinks` return vault-relative paths like `Cards/foo.md`.

- **Filesystem tools** (Glob, Grep, Read): strip `/brain/` prefix → `Cards/foo.md`
- **MCP tools** (brain_read, brain_edit, etc.): pass the path as returned — both formats accepted

## Flow

### 1. Resolve the source note

Accept: relative path, MCP path, or title → `brain_search(title)` to find it.

Read the full note.

### 2. Identify extraction candidates

Scan the note for discrete, self-contained ideas. An idea is extractable if:

- It could stand alone without the surrounding context
- It has a clear subject that could be a note title
- It's a different concept from the other ideas in the note

Present candidates to the user as a numbered list:

```
I found 4 extractable ideas:

1. "The jobs guarantee acts as an automatic stabiliser" — could be Cards/jobs-guarantee-automatic-stabiliser.md
2. "Comparison with UBI on inflationary pressure" — could be Cards/jg-vs-ubi-inflation.md
3. "Hyman Minsky's original formulation" — could be Cards/minsky-employer-of-last-resort.md
4. "Implementation via local government" — could be Cards/jg-local-government-implementation.md

Which would you like to extract? (numbers, "all", or "none")
```

### 3. Extract selected ideas

For each selected idea:

1. **Call `brain_create(template="discovery", title=<title>, directory="Cards/")` NOW** — or infer a better template/folder from the content. Note the returned filepath.
2. **Do NOT call `brain_write`.** Populate the note using `brain_edit`:
   - `brain_edit(op=replace_section, filepath=<filepath>, heading="Idea", body="<extracted content, verbatim or lightly cleaned>")`
   - If you can infer an effort connection: `brain_edit(op=update_frontmatter, filepath=<filepath>, frontmatter={effort: "<slug>"})`
   - The discovery template already sets `status: raw` and `captured: <today>` — do not overwrite these.
3. Report: "Created `Cards/jobs-guarantee-automatic-stabiliser.md`"

### 4. Update the source note

After all extractions:

1. Read the source note again
2. Replace each extracted passage with a `[[wikilink]]` to the new note (or add a `## See also` section if the passage should remain)
3. Ask first: "Replace extracted sections with wikilinks, or keep the original text and just add links at the bottom?"

Use `Edit` to patch the source note.

### 5. Report

```
Extracted 3 notes from Cards/jobs-guarantee-long.md:
  → Cards/jobs-guarantee-automatic-stabiliser.md
  → Cards/jg-vs-ubi-inflation.md
  → Cards/minsky-employer-of-last-resort.md
Source note updated with wikilinks.
```

## Rules

- **Never delete from the source note without asking.** Default is to add wikilinks; replacing text requires explicit confirmation.
- **One idea per note.** Don't bundle two concepts into one extracted note.
- **Preserve the author's words.** Extract verbatim or lightly clean — don't rewrite.
- **`status: raw` on extracted notes** — they are captures, not finished notes.
- **Never call `brain_write` on a file just created by `brain_create`.** Always use `brain_edit(op=replace_section)` to populate content.
