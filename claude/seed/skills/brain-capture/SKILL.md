---
name: brain-capture
description: Use when the user mentions a topic, idea, project, meeting, or anything they want to capture in their brain. Triggers on "I've had an idea", "I was thinking about", "we had a meeting", "I want to spec out", or any new thing to record.
---

# Brain Capture

Conversational idea capture with inline wiring after the user finishes editing.

## Path Translation

MCP tools return `/brain/X` paths. Strip the `/brain` prefix to get the working path:
`/brain/Cards/foo.md` → `Cards/foo.md`

## Flow

### 1. Search first

Run `brain_search(topic)` before creating anything.

- **Strong match** → read it, surface it, offer to update rather than duplicate
- **Weak matches** → note filepaths for the wiring step

### 2. Converse

Extract the idea through dialogue — one question at a time.

Infer note type from what the user says:

| What they say | Template |
|---|---|
| Vague idea / half-formed thought | `discovery` |
| "We had a meeting / talked to X" | `meeting` |
| "I want to build / spec out X" | `spec` |
| Ongoing area of focus | `effort` |

Only ask about type if genuinely ambiguous.

### 3. Create

Call `brain_create(template, title, directory)`. Infer directory from context:

- Known effort → `Efforts/<slug>/`
- Atomic idea or unclear → `Cards/`

Then `brain_write(filepath, content)` with the captured content.

Tell the user: "Draft at `Efforts/jobs-guarantee/automation-idea.md` — let me know when you've finished editing."

### 4. Wait

Do not proceed until the user signals they are done editing.

### 5. Wire

After the user confirms done:

1. Run `brain_search(title)` and `brain_related(filepath)` in parallel
2. For each strong match: `brain_edit(op=insert_wikilink, filepath=<new note>, target=<match title>, context_heading="Related Notes")` — idempotent, safe to call without pre-checking
3. If the note has a non-empty `effort:` field value: `brain_edit(op=insert_wikilink, filepath=Efforts/<slug>.md, target=<note title>, context_heading="Notes")`
4. Report: "Linked to 3 notes, added reference to `Efforts/jobs-guarantee.md`"

## Rules

- **No folder invention.** Only: Atlas, Efforts, Cards, Calendar, Sources
- **Search before creating.** Duplicates are worse than updates.
- **Write only what was captured.** No elaboration, no invented content.
- **`status: raw` on discovery notes** — never set it to anything else during capture.
- **One note per idea.**

## Common Mistakes

| Mistake | Fix |
|---|---|
| Creating without searching first | Always run `brain_search` before `brain_create` |
| Placing notes in the brain root | Always pass a `directory` to `brain_create` |
| Wiring before the user is done | Wait for explicit confirmation before step 5 |
| Wiring to a non-existent effort note | Glob for `Efforts/<slug>.md` before patching |
