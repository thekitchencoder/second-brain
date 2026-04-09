# The brain vault

This guide covers how the vault is organized, what the frontmatter fields do, and how the pieces connect. The quick version: notes go in folders by kind, YAML frontmatter makes them searchable, and skills use both to surface what matters.

## Philosophy

The vault is a place to think, not a filing system. You throw things in, tag them loosely, and let the tooling find connections later.

**Capture first, organize later.** Ideas are fragile. The system makes it cheap to grab one before it disappears. You decide what it means during triage, not at capture time.

**Connections over documents.** Notes reference each other, belong to efforts, share tags. The tooling surfaces those relationships so you don't have to hold them in your head.

**Visible state.** Notes move through statuses: raw, draft, current, archived. You can see what's half-finished, what's waiting for review, and what's actually done.

**Emergent structure.** You don't pre-organize. You tag, link, and the system reveals patterns: which efforts are active, what's been sitting idle, where you keep coming back to.

Semantic search (by meaning, not just keywords) and frontmatter metadata make this work. That's why both matter.

---

## Vault structure

The top-level folders are loosely inspired by ACE (Atlas, Calendar, Efforts). It's not a strict implementation — the idea is just that different kinds of thinking belong in different places.

### Atlas

Reference material, stable knowledge, reusable frameworks. Design patterns, glossaries, synthesis of prior research. Notes in Atlas are durable and reviewed. You link to them from anywhere. Put things here when you've synthesized something into a form you'll actually come back to.

### Efforts

Active areas of focus. Each effort gets its own folder with a kebab-case slug: `Efforts/co-dependent-confabulation/`, `Efforts/eink-display/`.

The effort note itself (`Efforts/co-dependent-confabulation.md`) is the hub — goal, links to related work, intensity, status. Subfolders hold supporting material: meeting notes, research, specs, context primers.

Efforts have a lifecycle. They start with a goal, accumulate work, sometimes pause, and eventually complete or get archived.

### Cards

Atomic ideas and loose discoveries that don't belong to a specific effort yet. A design idea, an observation, a standalone research finding. Cards might eventually get folded into an effort or promoted to Atlas. When in doubt about where something goes, Cards is fine — the system can surface and reorganize later.

### Calendar

Daily notes, one per day (`Calendar/2026-04-08.md`). The brain-daily skill creates these and seeds them with carried-forward items from yesterday.

### Sources

External material: papers, articles, books, interviews. Marked with `type: source`. They preserve the original source and your notes on it.

### Hidden folders

Leave these alone:

- `.zk/` — note system (zk) configuration and templates
- `.ai/` — semantic search database (SQLite + embeddings)
- `.vscode/` — VS Code workspace config
- `.claude/` — Claude Code skills and MCP config
- `.trash/` — deleted notes, restorable

---

## Frontmatter

Every note starts with a YAML block at the top. This metadata is what the tooling uses to answer questions like "show me all active efforts" or "what's simmering?" and to connect notes during search.

It tracks what the note is (type), where it stands (status, intensity), what it belongs to (effort, tags), and when it was created.

### Common fields

| Field | Purpose | Example values |
|-------|---------|---------------|
| `type` | Kind of note | `effort`, `discovery`, `meeting`, `spec`, `doc`, `adr`, `source`, `context-primer`, `note`, `daily` |
| `status` | Lifecycle position | `draft`, `current`, `raw`, `archived`, `proposed`, `accepted` |
| `intensity` | Effort focus level | `focus` (active), `ongoing` (background), `simmering` (parked) |
| `created` | Creation date | `2026-04-08` |
| `date` | For daily/dated notes | `2026-04-08` |
| `tags` | Searchable labels | `["effort", "co-dependent-confabulation", "economic-policy"]` |
| `title` | Note title (used in search) | Any string |
| `effort` | Parent effort for non-effort notes | `co-dependent-confabulation` or `""` |
| `captured` | When a discovery was captured | `2026-04-08` |
| `device` | Where a discovery came from | `phone`, `voice`, `laptop` |

### By note type

**Note (default)**
```yaml
type: note
title: "{{title}}"
created: {{date}}
tags: []
status: draft
```
The catch-all for anything that doesn't fit a more specific template.

