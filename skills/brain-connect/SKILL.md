---
name: brain-connect
description: Use when the user asks to find connections, related notes, or links for a specific note. Triggers on "what is this connected to", "find related notes", "wire this up", or a filepath with a request to surface links.
---

# Brain Connect

Find semantic and structural connections for a note. Report findings, offer to patch wikilinks.

## MCP-Only Skill

Uses MCP tools only. The brain lives inside a Docker container — filesystem tools (Glob, Grep, Read, Edit) will search the host filesystem, not the brain.

## Flow

### 1. Resolve the note

Accept any of:

- Relative path: `Cards/foo.md`
- MCP path: `/brain/Cards/foo.md`
- Title or description: run `brain_search(title)` to find it

Read the resolved note with `brain_read(filepath)`.

### 2. Search (run all three in parallel)

- `brain_related(filepath)` — semantic similarity via embeddings
- `brain_backlinks(filepath)` — notes that already wikilink TO this note (structural context)
- `brain_search(query="<key terms>")` — run multiple targeted searches using the note's title, tags, and key noun phrases to catch structural matches that embeddings may miss

Deduplicate. Exclude notes already wikilinked in the note body.

### 3. Report

Group by match strength:

```
Already links here (backlinks):
  Efforts/renewable-energy.md — wikilinks to this note

Strong match (semantic + keyword overlap):
  Efforts/renewable-energy/automation-proposal.md
  "automation and labour market reform..."

Weaker match (keyword only):
  Cards/universal-basic-income.md — shared tag: economics
```

### 4. Offer to patch

Ask: "Want me to add these as `[[wikilinks]]`?"

If yes, for each candidate:
- `brain_edit(op=insert_wikilink, filepath=<this note>, target=<candidate title>, context_heading="Related")`
- `insert_wikilink` is idempotent — safe to call without checking if the link already exists
- Report which links were added

## Common Mistakes

| Mistake | Fix |
|---|---|
| Including notes already linked in the body | Check existing wikilinks before reporting candidates |
| Only running semantic search | Always run additional `brain_search` queries for specific keywords from the note's title and tags |
| Adding wikilinks without asking | Always report first, then offer to patch |
