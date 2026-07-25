# Brain Profile Seam — implementation spec

Date: 2026-07-24
Status: approved design, ready for implementation planning
Supersedes the design sketch in `docs/brain-profile-seam.md`; incorporates
`docs/mcp-oauth-brief.md` as the auth half (Seam 6).

## Purpose

Run one second-brain engine over many brains — work (ACE), home (ACE, Obsidian-tuned),
Fiction (private fiction) — by extracting everything brain-specific into a **profile**.
The engine image becomes pure infrastructure; a profile is the implementation. Fiction
is the forcing function: it needs the profile loader **and** the generic query to be
usable; auth/RBAC follow.

## Core principle

**The image is infrastructure. The profile is the implementation.**

The engine ships Python tools, servers, entrypoint/setup, `hooks/run-hook.cmd`, `.vscode/`,
and `claude/seed/` (the container's own Claude config). It knows nothing about ACE, efforts,
or Fiction. Everything brain-shaped lives in a profile directory the engine reads at
`<brain>/.brain/`.

This is a **breaking change**, accepted deliberately: nothing profile-shaped remains baked
into the image — not even `ace`.

## Scope of this spec

Phase numbers below refer to the PR-sized phases in "Implementation phasing".

- **Build now (phases 1–2):** profile loader + the `ace` profile extraction (Seams 1–4) and
  the generic query (Seam 5). These two together make Fiction usable.
- **Designed here, built later (phases 3–4):** auth gate + visibility/RBAC (Seams 6–7).
  Designed now only so the manifest schema does not have to break to accommodate them.
  Default `mode = "none"` keeps them inert.

The full architecture is walked end-to-end below so the build-now decisions are correct under
what later phases demand. Anything marked *phase 3*, *phase 4*, or *deferred* is not built now.

---

## The profile

A profile is a plain directory the engine reads. The engine never shells out to git — its
contract is the directory, so every consumer stays testable against a fixture.

```
<brain>/.brain/
  profile.toml            # folders, fields, skills, plugin identity, vocabulary, zk, auth
  templates/*.md          # frontmatter templates
  skills/global/*         # MCP-only skills (the plugin)
  skills/vault/*          # filesystem skills (mv, Glob, Edit)
  zk-config.toml          # convention-only zk fragment (see "zk config" below)
  hooks/session-start.sh  # profile-flavoured session priming
  claude/vault-claude.md  # vault-level CLAUDE.md
  prompts/setup.md        # setup conventions
```

### The three launch profiles

| Profile repo                          | Role  | Notes |
|---------------------------------------|-------|-------|
| `second-brain-profile-ace`            | work  | Today's content extracted verbatim. The extraction baseline / correctness proof. Public. Default profile URL baked into the image as a *pointer*. |
| `second-brain-profile-ace-obsidian`   | home  | Own repo, **forked from `ace` and customised** (Obsidian-tuned skills). Public. |
| `fiction-profile`                  | fiction | Private. Local/private repo. Drives the design (folders `codex/canon/characters/memory`; fields `layer`/`known_by`/`never_tell`; RBAC). |

Creating these repos — and extracting current image content into `ace` — is **part of
shipping phase 1**, not a follow-up: the engine cannot boot without at least the `ace` repo
existing at the default URL.

---

## Distribution — git for delivery, off the boot path

- **Nothing profile-shaped is baked into the image.** The image ships **one pointer**: a
  default profile repo URL (config default `BRAIN_PROFILE_REPO` → the public
  `second-brain-profile-ace` repo). The URL, not the files.
- **First init clones** the profile into `<brain>/.brain/`. `ace` from the default URL with
  zero config; a custom profile via `brain-init --profile-repo <source>`.
- **`--profile-repo <source>` accepts a local path or a git URL.** Resolution: if the source
  exists on disk, treat it as a local path; otherwise treat it as a git URL. Local paths mean
  private profiles need **no secret in the container** (clone/mount on the host, point at the
  directory), and tests run against a local fixture repo with zero network. `git clone`
  handles a local path natively.
- **Every subsequent start is offline.** `.brain/` lives in the user's volume; the engine
  reads the directory, finds it populated, never touches git. A GitHub outage cannot stop an
  already-initialised brain.
- **Updates are explicit** — `brain-profile update` pulls when the user chooses, with a human
  present to resolve conflicts. **Never** an auto-pull at boot.
- A profile records its own origin in `profile.toml` (`[origin] repo/ref`) so `update` needs
  no re-typing.
- **`.brain/.git` must be excluded** from Obsidian sync and any brain-level git, alongside the
  existing `.ai/` and `.zk/` exclusions.
- **Deferred (YAGNI):** a known-profiles registry (name → URL). One `--profile-repo <source>`
  covers all three launch profiles.

---

## Seam 1 — Config loader (`tools/lib/config.py`)

`Config.load_profile()` is the **single source of truth**. It reads
`<brain>/.brain/profile.toml` with stdlib `tomllib` (no new dependency) and exposes
`.folders`, `.fields`, `.skills`, `.plugin`, `.vocabulary`, `.zk`, `.auth`. Everything
downstream reads the profile through `Config`; no other module re-parses the manifest.

Add `self.profile_dir = os.path.join(self.brain_path, ".brain")`.

**Effort: small.**

### Manifest schema (`profile.toml`)

```toml
name = "ace"

[origin]                       # written at init from --profile-repo; used by `brain-profile update`
repo = "https://github.com/kitchencoder/second-brain-profile-ace.git"
ref  = "main"

[plugin]
name   = "second-brain"        # plugin identity AND MCP server name
author = "kitchencoder"
marker = "brain"               # the CLAUDE.md <!-- brain --> hook marker

folders = ["Atlas", "Efforts", "Cards", "Calendar", "Sources"]

# Promoted query filters (Seam 5). `label` and `query_desc` are split by design:
#   label      — DEFINITIONAL: what the field means. Stable; docs, _no_match_hint.
#   query_desc — LLM-FACING: injected into the generated tool schema to steer tool selection.
#                Optional; falls back to `label` when absent.
[fields.status]
kind  = "scalar"
label = "Note status"
[fields.type]
kind  = "scalar"
label = "Note type"
[fields.intensity]
kind       = "scalar"
label      = "Effort intensity"
query_desc = "Filter by intensity: focus, ongoing, simmering"
[fields.effort]
kind  = "scalar"
label = "Effort"

[skills]
# ace ships 11 global skills (fixes today's brain-distil drop) + 5 vault skills.
global = ["brain-capture", "brain-connect", "brain-context", "brain-create-effort",
          "brain-distil", "brain-effort", "brain-project", "brain-save", "brain-setup",
          "brain-surface", "brain-triage"]
vault  = ["brain-daily", "brain-extract", "brain-hygiene", "brain-rename", "brain-reorganise"]

[zk]                           # convention-only; NO container paths (see "zk config")
filename = "{{slug title}}"
default_template = "default.md"
author = "Chris"
recents_filter = "--sort created- --created-after '2 weeks ago'"

[auth]                         # phase 3; default keeps everything inert
mode = "none"                  # none | oauth
```

The Fiction manifest is the same shape with `folders = ["codex","canon","characters",
"memory"]`, `[fields]` including `layer` (scalar) and `known_by`/`never_tell`
(`kind = "list", visibility = true`), `plugin.name = "fiction"`, `plugin.marker =
"fiction"`, its own skill set, and `[auth] mode = "oauth"` with an `[auth.rbac]` block.

### Init-time validation (fail loud, not at first use)

At `brain-init`, refuse with a clear message if any hold:
- `zk.default_template` names a template not shipped under `templates/`.
- any declared skill does not resolve under `skills/`.
- `folders` is empty.
- **Collision:** another installed profile already claims this `plugin.name`, MCP server
  name, or `marker`.

## Seam 2 — Folders (`tools/brain-init`)

`ACE_FOLDERS` (line 70) → `cfg.profile.folders`. Rename `init_ace_folders` (507) →
`init_profile_folders`. Nothing in the engine references folder names (`_walk_brain_files`
is name-agnostic). **Effort: trivial.**

## Seam 3 — Templates (`tools/brain-init`, `tools/lib/brain.py`)

Source templates from `<brain>/.brain/templates/` instead of the fixed `zk/` tree. Runtime
discovery already works (`_list_template_names`, `brain.py:310`; no hardcoded template
filenames). `init_core` composes `<brain>/.zk/templates/` from the profile. **Effort:
trivial.**

## Seam 4 — Skills, plugin identity, vocabulary (`tools/brain-init`)

The two name-sets `_VAULT_SKILL_NAMES` / `_GLOBAL_SKILL_NAMES` (59–68) and the plugin /
marketplace / `.mcp.json` identity in `stage_brain_plugin` (400–504) come from
`profile.skills` and `profile.plugin`. Skill *source* resolves under `<brain>/.brain/skills/`.
The plugin machinery is reused verbatim — only names are parametrised. Fixes the `brain-distil`
drop as a side effect. **Effort: small.**

**Multi-brain disambiguation — profile owns its vocabulary, engine validates.** Each profile
picks a distinct plugin name, MCP server name, skill names, trigger prose, and `CLAUDE.md`
marker (Fiction ships `fenn-capture` — "use when capturing Fiction fiction, canon or
characters" — not a second `brain-capture`). Namespacing (`second-brain:brain-capture` vs
`fiction:fenn-capture`; `mcp__<server>__…`) prevents crashes; distinct trigger prose
prevents the *wrong brain answering the same utterance*. The engine's only job is the
init-time collision check above. (Skill-content authoring for Fiction lives in its private
profile, not upstream; mind the exfiltration-language guardrail — frame `known_by`/`never_tell`
as in-world knowledge boundaries.)

## zk config — split convention from infrastructure

`zk/config.toml` mixes profile conventions with container infrastructure and must not move
wholesale (a distributed profile would bake in the `/brain` container mount path from
`[tool].fzf-preview`).

- **Profile owns convention keys** — shipped as `zk-config.toml` / the `[zk]` manifest block:
  `[note].filename`, `default_template`, `[extra].author`, `[filter].recents`.
- **Engine owns container-shaped keys** — `[tool]` (pager, `fzf-preview` with `/brain`), and
  the structural `[notebook].exclude`.
- **Compose at init:** live `<brain>/.zk/config.toml` = **deep merge, profile over infra**
  (profile wins on any collision — normal base-defaults-then-override layering; a profile may
  override `fzf-preview` or the pager if it means to).
- **One structural guarantee:** after the merge, the engine **unions `templates/` back into
  `[notebook].exclude`** unconditionally. This single key is structural, not stylistic —
  dropping it would make zk index template files as real notes and pollute search. It is the
  only exception to profile-wins.

`.zk/` remains zk's engine-managed runtime dir (holds the index).

## Seam 5 — Generic query (`tools/lib/brain.py`, `tools/brain_mcp_server.py`, `tools/brain_api.py`)

The `if`-ladder in `handle_brain_query` (`brain.py:163–247`) becomes a loop over
`profile.fields`:

- `kind = "scalar"` → equality (`meta.get(field) == value`).
- `kind = "list"` → membership (`value in meta.get(field, [])`), so `known_by = "fenn"` and
  `tags = "x"` filter uniformly.
- `status = "unset"` semantics (field missing) generalise to any promoted field.
- **Two engine primitives stay special-cased**, not profile fields: `tag` (delegated to
  `zk list --tag`) and `created_after/before` (date range).

**Generic `where` escape hatch:** `where: {field: value}` filters on *any* frontmatter key,
promoted or not, using the same scalar/membership rules. Keeps the manifest to only the fields
worth advertising; future-proofs new keys without code changes.

**Schema generation** — MCP `brain_query.inputSchema` (`brain_mcp_server.py:52`) and REST
`list_notes` params (`brain_api.py:209`) are **built from `profile.fields` at server
startup**: one property per field, description = `query_desc ?? label`, plus the stable `tag`
/ `created_*` / `where`. The tool-level `brain_query` description is **assembled from the
field labels** (not a hardcoded string) so it cannot drift out of sync with the field set.
`_no_match_hint.field_map` (`brain.py:154`) derives from `profile.fields`.

**Left alone deliberately:** the `db.py` chunks columns (`title,type,status,created,tags,
scope` — written, never filtered on). See "Server-side semantic filtering" below.

**Effort: medium** — the one seam with real signature churn, bounded to these four call sites.
`intensity`/`effort` stop being engine concepts and become two rows in the `ace` manifest.

### Server-side semantic filtering — deferred, with a defined trigger

Generalising the `chunks` columns into live filters on the vector query is **not built now**.
The trigger that promotes it: **enforced visibility (Seam 7 v2) on a selective field.**
Rationale — post-filtering top-K in Python is both a *correctness* problem (a rare filtered
attribute, or a spoiler chunk, can push all valid matches out of the returned top-K) and,
for a security boundary, wrong placement (forbidden chunks must not leave the DB for that
caller). Design it **alongside Seam 7 v2**, not before. Caveat for when it lands: sqlite-vec's
KNN-plus-`WHERE` interaction has real constraints (partition or filter-then-rank, not a naive
`WHERE`), so this is a genuine design task.

## Seam 6 — Auth gate (phase 3; designed now)

Gated on `profile.auth.mode`. **`mode = "none"` is a no-op — zero change to any existing code
path.** This is work and today's ACE, and it is the property that keeps phase 1 a clean
additive PR.

`mode = "oauth"` → **native `authlib` in `brain_api`** (already FastAPI): OAuth 2.1 + PKCE
endpoints (`/authorize`, `/token`, optional `/register` for DCR), a `require_token` FastAPI
dependency on protected routes, and for MCP an ASGI wrapper that returns `401` with
`WWW-Authenticate: Bearer resource_metadata="…"` and serves
`/.well-known/oauth-protected-resource` (RFC 9728) plus `/.well-known/oauth-authorization-server`
(RFC 8414, for older clients). PKCE S256 mandatory; validate `aud` = server URI; bind token
via `resource=` (RFC 8707). One process, one image — fits the `docker run` distribution model.
(Native chosen over an `mcp-oauth-proxy` sidecar to avoid reintroducing a multi-container
shape and two-layer token refresh.)

**Cloudflare arrangement** (from the OAuth brief): remove Access from the MCP hostname (Access
would intercept OAuth redirects); keep the tunnel for TLS/transport only. Interim before OAuth
ships: Access **service tokens** work non-interactively for Claude Code/Desktop, not for
web/mobile connectors.

**Policy/secret split — load-bearing for a git-distributed profile:**
- **Profile declares policy** — `auth.mode`, `[auth.rbac]` `roles`, `identities`
  (OAuth sub / email → role), `default_role`. Fiction's map lives in its **private** repo.
- **Deployment provides secrets** — `BRAIN_AUTH_ISSUER`, `BRAIN_AUTH_AUDIENCE`,
  `BRAIN_AUTH_JWKS_URL`, client secret — via env, read only when `mode = "oauth"`.
- **No secret ever enters a profile repo.**

**Effort: medium**, cleanly additive.

## Seam 7 — Visibility / RBAC (phase 3; designed now)

Where auth (who is calling) meets Fiction's `known_by`/`never_tell` (what may be surfaced).

- **v1 (zero engine code):** `known_by`/`never_tell` are just `visibility = true` list fields,
  indexed via Seam 5. The Fiction **skill prose** instructs the model to withhold.
  **Explicitly advisory — single trusted operator only; not a boundary a second human can be
  trusted against.** Ships in the private profile.
- **v2 (medium, isolated):** a `visible(meta, caller) -> bool` predicate derived from
  `auth.rbac` + the `visibility` fields, applied at the two retrieval sites — consumers of
  `_walk_brain_files` (query) and `search_chunks` results (semantic; this is where
  server-side semantic filtering plugs in). Makes the firewall **enforced**, not advised.
  Profile-declared so ACE/work never pay for it.

**Do not block v1 — or anything else — on v2.**

---

## Backward compatibility (the correctness proof)

The `ace` profile, loaded, must reproduce today's behaviour **byte-for-byte**: today's
folders, templates, skills (all 11 global — including `brain-distil`, which today's
`_GLOBAL_SKILL_NAMES` drops), fields (`intensity`/`effort` included), plugin identity,
zk conventions, and `auth = none`. A backward-compat test asserts this. This is what makes
the whole seam an **additive, non-breaking PR** and a clean upstream contribution.

Known pre-existing bugs the extraction must consciously handle:
1. `_GLOBAL_SKILL_NAMES` lists 10 skills but `skills/` has 11 — `brain-distil` never stages
   today. The `ace` manifest lists all 11 (fix), so "byte-for-byte" means *byte-for-byte plus
   this one intended correction* — call it out in the test, don't silently preserve the drop.
2. `hooks/session-start.sh` fires its generic primer **unconditionally** when no marker is
   found — so multiple installed profiles would each emit a primer in every unrelated project.
   Making the hook profile-aware (grep its own `marker`) fixes this as part of Seam 4.

## Public vs private split

- **Upstream (public engine repo):** the seam mechanism — `Config.load_profile()`,
  profile-driven folders/templates/skills/fields, the generic `where` query, the `auth.mode`
  gate + OAuth metadata endpoints, the v2 visibility hook — plus the distribution machinery
  (`--profile-repo`, `brain-profile update`).
- **Public profile repos:** `second-brain-profile-ace`, `second-brain-profile-ace-obsidian`.
- **Private (mounted/cloned at deploy):** `fiction-profile` — its manifest, templates
  (`layer`/`known_by`/`never_tell`), re-authored skills, RBAC map. Never public.
- **Work/Obsidian:** exclude `.ai/`, `.zk/`, and `.brain/.git` from Obsidian sync so
  `embeddings.db` and profile git internals aren't synced.

## Implementation phasing (PR-sized)

1. **Profile loader + `ace` extraction** (Seams 1–4, zk-config split, distribution machinery,
   hook fix). Create the `ace` (and `ace-obsidian`) repos. Pure refactor; behaviour identical
   modulo the two intended fixes. Backward-compat test asserts `ace == today`. **← unblocks
   private profiles by mount/clone.**
2. **Generic query** (Seam 5). Field ladder → profile-driven loop + `where`; dynamic MCP/REST
   schema with split `label`/`query_desc`. **← makes Fiction usable.**
3. **Auth gate** (Seam 6). `auth.mode` + native `authlib` bearer enforcement + OAuth metadata;
   default off. Pairs with the OAuth work. Cloudflare Access removed from the MCP hostname.
4. **Visibility predicate** (Seam 7 v2) + server-side semantic filtering. Optional, after
   Fiction runs on v1.

Phases 1 and 2 are this spec's build target. 3 and 4 are designed here and get their own
plans.

## Decisions locked (were open in the sketch)

- Manifest format: **TOML** (repo already uses it; stdlib `tomllib`).
- Profile home: **`<brain>/.brain/`** — one mount, no env var, brain self-describing.
- Ownership/distribution: **user owns; git for delivery, off the boot path; nothing baked in
  but the default URL pointer.**
- Boundary: **wide** — profile owns templates, skills, zk conventions, hooks, vocabulary,
  plugin identity, vault-claude, prompts/setup.
- OAuth issuer: **native `authlib`**, not a sidecar.
- `where` operators: **equality/membership only** for now; add operators only if a profile
  needs them.
- DB `chunks` columns: **left as convenience columns**; promote only with Seam 7 v2.

## Open items (do not block phase 1)

- Exact `[auth.rbac]` schema shape — finalise when Seam 6 is planned (phase 3).

Resolved during review: `ace-obsidian` is its own repo, **forked from `ace` and customised**
(not a branch). The `brain-distil` fix is included in the `ace` extraction.
