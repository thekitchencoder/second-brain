# Brain-Level Skills Design

**Date:** 2026-03-17
**Skills:** `brain-capture`, `brain-connect`
**Install location:** `$BRAIN_HOST_PATH/.claude/skills/`
**Repo location:** `brain-skills/`

---

## Overview

Two skills installed directly in the vault (not the second-brain repo's `skills/` directory).
They run when Claude Code is opened at the vault root (e.g. Fleet terminal pane at `/brain/`).

**Hybrid approach:**
- MCP tools for semantic search (`brain_search`, `brain_related`, `brain_create`, `brain_write`)
- Direct filesystem tools for file I/O and structural search (`Read`, `Write`, `Edit`, `Glob`, `Grep`)

**Path translation:** MCP returns `/brain/X` paths. Strip `/brain` prefix to get the working-directory-relative path `./X`.

---

## `brain-capture`

Conversational idea capture with inline wiring after the user finishes editing.

### Trigger

User mentions a topic, idea, project, or event in conversation.

### Flow

```
1. SEARCH
   - brain_search(topic) to surface existing context
   - Strong match → read it, surface it, offer to update rather than create duplicate
   - Weak matches → save for wiring step

2. CONVERSE
   - Extract the idea through dialogue, one question at a time
   - Infer note type from content:
       vague idea / half-formed thought → discovery
       "we had a meeting / talked to X"  → meeting
       "I want to build / spec out"      → spec
       ongoing focus area               → effort
   - Only ask about type if genuinely ambiguous

3. CREATE
   - brain_create(template, title, directory)
   - Infer directory from topic context:
       known project slug   → Projects/<slug>/
       known effort         → Efforts/<slug>/
       unclear              → ask, or default to Cards/ for atomic ideas
   - brain_write(filepath, content) — write initial content with space for user to expand
   - Tell user: "Draft at Projects/jobs-guarantee/jobs-guarantee-automation.md"

4. WAIT
   - "Let me know when you've finished editing"

5. WIRE (after user confirms done)
   a. Read the updated note
   b. brain_search(title) + brain_related(filepath) to find related notes
   c. Patch [[wikilinks]] into the note body for top matches
   d. Find nearest _index.md via Glob (effort or project directory first, then parent)
   e. Add a reference line to the index
   f. Report: "Linked to 3 notes, added reference to Projects/jobs-guarantee/_index.md"
```

### Rules

- Never invent a top-level folder (Atlas, Efforts, Projects, Cards, Calendar, Sources only)
- Always search before creating — a duplicate is worse than an update
- Write only what was captured — no elaboration, no invented content
- `status: raw` on discovery notes — never set it to anything else during capture
- One note per idea

---

## `brain-connect`

Find and surface semantic + structural connections for any existing note. Offer to patch wikilinks.

### Trigger

User asks to find connections for a note, or names a filepath.

### Flow

```
1. RESOLVE
   - Accept: relative path, MCP path (/brain/X → ./X), or title → brain_search to find it
   - Read the note

2. SEARCH (two passes, run in parallel)
   a. brain_related(filepath) — semantic similarity
   b. Grep key terms from title + tags — catches structural links the embedding may miss
      (project slug, effort name, key concepts in frontmatter)
   - Deduplicate results
   - Exclude notes already wikilinked in the note body

3. REPORT — grouped by match strength
   Strong (semantic + keyword overlap):
     - Projects/jobs-guarantee/automation-proposal.md
       "automation and labour market reform..."
   Weaker (keyword only):
     - Cards/universal-basic-income.md — shared tag: economics

4. OFFER
   "Want me to add these as [[wikilinks]]?"
   - If yes:
       - If note has a ## Related section: append links there
       - If not: add ## Related at the bottom
       - Report which links were added
```

---

## Repo layout

```
brain-skills/
  brain-capture/
    SKILL.md
  brain-connect/
    SKILL.md
```

## Install

```bash
# Copy (one-off)
cp -r brain-skills/brain-* $BRAIN_HOST_PATH/.claude/skills/

# Or symlink (stays in sync with repo)
for d in brain-skills/brain-*/; do ln -sf "$PWD/$d" "$BRAIN_HOST_PATH/.claude/skills/"; done
```

---

## Future

- `brain-triage`: work through the discovery inbox (`status: raw` notes), promote or archive
- Backlink surfacing: once a convention is established for how backlinks are stored
- `brain-chat`: terminal RAG chat against the vault using local model (tracked in vault discovery note)
