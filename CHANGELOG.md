# Changelog

All notable changes to second-brain are recorded here.

**Release cadence during the profile refactor:** the profile refactor (below) is
landing as a series of interim pull requests that merge to `main` **without cutting
a Docker release**. The image published to `kitchencoder/second-brain:latest` remains
the last tagged version; a version bump and a new release will land once the refactor
reaches its end state. See the [Roadmap](README.md#roadmap).

## [Unreleased]

### Profile seam — one engine, many brains (in progress)

A significant refactor that extracts everything brain-specific out of the engine and
into a selectable **profile**, so a single image can run many brains (work, home,
private fiction, …) with no fork. A brain self-describes via `<brain>/.brain/`; the
bundled `ace` profile is the zero-config, offline default.

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
- **Profile-driven queries** (#9, in review) — note-metadata filtering is generated from
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

**Still to come:** public, forkable profile repositories (community profiles),
plus the store-backed RBAC-tier follow-ups (retrieval/audit log, admin UI,
a `PolicyProvider` that generalizes beyond the bundled sqlite-vec store).

### Backward compatibility

The default experience is unchanged. `docker run … brain-init` followed by
`docker run …` behaves exactly as before — offline, zero-config — because the bundled
`ace` profile encodes today's folders, templates, skills, and conventions. Custom
profiles are strictly opt-in.

## [1.1.0]

Last tagged release. See the Git history and Docker Hub for prior changes.
