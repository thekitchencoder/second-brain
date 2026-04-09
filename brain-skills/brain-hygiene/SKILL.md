---
name: brain-hygiene
description: Use when asked to tidy, audit, or health-check the second-brain — checks frontmatter completeness, orphaned notes, broken wikilinks, and stale drafts. Can fix broken wikilinks and restructure files.
---

# Brain Hygiene

Systematic audit of the second-brain. Dispatch five parallel subagents to scan the brain; interpret findings and handle repairs in the main conversation.

This skill runs in the brain root with full filesystem access (Glob, Grep, Read, Edit). Use MCP tools for semantic operations, filesystem tools for structural scans and repairs.

## Schema Reference

**Required universal fields (all types):**
```
type, title, status, tags
```
Plus a date field: `created` for all types except `discovery`, which uses `captured` instead.

**Valid types:** `effort`, `discovery`, `context-primer`, `spec`, `adr`, `source`, `meeting`, `daily`

**Valid status values by type:**

| Type | Valid status values |
|------|-------------------|
| `discovery` | `raw`, `draft`, `current`, `archived` |
| `effort` | `active`, `archived` |
| `context-primer` | `draft`, `current`, `archived` |
| `spec`, `doc` | `draft`, `current`, `archived` |
| `adr` | `proposed`, `accepted`, `deprecated` |
| `meeting`, `daily` | status field optional |

**`intensity` field — required on `type: effort`:**

| Value | Meaning |
|-------|---------|
| `focus` | Primary attention right now |
| `ongoing` | Background / regular, not primary focus |
| `simmering` | Set aside — intent to return |

**Deprecated types:** `project` → `effort`, `moc` → `effort`

**Deprecated intensity value:** `on` → `focus`

**Deprecated fields (remove when found):**
`project:` (use `^project:\s` regex to avoid matching `project-id:`), `scope:`, `technical-level:`, `phase:`, `stack:`, `repo:`, `agents:`, `priority:`, `complexity:`, `delegate:`, `assignee:`

**ADR exceptions:** `id:` and `date:` (decision date, distinct from `created:`) are valid on `type: adr`.

---

## Flow

### 1. Dispatch all five checks as parallel subagents

Each subagent scans and returns a structured report. No repairs — findings only.

---

**Subagent 1 — Frontmatter audit**

```
Walk every .md file under the brain root using Glob(pattern="**/*.md"). Skip any path containing ".trash/".
For each file, Read it and parse the YAML frontmatter block (between the --- delimiters).
Check for the following and record any violations found:

- Missing any of: type, title, status, tags
- Missing date field: "created" for all types; "captured" (not "created") for type: discovery
- type not in: effort, discovery, context-primer, spec, adr, source, meeting, daily
- Deprecated type: "project" or "moc"
- status value invalid for the note's type (see the valid status table)
- intensity field missing on type: effort
- Deprecated intensity value: "on" (should be "focus")
- Any deprecated field present: project (as standalone key), scope, technical-level, phase,
  stack, repo, agents, priority, complexity, delegate, assignee
- For type: context-primer — count the words in the note body (excluding frontmatter).
  Flag as "context primer too large: N words" if over 400 words.

Return a JSON list:
[{ "path": "Cards/foo.md", "issues": ["missing: status", "deprecated type: project"] }, ...]

Return an empty list if no violations found. Do not fix anything.
```

---

**Subagent 2 — Orphan scan**

```
Walk every .md file using Glob(pattern="**/*.md"). Skip paths containing ".trash/" or "Calendar/".
For each file:
  - Outbound check: Read the file body and look for [[wikilinks]]. If none found, record as outbound orphan.
  - Inbound check: call brain_backlinks(filepath). If the result is empty, record as inbound orphan.

Return:
{ "no_outbound": ["Cards/foo.md", ...], "no_inbound": ["Cards/bar.md", ...] }

Calendar/daily notes are excluded — they are expected to have no inbound links.
```

---

**Subagent 3 — Broken wikilinks**

