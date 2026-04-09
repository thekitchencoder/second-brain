---
name: brain-surface
description: Use when the user asks what they've set aside, wants to review parked or simmering work, or says "what's simmering", "what am I not working on", "surface what I've put down", "what have I abandoned", "what's on the back burner".
---

# Brain Surface

Surface efforts with `intensity: simmering` — work that has been set aside but not abandoned. Present them oldest-first with any saved next steps, and offer to resume one.

## MCP-Only Skill

Uses MCP tools only. The brain lives inside a Docker container — filesystem tools (Glob, Grep, Read, Edit) will search the host filesystem, not the brain.

## Intensity Values

| Value | Meaning |
|---|---|
| `focus` | Active focus right now |
| `ongoing` | Background / low-frequency work |
| `simmering` | Set aside — intent to return |

## Flow

### 1. Find and read simmering efforts (subagent)

Dispatch a subagent with this task:

```
Run brain_query(status="active"). For each result, call brain_read(filepath) to get the
full note and check its type and intensity fields.

Filter to notes where:
  - type: effort
  - intensity: simmering  (or intensity field missing — flag those separately)

For each simmering effort extract:
  - title
  - created date
  - next_step field (if present)
  - left_off_because field (if present)
  - First non-empty line under ## Active Work (fallback if no next_step)

Sort by created ascending (oldest first — most at risk of being forgotten).

Return:
{
  "simmering": [
    { "path": "...", "title": "...", "created": "YYYY-MM-DD",
      "next_step": "...", "left_off_because": "..." },
    ...
  ],
  "missing_intensity": ["Efforts/foo.md", ...]  // active efforts with no intensity field set
}
```

### 2. Present ranked list

Use the subagent's `simmering` list (already sorted oldest-first):

```
You have N simmering efforts (oldest first):

1. Renewable Energy  [Efforts/renewable-energy.md]
   Set aside: 2026-01-15
   Next step: "Draft the funding model section"

2. Eink Display  [Efforts/eink-display.md]
   Set aside: 2026-02-03
   Next step: (none recorded)

3. ...
```

If a note has no `next_step`, flag it: "(no next step recorded — consider adding one when you resume)"

If `missing_intensity` is non-empty, mention: "N active efforts have no intensity set — run brain-hygiene to audit."

### 4. Offer actions

Ask: "Want to resume one of these, or set a next step on one?"

**Resume (set intensity back to active):**
```
brain_edit(op=update_frontmatter, filepath=<filepath>, frontmatter={intensity: "focus"})
```

**Set a next step:**
```
brain_edit(op=update_frontmatter, filepath=<filepath>, frontmatter={next_step: "<what the user says>"})
```

**Mark as done / archive:**
```
brain_edit(op=update_frontmatter, filepath=<filepath>, frontmatter={status: "archived"})
```

Report what changed.

## Setting intensity: simmering on an effort

When a user says "I'm putting X aside", "parking this", "set X to simmering":

```
brain_edit(op=update_frontmatter, filepath=Efforts/<slug>.md, frontmatter={intensity: "simmering"})
```

Offer to capture why and what's next:
```
brain_edit(op=update_frontmatter, filepath=Efforts/<slug>.md, frontmatter={
  left_off_because: "<reason>",
  next_step: "<first thing to do when resuming>"
})
```

## Rules

- **Read each effort fully** — search results only show excerpts, `next_step` may not be in the excerpt.
- **Sort oldest first** — longest-parked work is at highest risk of being lost.
- Always confirm which effort the user wants before acting — don't auto-resume.
- **`next_step` is not required** — flag its absence but don't block on it.

## Common Mistakes

| Mistake | Fix |
|---|---|
| Showing only search excerpts | Call `brain_read` for each simmering effort |
| Auto-resuming without asking | Always present list first, then offer actions |
| Skipping efforts with no `intensity` field | Also `brain_read` each active effort to check intensity field |
| Forgetting to offer to capture `next_step` when setting simmering | Always prompt for it — this is the critical handoff context |
