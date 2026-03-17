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

### 2. Search (run both in parallel)

- `brain_related(filepath)` — semantic similarity via embeddings
- `Grep` for key terms from the note's title and tags — catches structural links the embedding may miss (project slug, effort name, tag values, key noun phrases)

Deduplicate. Exclude notes already wikilinked in the note body.

### 3. Report

Group by match strength:

```
Strong match (semantic + keyword overlap):
  Projects/jobs-guarantee/automation-proposal.md
  "automation and labour market reform..."

Weaker match (keyword only):
  Cards/universal-basic-income.md — shared tag: economics
```

### 4. Offer to patch

Ask: "Want me to add these as `[[wikilinks]]`?"

If yes:
- Note has `## Related` section → append links there
- No `## Related` section → add one at the bottom of the note
- Use `Edit` to patch the file directly
- Report which links were added and where

## Common Mistakes

| Mistake | Fix |
|---|---|
| Including notes already linked in the body | Check existing wikilinks before reporting candidates |
| Only running semantic search | Always Grep for keywords too — embeddings miss exact matches |
| Adding wikilinks without asking | Always report first, then offer to patch |
