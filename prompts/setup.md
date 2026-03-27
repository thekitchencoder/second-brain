# Brain Setup Prompt

Paste this prompt into a Claude session to guide first-time setup of a second-brain vault.

---

You are helping me set up a structured second-brain vault for use with the `second-brain` Docker container. This is a one-time setup session. Your job is to ask me the right questions, then use the brain MCP tools to create the initial structure.

## What you are setting up

The vault is a folder of markdown files with YAML frontmatter. It has two layers:

- **Layer 1 — Generic RAG**: any markdown folder works. `brain_search`, `brain_read`, `brain_write`, `brain_related` work immediately.
- **Layer 2 — Structured management**: requires `brain-init` to have been run. Adds `brain_query`, `brain_create`, `brain_templates`.

Assume `brain-init` has already been run. If `brain_templates` returns an error, stop and ask the user to run `brain-init` inside the container first.

## Folder structure

The vault uses an ACE-aligned hierarchy. Create these top-level folders if they don't exist (use `brain_write` to create a placeholder `.keep` file in each if needed):

```
Atlas/        — Config, dashboards, evergreen reference notes
Efforts/      — All active work: projects, areas, ongoing focus
Cards/        — Atomic evergreen notes, flat, no hierarchy
Calendar/     — Daily notes and time-anchored content
Sources/      — Books, articles, reference material
```

Do not create any other top-level folders. If the user describes something that doesn't fit, ask which of these it belongs to before proceeding.

## Templates

The following templates are available via `brain_create`. Always call `brain_templates` first to confirm the exact names.

| Template | Use for | Key frontmatter to fill |
|---|---|---|
| `discovery` | Capturing a raw idea — the inbox | `effort` (optional at capture) |
| `context-primer` | Background docs for Claude sessions | no extras beyond universal fields |
| `doc` | Authored deliverable — architecture doc, RFC, design doc | `effort`; optional `published_url` when pushed externally |
| `effort` | Any project or ongoing area of work | `parents` (empty list if top-level) |
| `spec` | A feature specification | `effort` |
| `adr` | An architecture decision record | `effort`, `id` (sequential: ADR-001) |
| `meeting` | Meeting notes | `attendees`, `effort` |
| `daily` | Daily note | no extras needed |

## Setup sequence

Work through this in order. Do not skip steps.

### Step 1 — Understand the user's context

Ask:
1. What kind of work do you primarily use this for? (software projects, research, personal knowledge, all of the above)
2. Do you have any existing notes to migrate, or is this a fresh start?
3. What is the first active effort or project you want to track?

### Step 2 — Create the first Effort

An Effort covers any active area of work — a software project, an ongoing focus, or a personal initiative. It is a single flat file at `Efforts/<slug>.md`. Supporting notes (context-primers, specs, discoveries) live in `Efforts/<slug>/` subfolders.

- Ask for the effort name and a one-line goal
- Use `brain_create` with the `effort` template, placing it in `Efforts/` (not a subfolder — the file itself is `Efforts/<slug>.md`)
- Populate with the name, goal, and any active work the user names
- If this effort is part of a broader area, set `parents: [<parent-slug>]`; otherwise leave `parents: []`

### Step 3 — Create a context-primer for the effort

Every effort should have at least one context primer so future Claude sessions don't start cold.

- Use `brain_create` with the `context-primer` template in the same `Efforts/<effort-slug>/` directory
- Ask: what should a Claude session know before working on this effort?
- Populate: purpose, background, key decisions already made, open questions

### Step 4 — Capture any immediate discoveries

If the user has ideas, todos, or half-formed thoughts they want to capture:
- Use `brain_create` with the `discovery` template in `Efforts/<effort-slug>/` or the vault root
- Set `status: raw` — these are inbox items, not finished notes
- One note per idea

### Step 5 — Link to a dev project (if applicable)

If the effort has a linked software repository on this machine:
- Add a `dev:` map to the effort note frontmatter with the hostname and absolute path:
  ```yaml
  dev:
    Chriss-MacBook-Air.local: ~/projects/my-project
  ```
- Ask: what is the hostname of this machine and where does the repo live?
- Ask whether to create an initial spec for the first feature

### Step 6 — Confirm and summarise

When done:
- Call `brain_search` with a broad query to confirm notes are discoverable
- List what was created with file paths
- Remind the user to run `brain-index run` inside the container to index everything for semantic search

## Frontmatter rules

- `status` on discovery notes is always `raw` at creation — never set it to anything else during setup
- `status` on `doc` notes follows a publication lifecycle: `draft → review → published → archived`. Use `draft` at creation.
- `doc` notes live in `Efforts/<slug>/docs/` — numeric filename prefixes (`01-`, `02-`) preserve reading order within a set
- `tags` are lowercase, hyphenated, no spaces: `vault-tooling`, `local-llm`
- `created` is today's date in `YYYY-MM-DD` format — the template fills this automatically via `brain_create`
- Wikilinks use `[[Note Title]]` syntax — stub them even if the target doesn't exist yet
- File names are lowercase, hyphenated: `context-my-project.md`

## What not to do

- Do not invent top-level folders
- Do not create notes without frontmatter
- Do not set `status: processed` or `status: promoted` on discovery notes — that is the triage pipeline's job
- Do not ask for information you can infer (e.g. `created` date, file naming)
- Do not create placeholder content — if a section has nothing to say yet, leave the heading and move on
