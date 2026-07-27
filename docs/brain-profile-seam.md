# Brain Profile Seam — design

Status: draft / design doc (pick up as its own dev session)
Author: drafted with Claude, 2026-07-24
Related: `docs/mcp-oauth-brief.md` (the auth half of this)

## Why

Second-brain's engine (walk, semantic search, embeddings, wikilinks, edit/trash,
templates) is already schema-agnostic. What is *not* is a thin set of hardcoded
assumptions — the ACE folder names, the ACE-specific queryable fields
(`intensity`/`effort`), the two skill-name sets, and the plugin identity. To use one
engine for multiple brains (work/ACE, a private fiction brain, others) we introduce **one new
concept — a selectable `BRAIN_PROFILE`** — and thread it through those few coupling
points. Everything else stays shared.

**Path 1 (public engine, private profiles):** the *mechanism* here goes upstream to the
public repo (additive, non-breaking). Each brain's *profile* (folders, templates, skills,
field set, auth/RBAC) is **data** — a directory that can be bundled (the default `ace`
profile) or **mounted privately at deploy** (fiction, work) onto the stock image. No
fork.

**Auth is a profile dimension, not a fixed feature** (Chris's point): the same engine runs
`auth: none` (work — 1 machine/1 user), `auth: oauth` single-identity (home — many
surfaces/1 user), or `auth: oauth` + **RBAC over virtual users** (the fiction brain — where RBAC
*is* the `known_by`/`never_tell` spoiler firewall). See Seams 6–7.

---

## Core idea

- New env `BRAIN_PROFILE` (default `ace` → today's behaviour exactly).
- New env `BRAIN_PROFILES_DIR` (default: bundled `profiles/` in the image; override to a
  mounted volume to supply a private profile).
- A **profile manifest** `profiles/<name>/profile.toml` declares everything profile-specific.
- A profile directory:
  ```
  profiles/<name>/
    profile.toml          # folders, indexed fields, skills, plugin identity, auth
    templates/*.md        # frontmatter templates for this profile
    skills/               # profile's skill set (global + vault tiers)
  ```
- Private profiles are the same shape, supplied at runtime:
  `-e BRAIN_PROFILE=fiction -v /srv/fiction-profile:/profiles/fiction`.

### Profile manifest (proposed schema)

```toml
name = "fiction"
plugin_name = "fiction-brain"        # replaces hardcoded "second-brain"
plugin_author = "kitchencoder"

folders = ["codex", "canon", "characters", "memory"]

# Frontmatter fields promoted to first-class query filters + advertised in the
# MCP/REST schema. Everything else is still queryable via the generic `where` escape hatch.
[fields]
type      = { kind = "scalar" }
status    = { kind = "scalar" }
layer     = { kind = "scalar" }
tags      = { kind = "list"   }
related   = { kind = "list"   }
known_by  = { kind = "list",  visibility = true }   # feeds the visibility predicate
never_tell= { kind = "list",  visibility = true }

# Which skills this profile ships (names resolved under skills/)
[skills]
global = ["brain-capture", "brain-connect", "brain-context", "brain-save", "brain-triage"]
vault  = ["brain-daily", "brain-hygiene", "brain-rename"]

[auth]
mode = "oauth"          # none | oauth
# rbac only meaningful when mode = oauth
[auth.rbac]
roles   = ["author", "reader", "fenn-agent"]
# map an authenticated identity (OAuth sub / email) to a role
identities = { "author@example.com" = "author" }
# visibility policy for the spoiler firewall (Seam 7)
default_role = "reader"
```

The `ace` profile is just `profiles/ace/profile.toml` with
`folders = ["Atlas","Efforts","Cards","Calendar","Sources"]`, the current 9 templates, the
current skill sets, `plugin_name = "second-brain"`, `[fields]` = `type,status,intensity,
effort,tags,created`, and `[auth] mode = "none"`. Loading it reproduces current behaviour
byte-for-byte.

---

## Seam 1 — Config (`tools/lib/config.py`)

**Now:** 23-line `Config` reading `EMBEDDING_BASE_URL`, `EMBEDDING_MODEL`, `BRAIN_PATH`,
`BRAIN_API_CORS_ORIGINS`; `db_path` hardcodes `.ai/embeddings.db`.

**Change:** add `self.profile = os.environ.get("BRAIN_PROFILE", "ace")` and
`self.profiles_dir = os.environ.get("BRAIN_PROFILES_DIR", <bundled>)`. Add a
`load_profile()` that parses `profiles/<name>/profile.toml` and exposes
`.folders`, `.fields`, `.skills`, `.plugin`, `.auth`. Everything downstream reads the
profile through `Config`. **Effort: small.** This is the single source of truth.

## Seam 2 — Folders (`tools/brain-init`)

**Now:** `ACE_FOLDERS = ["Atlas","Efforts","Cards","Calendar","Sources"]` (line 70),
consumed only by `init_ace_folders()` (507) and the interactive folder step (642–658).
Nothing in the engine references folder names (`_walk_brain_files` is name-agnostic).

**Change:** `ACE_FOLDERS` → `cfg.load_profile().folders`. Rename `init_ace_folders` →
`init_profile_folders`. **Effort: trivial** — pure naming constant.

## Seam 3 — Templates (`tools/brain-init`, `tools/lib/brain.py`)

**Now:** already directory-driven — `init_core()` copies `zk/templates/*` into
`<vault>/.zk/templates/`; `_list_template_names()` (`brain.py:310`) reads that dir; no
hardcoded template filenames anywhere.

**Change:** source templates from `profiles/<name>/templates/` instead of the fixed `zk/`
tree (fall back to `zk/templates` for `ace`). **Effort: trivial** — swap the source path;
runtime discovery already works.

## Seam 4 — Skills & plugin identity (`tools/brain-init`)

**Now:** two hardcoded sets `_VAULT_SKILL_NAMES` / `_GLOBAL_SKILL_NAMES` (59–68);
`stage_brain_plugin()` (400–504) writes `plugin.json`/`marketplace.json`/`.mcp.json` with
hardcoded `name="second-brain"`, `author="kitchencoder"`, and stages `_GLOBAL_SKILL_NAMES`.

**Change:** the two name-sets and the plugin/marketplace identity come from
`profile.skills` and `profile.plugin_*`. Skill *source* dir resolves under
`profiles/<name>/skills/` (fall back to repo `skills/`+`brain-skills/` for `ace`). The
plugin machinery is reused verbatim — only names are parametrised. **Effort: small.**
(The fiction-brain skill *content* — re-authored prose for codex/canon/characters/memory —
lives in the private profile, not upstream. Mind the exfiltration-language guardrail: frame
`known_by`/`never_tell` as in-world knowledge boundaries.)

## Seam 5 — Queryable fields (the real one)

**Now (schema-coupled in 4 places, all the SAME fixed set `status,type,intensity,effort,
created_*` + `tag`):**
- `handle_brain_query()` (`brain.py:163–247`) — one hardcoded `if meta.get("<field>")`
  branch per field. Walks files + compares frontmatter (does **not** use the DB columns).
- `_no_match_hint()` `field_map` (`brain.py:154`).
- MCP `brain_query` `inputSchema` (`brain_mcp_server.py:52–67`).
- REST `list_notes` params (`brain_api.py:209–229`).
- (`SearchResult` surfaces `title,type,status,created,tags` — cosmetic.)
- DB `chunks` columns `title,type,status,created,tags,scope` (`db.py:56–68`) are **written
  but never filtered on** — so they don't block this seam; leave as convenience columns.

**Change — generalise, don't re-hardcode:**
1. Replace the per-field `if` ladder in `handle_brain_query` with a loop over
   `profile.fields`, comparing `meta.get(field)` — **scalar** equality for `kind=scalar`,
   **list membership** for `kind=list` (so `known_by=fenn`, `tags=x` work uniformly). Keep
   the two genuinely-special cases: `tag` (delegated to `zk list --tag`) and
   `created_after/before` (date range).
2. Add a generic `where: {field: value}` escape hatch so *any* frontmatter key is filterable
   even if not promoted — future-proofs new fields without code changes.
3. `_no_match_hint.field_map` → derived from `profile.fields`.
4. MCP `brain_query.inputSchema` and REST `list_notes` → **generated from `profile.fields`**
   at server build (`list_tools()` already builds the schema dynamically-capable), plus the
   stable `tag`/`created_*`/`where`. So the fiction brain's MCP advertises `layer`/`known_by`
   filters automatically; ACE keeps `intensity`/`effort`.

**Effort: medium** — this is the one seam with real signature churn, but it's bounded to
these four call sites and makes the engine strictly more general. `intensity`/`effort` stop
being engine concepts and become just two entries in the `ace` profile's `[fields]`.

## Seam 6 — Auth (additive; currently ZERO auth anywhere)

**Now:** no authn/authz on REST (7779) or MCP (7780). CORS allows the `Authorization`
header but nothing reads it. Both bind `0.0.0.0`. Greenfield.

**Change (gated on `profile.auth.mode`):**
- `mode = none` → no-op (today's behaviour; work case).
- `mode = oauth` → require a valid bearer token on every request:
  - REST: a FastAPI dependency (`Depends(require_token)`) on protected routes.
  - MCP: an ASGI wrapper around the `/mcp` mount that 401s without a valid token and emits
    `WWW-Authenticate: Bearer resource_metadata="…"` + serves
    `/.well-known/oauth-protected-resource` (per `docs/mcp-oauth-brief.md`).
- **Token issuance / OAuth endpoints:** two acceptable implementations, deployment's choice —
  (a) **sidecar** `mcp-oauth-proxy` in front (no server code; fastest), or (b) **native**
  via `authlib`. The *profile* only declares that auth is required + the RBAC map; the
  issuer wiring is a deployment/compose concern.
- New env surface: `BRAIN_AUTH_ISSUER`, `BRAIN_AUTH_AUDIENCE`, `BRAIN_AUTH_JWKS_URL`
  (only read when `mode=oauth`).

**Effort: medium**, but cleanly additive — no existing code path changes when `mode=none`.
This is where `docs/mcp-oauth-brief.md`'s recommendation plugs in (drop Cloudflare Access
on the MCP hostname; the server owns auth).

## Seam 7 — Visibility / RBAC (fiction-brain spoiler firewall)

This is where auth (who is calling) meets the fiction brain's `known_by`/`never_tell` (what may be
surfaced). Two levels — ship v1, design v2:

- **v1 (no engine change): enforce in skills.** `known_by`/`never_tell` are just
  `visibility=true` list fields (indexed via Seam 5). The fiction-brain skill prose instructs
  the model never to surface `never_tell` facts to the named party. Zero core work; ships in
  the private profile.
- **v2 (a small second seam): a visibility predicate in the retrieval path.** Given the
  authenticated caller's role (Seam 6), apply `visible(meta, caller) -> bool` — derived from
  `profile.auth.rbac` and the `visibility=true` fields — as a filter in the consumers of
  `_walk_brain_files` (query) and in `search_chunks` result post-filtering (semantic). This
  makes the firewall *enforced*, not just *advised*, and it's the same mechanism as
  multi-virtual-user RBAC. Keep it profile-declared so ACE/work never pay for it.

**Effort:** v1 = zero code; v2 = medium, isolated to a single predicate applied at two
retrieval sites. **Don't block v1 (or the rest of the seam) on v2.**

---

## Backward compatibility

Default `BRAIN_PROFILE=ace` + a bundled `profiles/ace/` that encodes today's folders,
templates, skills, fields (`intensity`/`effort` included), plugin identity, and
`auth=none`. With no env set and the ace profile loaded, every code path behaves exactly as
now. This makes the whole seam an **additive, non-breaking PR** — the property that makes it
a clean upstream contribution.

## Public vs private split (Path 1)

- **Upstream (public repo):** the seam mechanism — `Config.load_profile()`, profile-driven
  folders/templates/skills/fields, the generic `where` query, the `auth.mode` gate + OAuth
  metadata endpoints, the v2 visibility hook — and the bundled `ace` profile.
- **Private (a private profile repo, mounted at deploy):** `profiles/fiction/` —
  its `profile.toml`, its templates (codex/canon/characters/memory frontmatter incl.
  `layer`/`known_by`/`never_tell`), its re-authored skills, its RBAC map. Never public.
- Same pattern for the **work/Obsidian** profile (mounted onto the Obsidian host; remember to
  exclude `.ai/` and `.zk/` from Obsidian sync so `embeddings.db` isn't synced).

## Suggested implementation phasing (PR-sized)

1. **Profile loader + `ace` bundled profile** (Seams 1–4). Pure refactor; behaviour
   identical; add tests asserting ace == today. Ship. ← unblocks private profiles by mount.
2. **Generic query** (Seam 5). Field ladder → profile-driven loop + `where`; dynamic
   MCP/REST schema. Ship.
3. **Auth gate** (Seam 6). `auth.mode` + bearer enforcement + OAuth metadata; default off.
   Pairs with the OAuth dev session. Ship.
4. **Visibility predicate** (Seam 7 v2). Optional, after the fiction brain is running on v1.

## Open decisions

- Manifest format: TOML (proposed) vs YAML vs JSON — match whatever the repo already leans on.
- Where the OAuth *issuer* lives: `mcp-oauth-proxy` sidecar (fast) vs native `authlib`
  (self-contained). Recommend sidecar first; can internalise later.
- Whether to also generalise the DB `chunks` columns (low value now — they're unused as
  filters; the query path reads files, not columns). Leave for a later cleanup.
- Whether `where` should support operators (`>`, `contains`) or stay equality/membership only
  (recommend: start equality/membership; add operators if a profile needs them).
