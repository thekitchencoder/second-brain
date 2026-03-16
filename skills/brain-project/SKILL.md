---
name: brain-project
description: Use when the user says "start a new project", "set up a project", or asks to scaffold new work in the second-brain.
---

# Brain Project

Scaffold a new project in the second-brain with two seed documents.

## Steps

1. Ask for a project name if not provided. Derive a kebab-case slug (e.g. `my-project-name`).
2. Use Glob to scan the brain structure — find where existing projects live and what documents they contain. Follow the established pattern.
3. Run `brain_search` on the project topic to find any prior related work. For any relevant hit, call `brain_read(filepath)` to get the full content before drafting new notes.
4. Call `brain_templates` to see what templates are available. Then create two notes via `brain_create` using exact template names from that list:

### Note 1: Context Primer

Template: whichever template from `brain_templates` best matches a context/primer document (e.g. `default` if nothing more specific exists)

```yaml
type: context-primer
title: "<Project Name> — Context"
status: draft
created: <today YYYY-MM-DD>
tags: [<project-slug>, context]
```

Body: problem statement, goals, key decisions made so far, links to related prior work found in step 3.

### Note 2: Project / Effort Note

Template: whichever template from `brain_templates` best matches a project/effort document

```yaml
type: project
title: "<Project Name>"
status: draft
created: <today YYYY-MM-DD>
tags: [<project-slug>]
```

Body: current phase, active work items, wikilink to the context primer.

5. Add wikilinks between the two notes.
6. Report what was created and how to query the project later:
   ```
   brain_query(tag="<project-slug>")
   ```

## Rules

- **Two documents minimum, two maximum** unless the user asks for more.
- **Tag both** with the project slug so the full thread is queryable.
- **No invented content.** Populate from what the user has provided and what `brain_search` returns.
- **Follow existing patterns.** Do not invent a folder structure that doesn't match the brain.
