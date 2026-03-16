---
name: brain-context
description: Use when the user mentions a topic, project name, or concept they want to work on — searches the second-brain for prior context before starting work.
---

# Brain Context

Before starting work on a topic, search the second-brain to surface what's already been established.

## When to Use

Invoke when the user names a project, concept, or topic they want to work on. Do not invoke at every session start — only when there is a concrete subject to search for.

## Steps

1. Run `brain_search(query)` using the topic as the query
2. If a tag can be inferred from the topic, also run `brain_query(tag=<slug>)`
3. If a related filepath is known, run `brain_related(filepath)` to find connected notes
4. For any result with `status: current` or `type: context-primer`, call `brain_read(filepath)` to retrieve the full document — search results only show a short excerpt
5. Surface the full content of key documents; for less relevant hits show the frontmatter summary only

## Interpreting Results

| `status` value | Meaning |
|---------------|---------|
| `current` | Established — treat as reliable context |
| `draft` | Speculative — flag as work in progress |
| `archived` | Historical — may be superseded |

## Rules

- If nothing is found, say so explicitly. Do not invent context.
- Do not re-derive or re-explain concepts that exist in the brain — use what is there.
- Empty results are not a failure — they mean this topic is new to the brain.
