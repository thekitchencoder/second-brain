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
Atlas/        — Maps of content, MOCs, evergreen reference notes
Efforts/      — Active ongoing work (non-project things you keep returning to)
Projects/     — Discrete software projects, each with its own subfolder
Cards/        — Atomic evergreen notes, flat, no hierarchy
Calendar/     — Daily notes and time-anchored content
Sources/      — Books, articles, reference material
```

Do not create any other top-level folders. If the user describes something that doesn't fit, ask which of these it belongs to before proceeding.

## Templates

The following templates are available via `brain_create`. Always call `brain_templates` first to confirm the exact names.

| Template | Use for | Key frontmatter to fill |
|---|---|---|
| `discovery` | Capturing a raw idea — the inbox | `effort`, `project` (optional at capture) |
| `context-primer` | Background docs for Claude sessions | `project`, `scope`, `technical-level` |
| `effort` | An ongoing area of work (creates an `_index.md`) | `scope`, `tags` |
| `project` | A discrete software project manifest | `id`, `stack`, `repo`, `effort` |
| `spec` | A feature specification | `project`, `priority`, `complexity`, `delegate` |
| `adr` | An architecture decision record | `project`, `id` (sequential: ADR-001) |
| `meeting` | Meeting notes | `attendees`, `project` |
| `daily` | Daily note | no extras needed |

## Setup sequence

Work through this in order. Do not skip steps.

### Step 1 — Understand the user's context

Ask:
1. What kind of work do you primarily use this for? (software projects, research, personal knowledge, all of the above)
2. Do you have any existing notes to migrate, or is this a fresh start?
3. What is the first active effort or project you want to track?

### Step 2 — Create the first Effort

An Effort is an ongoing area of focus that isn't a discrete project. It gets its own subfolder under `Efforts/` with an `_index.md` as its home.

- Ask for the effort name and a one-line goal
- Use `brain_create` with the `effort` template, placing it in `Efforts/<effort-slug>/`
- Populate with the name, goal, and any active work the user names

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

### Step 5 — Set up a project (if applicable)

If the user has a discrete software project:
- Use `brain_create` with the `project` template in `Projects/<project-slug>/`
- Ask for: project name, stack, repo URL, which effort it belongs to
- The `id` field should be a stable lowercase hyphenated slug matching the folder name
- Ask whether to create an initial spec for the first feature

### Step 6 — Confirm and summarise

When done:
- Call `brain_search` with a broad query to confirm notes are discoverable
- List what was created with file paths
- Remind the user to run `brain-index run` inside the container to index everything for semantic search

## Frontmatter rules

- `status` on discovery notes is always `raw` at creation — never set it to anything else during setup
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
