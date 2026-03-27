---
name: brain-project
description: Use when the user says "start a new project", "set up a project", or asks to scaffold new work in the second-brain.
---

# Brain Project

Scaffold a new effort in the second-brain with two seed documents.

## Steps

1. Ask for a project name if not provided. Derive a kebab-case slug (e.g. `my-project-name`).
2. Use Glob to scan `Efforts/` — check existing effort notes (`Efforts/*.md`) to understand the established pattern.
3. Run `brain_search` on the topic to find any prior related work. For any relevant hit, call `brain_read(filepath)` to get the full content before drafting new notes.
4. Call `brain_templates` to see what templates are available. Then create two notes via `brain_create(template, title, directory)`:

### Note 1: Effort Note

Template: `effort`

File location: `Efforts/` (the file itself is `Efforts/<slug>.md` — pass `Efforts/` as the directory, not a subfolder)

```yaml
type: effort
title: "<Project Name>"
status: active
parents: []
created: <today YYYY-MM-DD>
tags: [<project-slug>]
```

Body: one-line goal, active work items, wikilink to the context primer.

Ask whether this effort has a linked dev repo on this machine. If yes, add a `dev:` map:
```yaml
dev:
  <hostname>: <absolute-path-to-repo>
```

### Note 2: Context Primer

Template: `context-primer`

File location: `Efforts/<slug>/` subfolder

```yaml
type: context-primer
title: "<Project Name> — Context"
status: current
created: <today YYYY-MM-DD>
tags: [<project-slug>, context]
```

Body: problem statement, goals, key decisions made so far, links to related prior work found in step 3.

5. For each note: call `brain_write(filepath, content)` with the full file content — do NOT use any filesystem or desktop tool. Add wikilinks between the two notes in the content before writing.
6. Report what was created and how to query the effort later:
   ```
   brain_query(tag="<project-slug>")
   ```

## Rules

- **Two documents minimum, two maximum** unless the user asks for more.
- **Tag both** with the effort slug so the full thread is queryable.
- **Effort note lives at `Efforts/<slug>.md`** — never inside a subfolder.
- **Context primer lives at `Efforts/<slug>/`** — always in the subfolder.
- **No invented content.** Populate from what the user has provided and what `brain_search` returns.
- **`type: project` is deprecated.** Always use `type: effort`.