**Discovery**
```yaml
type: discovery
title: "{{title}}"
status: raw
captured: {{date}}
device: ""
effort: ""
tags: [discovery]
```
Ideas you've captured. Start as `raw` and wait for triage. Fill in `effort` if the idea belongs to one. `device` is optional — where were you when the idea hit?

**Daily**
```yaml
type: daily
title: "{{date}}"
date: {{date}}
created: {{date}}
tags: [daily]
```
One per day. Created by brain-daily, seeded with yesterday's carried-forward items.

**Effort**
```yaml
type: effort
title: "{{title}}"
status: active
intensity: focus
parents: []
created: {{date}}
tags: [effort]
```
The hub of an area of focus. `intensity` is the important field: `focus` (active), `ongoing` (background), or `simmering` (parked, intending to return). `parents` is for nested efforts but most people keep things flat.

**Context primer**
```yaml
type: context-primer
title: "{{title}}"
status: current
created: {{date}}
tags: [context]
```
Background and context for an effort. Lives in `Efforts/<slug>/`. Set `status: current` on the authoritative version, archive old ones.

**Meeting**
```yaml
type: meeting
title: "Meeting — {{title}}"
date: {{date}}
attendees: []
effort: ""
created: {{date}}
tags: [meeting]
```
Link to an effort via the `effort` field if relevant.

**Spec**
```yaml
type: spec
title: "{{title}}"
effort: ""
status: draft
created: {{date}}
tags: [spec]
```
A specification or detailed design, usually part of an effort.

**Doc**
```yaml
type: doc
title: "{{title}}"
effort: ""
status: draft
created: {{date}}
tags: []
```
Documentation or design notes. Could belong to an effort or stand alone.

**ADR (architecture decision record)**
```yaml
type: adr
id: ADR-000
effort: ""
title: "{{title}}"
status: proposed
date: {{date}}
created: {{date}}
tags: [adr]
```
Formal decision records. Status values: `proposed`, `accepted`, `deprecated`.

---

## How notes move through states

```
Capture (raw) → Review (draft) → Use (current) → Done (archived)
```

### Status values

- **raw** — just captured, unreviewed. Default for discoveries.
- **draft** — you've looked at it, still working on it.
- **current** — active, in use, or recently reviewed.
- **archived** — done or intentionally set aside.

ADRs also use `proposed` → `accepted` or `deprecated`.

### Intensity (efforts only)

Separate from status — two independent dimensions.

- **focus** — you're actively working on this. Keep to 1-3 at a time.
- **ongoing** — background work you return to regularly.
- **simmering** — parked but not abandoned. The system surfaces these so you don't forget them.

When you're done with an effort, set `status: archived`.

---

## Tags

Every note has a `tags` field. Tags let you query things like "all notes tagged `economic-policy`" or "everything in the `co-dependent-confabulation` effort."

### Conventions

| Pattern | What it's for | Example |
|---------|---------------|---------|
| Type markers | Added by templates automatically | `effort`, `context`, `meeting`, `discovery` |
| Effort slugs | All notes in an effort share the slug | `co-dependent-confabulation` |
| Domain tags | Group related ideas across efforts | `epistemic-lens`, `technical`, `research` |
| Reserved | System use | `daily`, `adr` |

You don't need to tag everything. If a note belongs to an effort, tag it with the effort's slug so `brain_query(tag="co-dependent-confabulation")` finds it. Type tags are added by templates already.

---

## Wikilinks

Notes point to each other with wikilinks:

```markdown
This idea relates to [[another note]] and builds on [[context-primer]].
```

Cmd+click navigates in VS Code (via Foam). The system tracks backlinks — which notes point to you.

- `[[Note Title]]` — link by title, system finds it regardless of folder
- `[[Note Title|Display Text]]` — alias for display
- `[[filename]]` — works too, title is cleaner

The system uses backlinks for effort management. When you ask "what's the status of the co-dependent-confabulation effort?", it reads the effort note's wikilinks and builds a status overview from everything linked.

---

## A worked example

Say you're starting research on a co-dependent confabulation policy.

**1. Create the effort.** Run brain-create-effort. It creates `Efforts/co-dependent-confabulation.md`:

