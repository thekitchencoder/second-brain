---
name: brain-context
description: Use when starting work on a project with a brain effort linked, when the user mentions a topic or project name, or when the SessionStart hook indicates an effort is available. Searches the second-brain for prior context before starting work.
---

# Brain Context

Surface relevant context from the brain for the current project or topic. A subagent gathers effort notes and context primers, returning a compact briefing. Full note content enters the main conversation only on demand.

## When to Use

- The SessionStart hook injected an effort path — load context for it
- The user names a project, concept, or topic they want to work on
- You're about to start work and suspect the brain has relevant prior context

## Path Translation

`brain_search`, `brain_create`, and `brain_related` return absolute paths like `/brain/Cards/foo.md`. `brain_query` and `brain_backlinks` return brain-relative paths like `Cards/foo.md`.

- **MCP tools** (brain_read, brain_edit, etc.): pass the path as returned — both formats accepted
- **Filesystem tools** (Edit, Read): use for project files on the host (e.g. CLAUDE.md), NOT for brain files

## Flow

### 1. Resolve the effort

**If an effort path is known** (from SessionStart hook context or user direction):
- Call `brain_read(filepath)` to verify it exists
- If 404 → link is stale, fall through to cascade resolution

**Cascade resolution** (first time or stale link):
1. Slugify the project directory name (lowercase, hyphens for spaces/underscores) → scan results of `brain_query(type="effort")` for a filename match
2. No match → extract the project name and first paragraph from the project's CLAUDE.md → `brain_search(query="<name> <description excerpt>")`
3. Single confident match → use it
4. Multiple plausible matches → ask the user which effort this project belongs to
5. No match at all → tell the user, offer to create a new effort with `brain-create-effort`

Once resolved, tell the main agent to write the brain block to the project's CLAUDE.md:
```
<!-- brain -->
effort: <resolved effort path>
summary: <one-line summary from the effort's Goal section>
<!-- /brain -->
```

### 2. Gather context (subagent)

Dispatch a subagent with this task:

```
Load context for effort: <effort_path>

1. Read the effort note: brain_read(<effort_path>)
   Extract: title, status, intensity, next_step, parents, wikilinks in the body.

2. If the effort has parents, read each parent effort:
   brain_read("Efforts/<parent>.md") for each entry in the parents field.
   Extract their wikilinks too.

3. Collect context primers:
   From the effort's wikilinks and parent effort's wikilinks, call brain_read
   for each linked note. Identify notes with type: context-primer.

4. For context primers found:
   - Read each in full
   - Assess relevance to the project (based on the effort's goal and active work)
   - Return full content for relevant primers (max 3)
   - Return title + one-line summary for the rest

5. For all other linked notes (not primers):
   Extract: title, type, status, 2-4 key points

6. Sort by relevance: high (directly about the effort), medium (related), low (tangential).

Return:
{
  "effort": {
    "path": "...", "title": "...", "status": "...", "intensity": "...",
    "next_step": "...", "goal": "...", "active_work": "..."
  },
  "parent_efforts": [
    { "path": "...", "title": "...", "status": "...", "intensity": "..." }
  ],
  "primers": [
    { "path": "...", "title": "...", "full_content": "...", "loaded": true },
    { "path": "...", "title": "...", "summary": "one line", "loaded": false }
  ],
  "notes": [
    { "path": "...", "title": "...", "type": "...", "status": "...",
      "relevance": "high|medium|low", "key_points": ["...", "..."] }
  ]
}
```

### 3. Present the briefing

**Effort summary:**
```
## Project Context — <title>
Effort: <path> (intensity: <intensity>)
Next step: <next_step or "none recorded">
Goal: <goal excerpt>
```

**Parent effort** (if any):
```
Parent: [[<parent-slug>]] (<status>, <intensity>)
```

**Context primers** (loaded in full):
```
### Context: <primer title>
[full primer content]
```

**Primers available but not loaded:**
```
Available primers: [[slug]] — one-line summary, [[slug]] — one-line summary
```

**Related notes** (high and medium relevance, summaries only):
```
### Related Notes
- [type/status] <title> → <path>
  key points...
```

Low-relevance notes: mention count only.

### 4. Write the brain block

If this was a first-time resolution (no existing brain block), use the Edit tool to append the block to the project's CLAUDE.md:

```
<!-- brain -->
effort: <effort path>
summary: <one-line from goal>
<!-- /brain -->
```

If the block already exists but the effort path changed (stale link resolved), use Edit to update it.

### 5. Load more as needed

**Load proactively** when:
- The task directly involves a note shown in the briefing
- A primer was listed as "available" but is clearly needed for the current work
- A high-relevance note contains information the task will require

**Ask first** when:
- Multiple notes look equally relevant and loading all would be excessive
- A note is medium or low relevance

Call `brain_read(filepath)` for the specific note and surface the content.

## Context primer loading rules

- Load the effort's own context primers (directly linked from the effort note)
- If the effort has a parent, also load the parent's context primers
- Do NOT follow sibling efforts or traverse further
- If multiple primers exist, the subagent returns full content for up to 3 project-relevant ones; the rest as summaries
- The main agent can load additional primers on demand during the conversation

## Wikilinks

Wikilinks in the brain use filename stems, not titles. When presenting links to the user, use the `[[filename-stem]]` format.

## Rules

- Context primers always load in full — they exist to be read. Cap at 3 per effort level.
- Everything else is summary-first; full content on demand only.
- Do not re-derive concepts that exist in the brain — use what is there.
- If nothing is found, say so explicitly. Offer to create a new effort.
- The brain block in CLAUDE.md is a cache — always verify the effort exists before trusting it.