```
1. Build a filename index: Glob(pattern="**/*.md") → collect each stem (filename without extension)
   and its full path. Store as a list of { stem, path } pairs.

2. Grep(pattern="\[\[([^\]|#]+)", glob="**/*.md", output_mode="content") to find all wikilink targets.
   Extract the capture group (the target text). Skip targets that start with "http" or contain "#".

3. For each unique target:
   - Normalise: lowercase, replace spaces and underscores with hyphens.
   - Check if the normalised target matches any stem in the index (case-insensitive, hyphens=spaces).
   - If no match found, record as broken.

4. For each broken target, find close candidates in the index:
   - Exact case-insensitive match after normalisation: strong candidate
   - All words present in the stem: weak candidate

Return:
[{ "source": "Cards/foo.md", "broken_target": "Bad Title", "candidates": ["good-title", "good-title-v2"] }, ...]

Return an empty list if no broken targets found.
```

---

**Subagent 4 — Stale drafts**

```
Run brain_query(status="draft"). For each result, call brain_read(filepath) to get the title and created fields.
Return: [{ "path": "...", "title": "...", "created": "YYYY-MM-DD" }]
Sort by created ascending (oldest first).
Return an empty list if no drafts found.
```

---

**Subagent 5 — Trash scan**

```
Glob(pattern=".trash/**/*.md"). For each file found:
- Check for a .origin sidecar: same stem, .origin extension. If present, Read it to get the original path.
  If absent, derive original path by stripping ".trash/" from the path.
- Get the file's modification date using: Bash("stat -f '%Sm' -t '%Y-%m-%d' <path>")

Return: [{ "trash_path": "...", "original_path": "...", "trashed_date": "YYYY-MM-DD" }]
Return an empty list if no trash files found.
```

---

### 2. Present findings and handle repairs

Wait for all five subagents to return, then work through each check in order.

**Check 1 — Frontmatter violations**

Group results by issue type. For each violation, Read the file before proposing a fix:

| Issue | Fix |
|-------|-----|
| Missing `created` | `brain_edit(op=update_frontmatter, frontmatter={"created": "<mtime-date>"})` — no confirmation needed |
| Missing `type`, `title`, `status`, `tags` | Propose value, confirm with user, then `update_frontmatter` |
| `type: project` or `type: moc` | Confirm with user → `update_frontmatter({"type": "effort"})` |
| `intensity: on` | Confirm with user → `update_frontmatter({"intensity": "focus"})` |
| Invalid status for type | Propose correct value, confirm, then `update_frontmatter` |
| Deprecated scalar field | Confirm with user → `brain_edit(op=find_replace, find="^fieldname:.*\n", replace="", regex=true)` |
| Deprecated list field (`stack:`, `agents:`) | Read the full block, confirm with user, use multiline `find_replace` to remove key + indented items |

**Check 2 — Orphans**

Report both lists (no outbound links, no inbound links) with title and path. Flag only — do not delete.

**Check 3 — Broken wikilinks**

For each broken target:
- One candidate → propose fix, confirm, then: `brain_edit(op=find_replace, filepath=<source>, find="[[broken-target]]", replace="[[correct-target]]")`
- Multiple candidates → show options, ask user to pick
- No candidates → flag only, do not create stub notes

Report repairs: "Fixed N broken wikilinks across M files."

**Check 4 — Stale drafts**

Show list oldest-first. For each, ask: **[promote to current]** | **[archive]** | **[skip]**

- Promote: `brain_edit(op=update_frontmatter, frontmatter={"status": "current"})`
- Archive: `brain_edit(op=update_frontmatter, frontmatter={"status": "archived"})`

**Check 5 — Trash**

For each entry, show original path + trashed date and ask: **[restore]** | **[delete]** | **[skip]**

- Restore: `brain_restore(trash_path)`
- Delete: `Bash("rm <trash-path>")` (and `.origin` sidecar if present) — irreversible, confirm per file

---

## Fix vs Flag

| Issue | Action |
|-------|--------|
| Missing `created` (mtime available) | Fix automatically |
| Missing `type`, `title`, `status`, `tags` | Propose + confirm |
| `type: project` or `type: moc` | Propose migration + confirm |
| `intensity: on` on an effort | Propose migration to `focus` + confirm |
| Deprecated field present | Propose removal + confirm |
| Outbound orphan (no links out) | Flag |
| Inbound orphan (no backlinks) | Flag |
| Broken wikilink target | Fix with fuzzy-match (confirm first) |
| Stale draft | Flag — user decides |
| Context primer over 400 words | Flag — suggest trimming or splitting via brain-extract |
| Empty file | Flag — do not delete without confirmation |

## Rules

- Read the file before proposing any fix.
- Always get explicit user confirmation before deleting anything.
- Subagents scan only — all repairs happen in the main conversation.
- Drafts are promoted by the user, not auto-promoted.