```markdown
---
type: effort
title: "Co-dependent Confabulation"
status: active
intensity: focus
created: 2026-04-08
tags: [effort, co-dependent-confabulation]
---

# Co-dependent Confabulation

## Goal
Research and model a universal co-dependent confabulation policy.

## Active Work

## Notes

## Related
```

**2. Capture research.** You read a paper. brain-capture creates a discovery note:

```markdown
---
type: discovery
title: "Co-dependent Confabulation Implementations Review"
status: raw
captured: 2026-04-08
effort: co-dependent-confabulation
tags: [discovery, co-dependent-confabulation]
---

## Idea
Australia's co-dependent confabulation experiment (2015-2020) showed employment gains of 8-12% in treated regions...

## Why it matters
Implementation data beats theory. This gives us a testable model.
```

The `effort: co-dependent-confabulation` field and tag link it to the effort.

**3. Triage.** When you're ready to process your inbox, run brain-triage:

```
You have 3 notes awaiting review. Working through them oldest first.

[1/3] Co-dependent Confabulation Implementations Review
Summarise: Australian field data on co-dependent confabulation effectiveness...

[p] Promote → [a] Archive → [d] Defer → [s] Stop
```

Promote sets `status: draft`, runs semantic search for related notes, offers to insert wikilinks, and adds a link from the effort hub.

**4. Check effort status.** Ask "where does the co-dependent-confabulation effort stand?" and brain-effort finds the effort note, searches for tagged notes, reads the wikilinks, groups everything by status, and flags orphans (tagged but not linked from the hub).

---

## The workflow

1. **Capture** — ideas go to Cards, Discoveries, or directly into Efforts
2. **Triage** — review raw notes, promote or archive
3. **Connect** — link related notes; the system suggests connections
4. **Surface** — "what's active?", "what's simmering?", "what's in this effort?"
5. **Archive** — mark completed work archived; it stays in the vault, just out of the way

Frontmatter and tags make steps 3-5 possible. Semantic search finds notes you'd forgotten. Wikilinks make connections explicit.

---

## Common questions

**Should I tag everything?**
No. Tag notes that belong to efforts (with the effort slug) and notes you want to search together by domain. Type tags are added by templates.

**Where should I put this note?**
- Has a defined effort → `Efforts/<slug>/`
- Reference or synthesis → `Atlas/`
- Loose idea or discovery → `Cards/`
- Today's note → `Calendar/`
- External material → `Sources/`
- Not sure → `Cards/`

**Draft vs current?**
Draft means you're still working on it. Current means it's ready or represents your current understanding. For context primers, `status: current` marks the authoritative version.

**Nested efforts?**
The `parents` field supports it, but most people keep efforts flat and use tags to group related ones.

**Deleted notes?**
They move to `.trash/` and get removed from the search index. You can restore them.

**Reindexing?**
The system watches for changes and reindexes automatically. Force a full reindex with `brain-index run` if needed.

---

## Editing frontmatter

Frontmatter is YAML:
- 2 spaces for indentation, not tabs
- Strings with special characters need quotes: `title: "Use SQLite for storage?"`
- Lists use square brackets: `tags: [effort, co-dependent-confabulation]`
- Empty fields: `effort: ""` or just omit them

Templates handle this for you. If you hand-edit and break the YAML, the system will warn you.

The `brain-edit` tool updates frontmatter without touching the note body:

```
brain_edit(op=update_frontmatter, filepath="Efforts/co-dependent-confabulation.md",
  frontmatter={"status": "archived", "intensity": "simmering"})
```

---

## Scope and custom fields

The database stores a `scope` field for each indexed chunk — the section heading where text appears (e.g. "Goal", "Related Notes"). This lets semantic search weight hits by where they appear in a note.

You can add custom fields to frontmatter:

```yaml
type: effort
title: "Co-dependent Confabulation"
status: active
intensity: focus
owner: "Chris"
budget: "$50K"
created: 2026-04-08
tags: [effort, co-dependent-confabulation]
```

The system won't query on custom fields, but skills may read them.

---

## Getting started

1. Run `brain-init` to set up the vault structure, templates, and embeddings database
2. Run `brain-daily` to create today's note
3. Use `brain-capture` to add a discovery
4. Use `brain-create-effort` to start an effort
5. Run `brain-triage` weekly to process your inbox
