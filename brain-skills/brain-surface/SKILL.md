---
name: brain-surface
description: Use when the user asks what they've set aside, wants to review parked or simmering work, or says "what's simmering", "what am I not working on", "surface what I've put down", "what have I abandoned", "what's on the back burner".
---

# Brain Surface

Surface efforts with `intensity: simmering` — work that has been set aside but not abandoned. Present them oldest-first with any saved next steps, and offer to resume one.

## Path Translation

MCP paths: `/brain/X` → `X` (strip `/brain` prefix)

## Intensity Values

| Value | Meaning |
|---|---|
| `on` | Active focus right now |
| `ongoing` | Background / low-frequency work |
| `simmering` | Set aside — intent to return |

## Flow

### 1. Find simmering efforts

**Call `brain_query(status="active")` NOW.** Do not proceed until you have results.

Filter the returned notes to:
- `type: effort`
- `intensity: simmering`

If no results have `intensity` set at all, also surface efforts with `status: active` that haven't been mentioned recently — **Call `Grep(pattern="intensity: simmering", path="Efforts/", glob="*.md")` NOW** as a fallback.

### 2. Read each simmering effort

For each match, **call `brain_read(filepath)` NOW** to get the full note. Extract:
- `title`
- `created` date
- `next_step` field (if present)
- `left_off_because` field (if present)
- First item under `## Active Work` (if no `next_step` field)

### 3. Present ranked list

Sort oldest `created` first — these are most at risk of being forgotten.

```
You have N simmering efforts (oldest first):

1. Jobs Guarantee  [Efforts/jobs-guarantee.md]
   Set aside: 2026-01-15
   Next step: "Draft the funding model section"

2. Eink Display  [Efforts/eink-display.md]
   Set aside: 2026-02-03
   Next step: (none recorded)

3. ...
```

If a note has no `next_step` and no Active Work items, flag it: "(no next step recorded — consider adding one when you resume)"

### 4. Offer actions

Ask: "Want to resume one of these, or set a next step on one?"

**Resume (set intensity back to active):**
```
brain_edit(op=update_frontmatter, filepath=<filepath>, frontmatter={intensity: "on"})
```

**Set a next step:**
```
brain_edit(op=update_frontmatter, filepath=<filepath>, frontmatter={next_step: "<what the user says>"})
```

**Mark as done / archive:**
```
brain_edit(op=update_frontmatter, filepath=<filepath>, frontmatter={status: "archived", intensity: "on"})
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
- **Never auto-resume.** Always confirm which effort the user wants to act on.
- **`next_step` is not required** — flag its absence but don't block on it.

## Common Mistakes

| Mistake | Fix |
|---|---|
| Showing only search excerpts | Call `brain_read` for each simmering effort |
| Auto-resuming without asking | Always present list first, then offer actions |
| Skipping efforts with no `intensity` field | Also Grep for `intensity: simmering` as fallback |
| Forgetting to offer to capture `next_step` when setting simmering | Always prompt for it — this is the critical handoff context |
