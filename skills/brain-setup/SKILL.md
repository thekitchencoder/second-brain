---
name: brain-setup
description: Use when the user wants to set up their brain vault for the first time, or says "set up my brain", "initialise my vault", "help me get started". Guides a structured onboarding session to create the first effort, context-primer, and initial notes.
---

# Brain Setup

Guided first-time vault setup. Ask the right questions, then use MCP tools to build the initial structure.

## MCP-Only Skill

Uses MCP tools only. The vault lives inside a Docker container — filesystem tools (Glob, Grep, Read, Edit) will search the host filesystem, not the vault.

## Pre-flight check

Call `brain_templates` first. If it errors, stop and tell the user:

> "It looks like `brain-init` hasn't been run yet. Please run it inside the container first, then come back."

## Vault structure

The vault uses an ACE-aligned hierarchy. `brain-init` creates these folders — do not recreate them. If any are missing, use `brain_write` to create a placeholder `.keep` file.

| Folder | Purpose |
|---|---|
| `Atlas/` | Config, dashboards, stable reference notes (`status: current`) |
| `Efforts/` | All active work: projects, areas, ongoing focus |
| `Cards/` | Atomic notes, flat, no hierarchy — stable cards use `status: current` |
| `Calendar/` | Daily notes and time-anchored content |
| `Sources/` | Books, articles, reference material |

Do not create any other top-level folders. If the user describes something that doesn't fit, ask which of these it belongs to before proceeding.

## Templates

Always use `brain_create` with these templates — never `brain_write` a new note from scratch.

| Template | Use for | Key frontmatter |
|---|---|---|
| `effort` | Any project or ongoing area of work | `parents` (empty list if top-level) |
| `context-primer` | Background docs for Claude sessions | universal fields only |
| `discovery` | Raw idea — inbox item | `effort` (optional at capture) |
| `spec` | Feature specification | `effort` |
| `adr` | Architecture decision record | `effort`, `id` (ADR-001…) |
| `meeting` | Meeting notes | `attendees`, `effort` |
| `daily` | Daily note | no extras |
| `doc` | Authored deliverable (RFC, design doc) | `effort` |

## Setup sequence

Work through in order.

### Step 1 — Understand the user's context

Ask these three questions (can be in one message):

1. What kind of work do you primarily use this for? (software projects, research, personal knowledge, all of the above)
2. Do you have any existing notes to migrate, or is this a fresh start?
3. What is the first active effort or project you want to track?

### Step 2 — Create the first Effort

An Effort is a single flat file at `Efforts/<slug>.md`. Supporting notes live in `Efforts/<slug>/` subfolders.

- Ask for the effort name and a one-line goal
- Call `brain_create(template="effort", title=<name>, directory="Efforts/")`
- Note the returned filepath
- Populate with `brain_edit(op=update_frontmatter, ...)` for the goal and any parent efforts
- Populate the Goal section: `brain_edit(op=replace_section, filepath=<filepath>, heading="Goal", body=<goal>)`

### Step 3 — Create a context-primer for the effort

Every effort needs a context-primer so future Claude sessions don't start cold.

- Call `brain_create(template="context-primer", title="Context: <effort name>", directory="Efforts/<slug>/")`
- Ask: what should a Claude session know before working on this effort?
- Populate: purpose, background, key decisions already made, open questions
- Use `brain_edit(op=replace_section, ...)` for each section — do not overwrite the whole file

### Step 4 — Capture immediate discoveries

If the user has ideas, todos, or half-formed thoughts:

- Call `brain_create(template="discovery", ...)` in `Efforts/<slug>/` or `Cards/`
- Set `status: raw` via `brain_edit(op=update_frontmatter, ...)` — always raw at capture
- One note per idea

### Step 5 — Link to a dev project (if applicable)

If the effort has a linked software repository:

- Ask: what is the hostname of this machine and where does the repo live?
- Add a `dev:` map to the effort note frontmatter:
  ```yaml
  dev:
    hostname.local: ~/projects/my-project
  ```
- Use `brain_edit(op=update_frontmatter, filepath=Efforts/<slug>.md, frontmatter={dev: {<hostname>: <path>}})`
- Ask whether to create an initial spec for the first feature

### Step 6 — Confirm and summarise

- Call `brain_search` with a broad query to confirm notes are discoverable
- List what was created with file paths
- Remind the user: the background indexer will pick up new notes automatically, but they can run `brain-index run` inside the container to index immediately

## Frontmatter rules

- `status: raw` on discovery notes — never set it to anything else during setup
- `status: draft` on doc notes at creation
- `doc` notes live in `Efforts/<slug>/docs/` — numeric prefixes (`01-`, `02-`) preserve order
- `tags`: lowercase, hyphenated (`vault-tooling`, `local-llm`)
- `created` is filled automatically by `brain_create` — do not set it manually
- Wikilinks: `[[Note Title]]` — stub them even if the target doesn't exist yet
- Filenames: lowercase, hyphenated (`context-my-project.md`)

## Rules

- **No folder invention.** Only: Atlas, Efforts, Cards, Calendar, Sources
- **No notes without frontmatter.**
- Use `brain_edit` after `brain_create`, not `brain_write` — preserves template frontmatter.
- **No placeholder content.** If a section has nothing to say yet, leave the heading and move on.
- Infer what you can (created date, file naming) rather than asking.
