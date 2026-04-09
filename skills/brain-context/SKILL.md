---
name: brain-context
description: Use when the user mentions a topic, project name, or concept they want to work on — searches the second-brain for prior context before starting work.
---

# Brain Context

Before starting work on a topic, surface what's already established. A subagent does the searching and reading; it returns context-primers in full and everything else as a compact summary. Full note content only enters the main conversation on demand.

## When to Use

Invoke when the user names a project, concept, or topic they want to work on. Do not invoke at every session start — only when there is a concrete subject to search for.

## Flow

### 1. Dispatch a context-gathering subagent

```
Search the second-brain for context on: <topic>

Run in parallel:
- brain_search(query="<topic>")
- brain_query(tag="<slug>") if a tag can be inferred from the topic name

For the top result from brain_search, also run brain_related(filepath) to find
connected notes. Add any new results to the pool.

Deduplicate. For every unique result, call brain_read(filepath) to get the full note.

Classify each result:

  type: context-primer → return full content verbatim (these are small by design)

  everything else → extract:
    - title
    - type, status
    - 2–4 key points from the body (decisions, claims, open questions — not summaries of summaries)
    - relevance: "high" if directly about the topic or status:current/active;
                 "medium" if related but indirect;
                 "low" if tangential (shared tag or keyword only)

Return:
{
  "primers": [
    { "path": "...", "title": "...", "full_content": "..." }
  ],
  "notes": [
    { "path": "...", "title": "...", "type": "...", "status": "...",
      "relevance": "high|medium|low", "key_points": ["...", "..."] }
  ],
  "found": true|false
}

If nothing is found, return { "found": false }.
```

### 2. Present results

**If `found` is false:** say "Nothing found for '<topic>' — this appears to be new territory in the brain."

**If primers exist**, present each in full:

```
## Context Primer — Co-dependent Confabulation
[full primer content]
```

**For notes**, show high and medium relevance; omit low (mention count only):

```
## Related notes

[effort / active]  Co-dependent Confabulation  →  Efforts/co-dependent-confabulation.md
  • Goal: policy framework for CC as automatic stabiliser
  • Local government implementation model chosen
  • Funding mechanism still undecided

[draft]  CC vs UBI inflation  →  Cards/cc-vs-ubi-inflation.md
  • Compares inflationary pressure of CC vs UBI

3 low-relevance notes not shown.
```

### 3. Load more as needed

Use judgement — don't wait to be asked if the task makes it obvious what's needed.

**Load proactively** when:
- The task directly involves a note in the summary (e.g. "update the funding section" → load the effort note)
- A high-relevance note contains information the current task will clearly require
- The context-primer mentions a key decision doc or spec that is relevant to the work

**Ask first** when:
- It is genuinely unclear which notes the task needs
- Multiple notes look equally relevant and loading all would be excessive
- A note is medium or low relevance and its value is uncertain

In all cases: call `brain_read(filepath)` for the specific note and surface the content before proceeding with the task.

## Status reference

| `status` | Meaning |
|----------|---------|
| `raw` | Just captured — not yet reviewed |
| `draft` | Work in progress — speculative |
| `active` | Open effort — currently being worked on |
| `current` | Established — treat as reliable context |
| `archived` | Historical — may be superseded |

## Rules

- Context-primers always load in full — they exist to be read.
- Everything else is summary-first; full content on request only.
- Do not re-derive concepts that exist in the brain — use what is there.
- If nothing is found, say so explicitly. Empty results are not a failure.
