---
name: brain-distil
description: Use when the user wants to create or update a context primer from one or more source notes. Triggers on "create a context primer from these", "distil my research into a primer", "make a primer for X from Y and Z", "build a context primer".
---

# Brain Distil

Synthesise one or more source notes into a context primer for an effort. The primer is a concise, structured reference doc loaded by Claude at the start of every session on that effort — it must stay under 400 words.

## MCP-Only Skill

Uses MCP tools only. The brain lives inside a Docker container — filesystem tools (Glob, Grep, Read, Edit) will search the host filesystem, not the brain.

## Flow

### 1. Identify the sources

Accept any mix of:
- Explicit paths (`Efforts/renewable-energy/research.md`)
- Titles → resolve via `brain_search(title)`
- A search query → run `brain_search(query)`, confirm which results to include

Collect the resolved paths.

### 2. Identify the effort

Infer the effort from source frontmatter (`effort:` field), tags, or folder path. If ambiguous or absent, ask the user: "Which effort is this primer for?"

### 3. Check if the effort exists

Run `brain_search(query="<effort-slug>")` and check for a result at `Efforts/<slug>.md`.

**If the effort does not exist:** say "No effort note found for `<slug>`. Want me to create one first?" and invoke `brain-create-effort` if the user confirms. Do not proceed until the effort note exists.

### 4. Check for an existing primer

Run `brain_search(query="<effort-slug> context primer")` and look for a result with `type: context-primer` in `Efforts/<slug>/`.

- **Found** → offer to update the existing primer rather than create a new one. Confirm with the user before overwriting any sections.
- **Not found** → proceed to create.

### 5. Synthesise (subagent)

Dispatch a subagent with this task:

```
Read each of the following source notes in full using brain_read:
<list of resolved source paths>

Synthesise the content into a context primer for the effort: <effort name>

A context primer is a concise orientation document — loaded in full by Claude at the
start of every work session. It must be under 400 words total. Distil; do not transcribe.

Return a JSON object with these four fields. Each value is a short prose block or
bullet list — no headings, no padding:

{
  "purpose": "One sentence: what this effort is and what the primer is for.",
  "background": "Key history, framing, prior work, and external context a collaborator needs.",
  "key_details": "Decisions already made, constraints, technical choices, things that are settled.",
  "open_questions": "Active tensions, unresolved questions, or things still being figured out."
}

If the combined text of all four fields exceeds 400 words, trim key_details and
background first — keep open_questions and purpose intact.
```

### 6. Create or update the primer

**Creating:**
```
brain_create(template="context-primer", title="<Effort Name> — Context", directory="Efforts/<slug>/")
```

Populate using `brain_edit(op=replace_section, ...)` for each section:

| Frontmatter section | Subagent field |
|---|---|
| `## Purpose of This Document` | `purpose` |
| `## Background` | `background` |
| `## Key Details` | `key_details` |
| `## Open Questions` | `open_questions` |

Set the effort tag:
```
brain_edit(op=update_frontmatter, filepath=<primer path>, frontmatter={
  title: "<Effort Name> — Context",
  tags: ["context", "<slug>"]
})
```

**Updating:** use `brain_edit(op=replace_section, ...)` for any sections that have changed. Do not overwrite sections the user asked to leave untouched.

### 7. Link sources into the primer

For each source note, insert a wikilink under `## Key Details`:
```
brain_edit(op=insert_wikilink, filepath=<primer path>, target="<source title>", context_heading="Key Details")
```

### 8. Link primer into the effort note

Insert a wikilink from the effort note to the primer:
```
brain_edit(op=insert_wikilink, filepath="Efforts/<slug>.md", target="<Effort Name> — Context", context_heading="Notes")
```

`insert_wikilink` is idempotent — safe to call even if the link already exists.

### 9. Report

```
Created: Efforts/<slug>/context.md
Linked from: Efforts/<slug>.md → ## Notes
Sources linked: 3 notes under ## Key Details
Word count: ~280 words
```

## Rules

- **Under 400 words.** If the synthesis is too long, tell the subagent to trim and re-synthesise.
- **Distil, don't transcribe.** The primer is orientation, not a summary of every source.
- **Check for existing primer first.** Update rather than duplicate.
- **Effort must exist before creating the primer.** Invoke `brain-create-effort` if needed.
- Use `brain_edit` after `brain_create`, not `brain_write` — preserves template frontmatter.
