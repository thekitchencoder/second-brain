# Changelog

All notable changes to second-brain are recorded here.

## [2.0.0] — 2026-07-28

The profile refactor is complete: the engine (this image) is fully separated
from the profile (a brain's folders, templates, skills, identity, and
queryable fields) — **one engine, many brains, no fork**.

### Changed
- **BREAKING:** profiles no longer ship inside the image. The default profile
  is cloned from [brain-profile-ace](https://github.com/thekitchencoder/brain-profile-ace)
  on first init — which therefore needs network access or a local
  `BRAIN_PROFILE_REPO` source (git URL or directory). Existing brains
  (`.brain/` already seeded) are unaffected. An Obsidian flavour is available
  at [brain-profile-obsidian](https://github.com/thekitchencoder/brain-profile-obsidian).
  `folders = []` is now valid in `profile.toml` (no prescribed taxonomy), and
  `profile.toml` may declare a `schema` version (missing = 1): now that profiles
  evolve in their own repos, an engine refuses to load a profile declaring a
  newer schema than it supports instead of misreading it.

### Added
- Per-brain host identity: `brain-init --brain-name <name>` (or `-e BRAIN_NAME`)
  qualifies the staged plugin, marketplace, MCP server key, and session-hook
  marker (`second-brain-work`, `brain-work`) so several brains coexist on one
  machine. The staged MCP endpoint is configurable — `--mcp-url` /
  `BRAIN_MCP_PUBLIC_URL` for tunnel/reverse-proxy deployments (staged
  verbatim), `--mcp-port` / `BRAIN_MCP_HOST_PORT` and `BRAIN_API_HOST_PORT`
  for remapped local ports. Identity persists in the brain's `.env`; with
  nothing set, staging is unchanged.
- `PgVectorStore`: PostgreSQL/pgvector index backend for the full-stack tier,
  selected via `BRAIN_VECTOR_STORE=pgvector` + `BRAIN_DATABASE_URL`. Exact-scan
  search with native layer filtering (recall-correct by construction).
- Image tiers: `:oauth` (twin tags of core) and `:full` (adds psycopg);
  compose recipe in `docs/recipes/full-stack-compose.md`.
- Admin plane: `/api/admin/*` (owner-gated, oracle-safe 404s) and the
  `brain-admin` CLI. Policy edits are git commits to the profile repo —
  the profile stays the single source of policy truth.
- Postgres agent-token credentials (`BRAIN_POLICY_CREDENTIALS=postgres`):
  hashed bearer tokens with instant revocation; minted via brain-admin.
- `BRAIN_AUTH_MODE` env override — one profile repo can serve an
  owner-only local instance and an oauth+RBAC deployment.
- Policy hot-reload: rbac changes apply without restart.
- Per-principal retrieval log (`BRAIN_RETRIEVAL_LOG=postgres`): append-only
  record of every note surfaced to each principal (plus writes and admin
  actions) in the full-stack tier's Postgres. Best-effort + loud — a log
  outage never blocks retrieval. Query via `GET /api/admin/retrievals` or
  `brain-admin log query`.

### Deprecated
- The `:ui` image is no longer published. Build your own thin layer —
  recipe in `docs/recipes/code-server.md`. Existing `:ui` tags remain
  on Docker Hub.

### Profile seam — one engine, many brains

The refactor that extracts everything brain-specific out of the engine and
into a selectable **profile**, so a single image can run many brains (work, home,
private fiction, …) with no fork. A brain self-describes via `<brain>/.brain/`,
seeded from a profile repo on first init.

- **Profile-driven engine** (#6) — folders, templates, skills, plugin identity, and
  zk conventions are read from the profile instead of hardcoded constants. The bundled
  `ace` profile reproduces prior behaviour byte-for-byte, plus one fix: the
  previously-dropped `brain-distil` skill is now installed (11 global skills, not 10).
- **Profile distribution** (#8) — custom profiles via `brain-init --profile-repo <url-or-path>`
  or `-e BRAIN_PROFILE_REPO=<url-or-path>` (git-cloned for a repo/URL, copied for a plain
  directory). New `brain-profile update` (git pull) and `brain-profile show`. The
  container's Claude Code skills are sourced from the active profile; the redundant
  top-level `skills/`, `brain-skills/`, `zk/`, `hooks/`, and `claude/*.md` sources were
  removed in favour of `profiles/ace/`.
- **Profile-driven queries** (#9) — note-metadata filtering is generated from
  the profile's declared fields: the MCP `brain_query` schema and REST `list_notes`
  filters adapt per profile, with a generic `where` escape hatch and a fail-loud 400 on
  unknown REST filter fields.
- **Auth gate (Seam 6)** — static per-principal bearer tokens + OAuth 2.1 authorization
  server (PKCE S256, DCR, upstream-IdP federation), gated on `profile.auth.mode`; default
  `none` is a no-op. See [docs/auth.md](docs/auth.md).
- **Auth:** OAuth server hardened for internet exposure — a consent screen on the
  authorization-code flow (closes an auth-code-injection path under open DCR), and
  stateful refresh tokens with rotation, reuse detection, client binding, and an
  RFC 7009 `/revoke` endpoint. The consent screen now sends anti-clickjacking and
  no-store headers. Note: enabling this build's stateful refresh invalidates any
  refresh tokens issued by a prior build — they lack a stored jti and force one
  re-auth.
- **Content visibility / RBAC (Seam 7)** — role-based read/write layers
  (`[auth.rbac.roles]` `read`/`write`) plus fine-grained `allow`/`deny`
  visibility fields, enforced at a single choke point
  (`visible()`/`can_write()`) across every read-egress path (`brain_read`,
  `brain_query`, `brain_search`, `brain_related`, `brain_backlinks`) and every
  write path (`brain_write`, `brain_edit`, `brain_trash`, `brain_restore`),
  on both the MCP handlers and the REST routes. Deny-by-default on missing
  layer; a forbidden note is oracle-safe — indistinguishable from a genuinely
  absent one on every surface. A write additionally gates on the
  layer-mutation guard: it may not move a note into (or out of) a layer the
  caller can't write, checked against the actual post-edit frontmatter so a
  raw-text edit can't smuggle a layer change past the check. Semantic search
  filters recall-correctly on a `layer` column added to the chunks index
  (existing brains migrate the column automatically; re-index to populate it
  after turning RBAC on). `mode = "none"` (the bundled `ace` profile's
  setting) remains a total no-op — see [docs/rbac.md](docs/rbac.md) for the
  deploy guide, including the folder-homogeneous-layers profile-authoring
  rule that keeps the write-path existence oracle unreachable in a
  well-formed profile. The retrieval/audit log and an admin UI are deferred,
  store-backed follow-ups, not part of this build.

Public, forkable profile repositories and the store-backed RBAC-tier
follow-ups (retrieval/audit log, `PolicyProvider` beyond the bundled
sqlite-vec store) shipped within this release; an admin UI for the RBAC
tier remains a planned follow-up.

### Backward compatibility

`docker run … brain-init` followed by `docker run …` still yields the same
brain as before — the `ace` profile encodes the same folders, templates,
skills, and conventions — but first init now clones that profile from its
public repo, so it needs network access once (or a local `BRAIN_PROFILE_REPO`
source). Existing brains are untouched. Custom profiles remain strictly opt-in.

## [1.1.0]

Last tagged release. See the Git history and Docker Hub for prior changes.
