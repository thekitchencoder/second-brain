---
name: brain-create-effort
description: Use when the user wants to create a new effort, set up an effort for a topic, or says "new effort for X", "create an effort on X", "start an effort around X". Distinct from brain-project which is for software projects with full scaffolding.
---

# Brain Create Effort

Scaffold a new effort note with correct frontmatter, intensity state, and optional context primer.

## MCP-Only Skill

Uses MCP tools only. The vault lives inside a Docker container — filesystem tools (Glob, Grep, Read, Edit) will search the host filesystem, not the vault.

## Flow

### 1. Get details

If the user hasn't provided them, ask:
- Effort name (human-readable title)
- One-line goal statement

Derive a kebab-case slug from the name (e.g. `Co-dependent Confabulation` → `co-dependent-confabulation`).

### 2. Check for duplicates

Run `brain_search(query=<slug>)` — always check for duplicates before creating. If a strong match is returned at `Efforts/<slug>.md`, the effort already exists — surface it and ask: "An effort matching this already exists — do you want to update it instead?"

Only proceed to step 3 if the search returns no exact match at the expected path.

### 3. Create the effort note

Run `brain_create(template="effort", title="<Effort Name>", directory="Efforts/")`. Note the returned filepath exactly — it will be `Efforts/<slug>.md`.

Populate using `brain_edit`, not `brain_write`:

```
brain_edit(op=update_frontmatter, filepath=<filepath>, frontmatter={
  title: "<Effort Name>",
  intensity: "focus",
  tags: ["effort", "<slug>"]
})

brain_edit(op=replace_section, filepath=<filepath>, heading="Goal", body="<one-line goal statement>")
```

If the user provided initial work items:
```
brain_edit(op=replace_section, filepath=<filepath>, heading="Active Work", body="<items, one per line>")
```

### 4. Offer a context primer

Ask: "Want a context primer in `Efforts/<slug>/` for background and key decisions?"

If yes:
1. Run `brain_create(template="context-primer", title="<Effort Name> — Context", directory="Efforts/<slug>/")`. Note the filepath.
2. Populate with `brain_edit`:
   ```
   brain_edit(op=update_frontmatter, filepath=<primer filepath>, frontmatter={
     title: "<Effort Name> — Context",
     tags: ["context", "<slug>"]
   })
   brain_edit(op=replace_section, filepath=<primer filepath>, heading="Purpose of This Document", body="<goal and scope>")
   ```
3. Link the two notes:
   ```
   brain_edit(op=insert_wikilink, filepath=<effort filepath>, target="<Effort Name> — Context", context_heading="Notes")
   brain_edit(op=insert_wikilink, filepath=<primer filepath>, target="<Effort Name>", context_heading="Key Details")
   ```

### 5. Report

```
Created: Efforts/<slug>.md
  Goal: <goal>
  Intensity: on
  Query later: brain_query(tag="<slug>")
```

## Rules

- Use `brain_edit` after `brain_create`, not `brain_write` — preserves template frontmatter.
- Always check for duplicates — run `brain_search` and check results for an exact path match at `Efforts/<slug>.md`.
- `intensity: focus` is always set on creation — this is the default active state.
- Effort note at `Efforts/<slug>.md` — never inside a subfolder.
- Context primer at `Efforts/<slug>/` — always in the subfolder, never at root.

## Baseline Failures This Skill Addresses

Without this skill, agents either:
- Fall through to direct `brain_create` calls without checking for duplicates
- Use `brain_write` after `brain_create`, clobbering template frontmatter
- Use `brain-project` (wrong tool — creates project structure, not an effort)
- Ask clarifying questions instead of acting

## Common Mistakes

| Mistake | Fix |
|---|---|
| Using `brain-project` for a plain effort | Use this skill — brain-project is for software projects with dev repos |
| Calling `brain_write` after `brain_create` | Use `brain_edit(op=replace_section)` and `update_frontmatter` |
| Skipping the duplicate check | Always run `brain_search`; check results for exact path match |
| Not setting `intensity: focus` | Set it in `update_frontmatter` — it won't be in the template yet for existing vaults |
