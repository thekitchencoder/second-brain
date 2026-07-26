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

**Still to come:** content visibility / RBAC enforcement built on the auth gate (Seam 7),
and public, forkable profile repositories (community profiles).

### Backward compatibility

The default experience is unchanged. `docker run … brain-init` followed by
`docker run …` behaves exactly as before — offline, zero-config — because the bundled
`ace` profile encodes today's folders, templates, skills, and conventions. Custom
profiles are strictly opt-in.

## [1.1.0]

Last tagged release. See the Git history and Docker Hub for prior changes.
