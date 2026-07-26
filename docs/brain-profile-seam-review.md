# Brain Profile Seam — review & companion notes

Status: review companion to `brain-profile-seam.md` (drafted with Claude, 2026-07-25)
Related: `docs/mcp-oauth-brief.md`; the actor-model design note (workshop side)

Verdict up front: the seam design is the right chassis and the PR phasing is right.
These notes add one synthesis, tighten one requirement for fiction profiles, close one
auth gap, and propose two cheap additions best made while Seams 6–7 are still wet cement.

## 1. Synthesis: the engine is already the actor substrate

The multi-agent layer planned above this (named agents corresponding, remembering,
pursuing goals against canon) needs no new storage engine — it is all notes:

- **Correspondence**: notes with `type: letter` frontmatter (`from`, `to`, `thread`,
  `date`, citations). Mailboxes are just folders; threading is a field.
- **Episodic memory**: per-conversation recollections as notes visible only to their
  owner (`known_by: [<self>]`) — lossy by construction via a length budget.
- **Relationship state**: one rolling distilled note per counterpart, consolidated
  periodically from episodic notes (a distil-style skill, not engine code).
- **Recall**: `brain_search` / `brain_query` under the caller's principal *is* memory
  retrieval — gist always, detail unevenly, older material via its consolidated residue.

One corpus, one visibility predicate, uniform indexing. The only genuinely new machinery
is the orchestrator (turn-taking, gates, routing). This collapses most of the planned
actor-layer storage work into profile + skill authoring.

## 2. Fiction profiles: Seam 7 v2 is the requirement, not the enhancement

Seam 7 v1 (firewall enforced in skill prose) is fine for personal/work brains. It is
**not sufficient for quarantined in-character agents**, because the failure mode is at
*ingress*: an agent that merely retrieves out-of-scope material is already contaminated,
regardless of what it later surfaces. Advice gates egress; quarantine requires gating
retrieval. Ship v1 for the human-facing profiles, but treat **v2 (the enforced
`visible(meta, caller)` predicate) as the gating requirement for any fiction-profile
deployment that runs in-character agents.**

And the predicate must cover **every content egress path**, not only `brain_query` +
`search_chunks`:

- `brain_read` (direct path fetch — the obvious bypass)
- `brain_backlinks`, `brain_related` (leak titles/paths of invisible notes)
- any REST equivalent of the above
- error messages and no-match hints (must not confirm the existence of invisible notes —
  a 404-vs-403 distinguisher is an oracle)

One predicate, applied at a single choke point all these call through, is the design to
aim for; per-endpoint checks will drift.

## 3. Virtual principals: how a subagent becomes a caller

The RBAC map binds OAuth identities (email/sub) to roles — correct for humans and
surfaces. In-fiction agent principals (e.g. `fenn-agent`) never perform an OAuth dance;
they are orchestrator-spawned. Recommendation:

- **Per-principal credentials minted by the orchestrator** — at v1 on a single host,
  static bearer tokens per principal in the deploy config are acceptable; upgrade path is
  orchestrator-issued short-lived tokens once Seam 6's issuer exists.
- Enforcement stays **server-side**: the token *is* the principal; no request parameter
  may select a role.
- **Anti-pattern to avoid**: one privileged orchestrator token plus an "act as role X"
  parameter. That is a confused deputy — a single orchestrator bug (or a prompt-injected
  agent asking its tools nicely) leaks the widest clearance into the narrowest context.

## 4. Cheap addition: per-role layer allowlist (coarse wall before fine filter)

`known_by`/`never_tell` are per-note and depend on frontmatter being right. Add a
per-role **layer allowlist** in `[auth.rbac]` (e.g. `fenn-agent = { layers = ["fiction"] }`)
applied *before* the per-note predicate. Properties: robust to sloppy or missing
frontmatter (deny-by-default on `layer`), trivially auditable, and it makes the common
case fast. The fine-grained fields then refine *within* permitted layers.

## 5. Cheap addition: per-principal retrieval log

At the same choke point as the predicate, log `(principal, tool, query-or-path,
returned note IDs, timestamp)`. Cost: a few lines. Value: leak forensics; provenance
input for downstream claim-checking (agents citing retrieval IDs); and an audit answer
to "what did this caller see, and when" — which the multi-agent layer wants for its
own record-keeping. Recommend folding into the Seam 6/7 work rather than retrofitting.

## 6. OAuth brief — one upgrade it implies but doesn't claim

Once Seam 6 ships per `mcp-oauth-brief.md`, the brain is not limited to desktop-proxied
access: it qualifies as a claude.ai **custom connector** (OAuth 2.1 + PKCE, persistent
refresh) — reachable directly from web, mobile, and cloud Cowork sessions. The
"register the MCP in the desktop app" step becomes the fallback, not the plan.

## 7. Review checklist for the pending Seam 5 branch (generic query)

- **Ace parity**: tests assert ace profile == today's behaviour byte-for-byte
  (field set, hint text, MCP inputSchema, REST params).
- **Semantics**: `kind=scalar` equality vs `kind=list` membership handled uniformly;
  list-membership matches the documented `known_by=fenn` shape.
- **`where` escape hatch**: equality/membership only (no operators yet, per open
  decision); no collision with reserved params (`tag`, `created_after/before`, paging);
  unknown fields fail soft (no match + hint) rather than error.
- **Schema generation**: MCP `inputSchema` and REST `list_notes` params both derived
  from `profile.fields` — one source, not two hand-maintained lists.
- **`_no_match_hint`** derived from the profile, not re-hardcoded.
- **Special cases preserved**: `tag` still delegates to zk; `created_*` still ranged.
- **Forward-compat**: nothing in the query path assumes the ace field names
  (`intensity`/`effort` appear only in `profiles/ace/profile.toml`).
- Docs: `mcp-server.md` / `user-guide.md` note that advertised filters are
  profile-dependent.

## 8. Ordering deltas suggested

1. Land Seam 5 (in review) → 2. Seam 6 auth gate → 3. **Seam 7 v2 + layer allowlist +
retrieval log as one unit** (they share the choke point) → 4. actor/orchestrator layer
on top. v1 skill-advised visibility ships whenever the fiction profile ships, but is not
load-bearing for quarantines.
