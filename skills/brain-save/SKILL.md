---
name: brain-save
description: Use when the user says "remember", "save", "capture", "note down", or asks Claude to record something for future sessions.
---

# Brain Save

Save something to the second-brain with correct frontmatter and placement.

## Steps

1. Run `brain_search` on the topic to check if a note already exists — offer to update it rather than create a duplicate
2. Use Glob to scan the top-level folder structure of the brain and infer where similar content lives — suggest a location based on existing patterns
3. Agree the location with the user if ambiguous
4. Create the note via `brain_create(template, title)`
5. Write frontmatter with exactly these fields:

```yaml
type:     # infer from content — ask if unclear
title:    # human-readable, descriptive
status:   # draft | current | archived
created:  # today YYYY-MM-DD
tags:     # array, lowercase, hyphenated — at least one tag
```

6. Write the body: exactly what was asked to be saved, nothing more
7. Add wikilinks to related notes found in step 1

## Rules

- **No invented fields.** Only the five above unless the user explicitly requests more.
- **No elaboration.** Write what was asked, stop there.
- **No folder invention.** Infer location from existing brain structure — do not create new top-level folders.
- **Check first.** Always search before creating. A duplicate is worse than an update.
