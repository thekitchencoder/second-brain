---
name: brain-project
description: Use when the user says "start a new project", "set up a project", or asks to scaffold new work in the second-brain.
---

# Brain Project

Scaffold a new effort in the second-brain with two seed documents.

## Path Notes

The brain lives inside a Docker container — use MCP tools to inspect brain paths. Filesystem tools (Glob, Read, etc.) will search the host, not the brain. When MCP tools return absolute paths like `/brain/Efforts/foo.md`, pass them directly back to other MCP tools unchanged.

## Steps

1. Ask for a project name if not provided. Derive a kebab-case slug (e.g. `my-project-name`).

2. Run `brain_query(type="effort")` to see existing efforts and understand the established pattern.

3. Run `brain_search(query=<topic>)` to find any prior related work. For any relevant hit, call `brain_read(filepath)` to get the full content before drafting new notes.

4. Run `brain_templates()` to see what templates are available. Then create two notes:

### Note 1: Effort Note

Run `brain_create(template="effort", title="<Project Name>", directory="Efforts/")`. Note the returned filepath (should be `Efforts/<slug>.md`).

Populate using `brain_edit`, not `brain_write`:

```
brain_edit(op=update_frontmatter, filepath=<effort filepath>, frontmatter={
  title: "<Project Name>",
  tags: ["effort", "<slug>"]
})
```

If the user provided a linked dev repo:
```
brain_edit(op=update_frontmatter, filepath=<effort filepath>, frontmatter={
  dev: { "<hostname>": "<absolute-path-to-repo>" }
})
```

Then fill in body sections:
```
brain_edit(op=replace_section, filepath=<effort filepath>, heading="Goal", body="<one-line goal statement>")
brain_edit(op=replace_section, filepath=<effort filepath>, heading="Active Work", body="<initial work items, one per line>")
brain_edit(op=replace_section, filepath=<effort filepath>, heading="Notes", body="[[<Context Primer title>]]")
```

Ask whether this effort has a linked dev repo on this machine. If yes, add the `dev:` map via `update_frontmatter` above.

### Note 2: Context Primer

Run `brain_create(template="context-primer", title="<Project Name> — Context", directory="Efforts/<slug>/")`. Note the returned filepath.

Populate using `brain_edit`, not `brain_write`:

```
brain_edit(op=update_frontmatter, filepath=<primer filepath>, frontmatter={
  title: "<Project Name> — Context",
  tags: ["context", "<slug>"]
})
brain_edit(op=replace_section, filepath=<primer filepath>, heading="Purpose of This Document", body="<problem statement and goals>")
brain_edit(op=replace_section, filepath=<primer filepath>, heading="Background", body="<background from user + prior work found in step 3>")
brain_edit(op=replace_section, filepath=<primer filepath>, heading="Key Details", body="<key decisions made so far>")
```

Add a wikilink from the context primer back to the effort note:
```
brain_edit(op=insert_wikilink, filepath=<primer filepath>, target="<Project Name>", context_heading="Key Details")
```

5. Report what was created and how to query the effort later:
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
- Use `brain_edit` after `brain_create`, not `brain_write` — preserves template frontmatter.
