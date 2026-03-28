---
name: brain-connect
description: Use when the user asks to find connections, related notes, or links for a specific note. Triggers on "what is this connected to", "find related notes", "wire this up", or a filepath with a request to surface links.
---

# Brain Connect

Find semantic and structural connections for a note. Report findings, offer to patch wikilinks.

## Path Translation

MCP tools return `/brain/X` paths. Strip the `/brain` prefix to get the working path:
`/brain/Cards/foo.md` → `Cards/foo.md`

## Flow

### 1. Resolve the note

Accept any of:

- Relative path: `Cards/foo.md`
- MCP path: `/brain/Cards/foo.md` → strip `/brain` prefix
- Title or description: run `brain_search(title)` to find it

Read the resolved note with the `Read` tool.

### 2. Search (run all three in parallel)

- `brain_related(filepath)` — semantic similarity via embeddings
- `brain_backlinks(filepath)` — notes that already wikilink TO this note (structural context)
- `Grep` for key terms from the note's title and tags — catches structural links the embedding may miss (project slug, effort name, tag values, key noun phrases)

Deduplicate. Exclude notes already wikilinked in the note body.

### 3. Report

Group by match strength:

```
Already links here (backlinks):
  Efforts/jobs-guarantee.md — wikilinks to this note

Strong match (semantic + keyword overlap):
  Efforts/jobs-guarantee/automation-proposal.md
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
| Only running semantic search | Always Grep for keywords too — embeddings miss exact matches |
| Adding wikilinks without asking | Always report first, then offer to patch |
