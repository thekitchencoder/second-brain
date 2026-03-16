# Brain Rename + Skills Design

**Date:** 2026-03-16
**Status:** Ready for implementation

---

## Goal

Two related changes:

1. **Rename `vault` → `brain`** throughout the codebase — the project is `second-brain`, not an Obsidian vault. The word "vault" is Obsidian-specific. This rename makes the project stand alone.

2. **Ship four Claude Code skills** in a `skills/` directory that give Claude the ability to use the second-brain tools without any Obsidian-specific knowledge.

---

## Section 1: The Rename

Every occurrence of `vault` in tool names, env vars, mount paths, container names, and MCP server names becomes `brain`.

### Files to rename

| Old | New |
|-----|-----|
| `tools/vault_mcp_server.py` | `tools/brain_mcp_server.py` |
| `tools/vault_index.py` | `tools/brain_index.py` |
| `tools/vault_search.py` | `tools/brain_search.py` |
| `tools/vault-mcp-server` (entrypoint) | `tools/brain-mcp-server` |
| `tools/vault-index` (entrypoint) | `tools/brain-index` |
| `tools/vault-search` (entrypoint) | `tools/brain-search` |
| `tools/vault-init` (entrypoint) | `tools/brain-init` |

### Symbols to rename inside files

| Old | New | Where |
|-----|-----|-------|
| `vault_search` (MCP tool name) | `brain_search` | `brain_mcp_server.py` |
| `vault_query` (MCP tool name) | `brain_query` | `brain_mcp_server.py` |
| `vault_create` (MCP tool name) | `brain_create` | `brain_mcp_server.py` |
| `vault_related` (MCP tool name) | `brain_related` | `brain_mcp_server.py` |
| `handle_vault_search` | `handle_brain_search` | `brain_mcp_server.py` |
| `handle_vault_query` | `handle_brain_query` | `brain_mcp_server.py` |
| `handle_vault_create` | `handle_brain_create` | `brain_mcp_server.py` |
| `handle_vault_related` | `handle_brain_related` | `brain_mcp_server.py` |
| `VAULT_PATH` (env var) | `BRAIN_PATH` | `lib/config.py`, `docker-compose.yml` |
| `VAULT_HOST_PATH` (env var) | `BRAIN_HOST_PATH` | `docker-compose.yml` |
| `vault_path` (Python attr) | `brain_path` | `lib/config.py` |

### Infrastructure changes

| File | Change |
|------|--------|
| `docker-compose.yml` | `container_name: vault` → `brain`; `VAULT_HOST_PATH` → `BRAIN_HOST_PATH`; `VAULT_PATH` → `BRAIN_PATH` |
| `docker-compose.override.yml` | Same env var renames |
| `Dockerfile` | `WORKDIR /vault` → `/brain`; `VAULT_PATH` default if hardcoded |
| `.mcp.json` | Server name `vault` → `brain`; container ref `vault` → `brain`; binary `vault-mcp-server` → `brain-mcp-server` |
| `tests/test_integration.py` | All `/vault` paths → `/brain`; env vars; container name |

### Test fixture changes

All `/vault/...` paths in fixture vault notes and test assertions → `/brain/...`.

---

## Section 2: Skills

### Location

```
skills/
  README.md
  brain-context/SKILL.md
  brain-save/SKILL.md
  brain-project/SKILL.md
  brain-hygiene/SKILL.md
```

### Install

Users copy the skills directory contents to `~/.claude/skills/`:
```bash
cp -r skills/brain-* ~/.claude/skills/
```

Document this in `skills/README.md` and the main `README.md`.

---

### Skill: brain-context

**Trigger:** user mentions a topic, project name, or concept they want to work on.

**Behaviour:**
1. Run `brain_search(query)` with the topic as the query
2. Run `brain_query(tag=<topic-slug>)` if a relevant tag can be inferred
3. Surface results with full frontmatter — type, status, created, tags
4. Flag evidential status: `status: draft` = speculative, `status: current` = established
5. If nothing found, say so explicitly — do not invent context
6. Do not re-derive or re-explain concepts that exist in the brain; use what's there

**Does not:** load everything at session start, search without a concrete topic, or treat empty results as a failure.

---

### Skill: brain-save

**Trigger:** user says "remember", "save", "capture", "note down", or asks Claude to record something for future sessions.

**Behaviour:**
1. Run `brain_search` to check if a note on this topic already exists — offer to update rather than duplicate
2. Scan the top-level folder structure with Glob to infer vault conventions and suggest an appropriate location
3. Create via `brain_create(template, title)` in the agreed location
4. Write frontmatter with exactly these fields (no others invented):
   ```yaml
   type:     # infer from content, ask if unclear
   title:    # human-readable, descriptive
   status:   # draft | current | archived
   created:  # today YYYY-MM-DD
   tags:     # array, lowercase, hyphenated
   ```
5. Body: exactly what was asked to be saved, nothing more
6. Add wikilinks to related notes found in step 1

**Does not:** prescribe folder structure (inferred from vault), invent frontmatter fields, or elaborate raw captures.

---

### Skill: brain-project

**Trigger:** user says "start a new project", "set up a project", or asks to scaffold new work.

**Behaviour:**
1. Ask for a project name if not given — derive a kebab-case slug
2. Scan vault structure with Glob to find where projects live and what existing projects contain — follow the pattern
3. Create two notes via `brain_create`:
   - **Context primer** (`type: context-primer`) — problem statement, goals, key decisions, related work from `brain_search`
   - **Project/effort note** — current phase, active work, links to context primer
4. Tag both with the project slug so `brain_query(tag=<slug>)` returns the full thread
5. Link both to each other with wikilinks
6. Report what was created and how to query: `brain_query(tag=<slug>)`

**Does not:** create more than two documents without being asked, invent folder structure that doesn't match existing patterns, or populate notes with invented content.

---

### Skill: brain-hygiene

**Trigger:** user asks to tidy, audit, or health-check the second-brain.

**Four checks in order:**

**1. Frontmatter completeness**
Glob all `.md` files excluding templates. Read each, flag any missing `type`, `title`, `status`, `created`, or `tags`. Fix unambiguous cases (e.g. `created` from file mtime). Ask before fixing anything ambiguous.

**2. Orphaned notes**
Grep for files with no outbound `[[wikilinks]]`. Cross-reference against files with no inbound links. Flag both — report with title and path. Do not delete.

**3. Broken wikilink targets**
Build filename index via Glob. Grep for all `[[target]]` patterns. Flag any target not in the index. Do not create stub documents.

**4. Stale drafts**
`brain_query(status=draft)` to surface notes still in draft. Report with `created` date for user to decide: promote, archive, or delete.

**Fix vs flag:**
- Fix: missing `created` (infer from mtime), unambiguous frontmatter gaps
- Flag everything else: orphans, broken links, stale drafts, ambiguous types

**Does not:** prescribe valid types, auto-promote notes, auto-delete anything.

---

## Dependency Note

The rename must be completed before the skills are written — the skills reference `brain_search`, `brain_query` etc. by name. Wrong order = skills that reference non-existent tools.
