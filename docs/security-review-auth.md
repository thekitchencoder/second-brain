# Security review — second-brain OAuth + RBAC (Plans D/D2/E)

Reviewer: Claude, 2026-07-26. Scope: internet-facing deployment safety of the
self-hosted auth stack — `tools/lib/auth.py`, `tools/lib/oauth_server.py`,
`tools/lib/visibility.py`, `tools/brain_api.py`, `tools/brain_mcp_server.py`,
`tools/lib/config.py`. Threat model: the MCP + REST endpoints are reachable from the
public internet (behind the Cloudflare tunnel); attacker can hit every route, register
clients, and present arbitrary tokens.

## Verdict

**Safe to deploy internet-facing behind the tunnel, in `oauth` mode, subject to the
deployment checklist below — the two items marked [CRITICAL] are load-bearing.**

Rolling your own OAuth/RBAC is inherently higher-risk than delegating it, and that risk
never fully goes away — but this implementation has visibly internalised the OAuth 2.1
Security BCP, and the usual roll-your-own footguns are handled correctly, not
hand-waved. The residual risk is concentrated in *configuration* and *key secrecy*, not
in the code's logic. I would run it, with the checklist enforced and Cloudflare doing
rate-limiting in front.

## What is done correctly (the hard parts, and they're right)

- **JWT alg pinned to RS256** (`_JWT = JsonWebToken(["RS256"])`) — alg-confusion /
  `alg:none` closed independent of what the token header claims.
- **PKCE S256 mandatory**, verified with `secrets.compare_digest`; `plain` refused.
- **`redirect_uri` exact-match** against the client's registered set on both
  `/authorize` and code redemption; issued codes bind client_id + redirect_uri.
- **Refresh-token rotation with reuse detection** — replay of a rotated (revoked)
  token treats the chain as stolen and revokes the whole family. This is the good
  pattern, not the naive one.
- **Refresh tokens are rejected as resource credentials** (`typ == "refresh"` → not a
  principal), so a refresh token can't be used as an access token.
- **Access tokens validate `iss`, `aud`, `exp`**; audience-bound per RFC 8707. Resource
  metadata advertised via RFC 9728 `/.well-known/oauth-protected-resource`.
- **Fail-closed everywhere it matters**: the MCP `current_principal` ContextVar defaults
  to `ANONYMOUS` (deny), never OWNER; a malformed principal denies in `visible()`;
  `_unrestricted()` only treats a real collection containing `"*"` as owner.
- **Constant-time static-token comparison** (`hmac.compare_digest`); the token *is* the
  principal — no request field influences role (no confused-deputy "act as" param).
- **Oracle-safe reads**: a forbidden note returns the byte-identical `File not found`
  404 as a genuinely absent one, across read/edit/write/backlinks.
- **Layer-escalation closed** (the Plan-E review's finding #1): writes gate on
  `can_write_transition(old, new)` — the caller must be authorised for *both* the note's
  current layer and the incoming content's layer. The `edit` path re-parses the
  candidate's frontmatter after applying the op, so `find_replace`/`replace_lines`
  can't smuggle a `layer:` change past a stale check.
- **DoS bounds**: DCR clients (100), pending flows / auth codes (2000 each), refresh
  tokens (5000), all with expiry sweeps; atomic write-then-rename persistence with a
  corrupt-load guard so a bad file can't brick startup.
- **Consent screen** carries `X-Frame-Options: DENY` + `frame-ancestors 'none'`,
  escapes all interpolated values, and is `no-store`.
- **Session secret hard-fails** rather than defaulting to a dev value; it is derived
  from a hash of the signing key, never a raw PEM prefix.
- **No injection surface**: SQL uses parameterised placeholders (incl. the
  `IN (...)` layer filter); path access is realpath-fenced within the brain; query
  fields are slug-validated (Plan-C).

## Deployment checklist (enforce before exposing)

- [ ] **[CRITICAL] `default_role` MUST be null (or a zero-access role).**
  `resolve_jwt` maps `identities[subject] or default_role`. Registration (`/register`)
  is open per RFC 7591 and `_valid_redirect` allows any https URI — so *anyone with an
  upstream IdP account* can complete a login. Open DCR + arbitrary https redirect only
  ever authorises the attacker's **own** identity (the subject comes from their own
  upstream login), so the identity→role allowlist is the entire access control. With
  `default_role` set to anything with access, the brain is open to the whole IdP. With
  it null, unknown subjects resolve to `None` → 401. The code handles this correctly;
  the risk is purely misconfiguration. Verify the deployed profile.toml.
- [ ] **[CRITICAL] Never expose a `mode="none"` brain to the network.** In that mode
  `resolve_principal` returns OWNER for every request, token or not — by design, for
  the single-user local case. The internet-facing (fiction) brain must be `oauth`.
- [ ] **Signing key**: `BRAIN_AUTH_SIGNING_KEY` is a single RSA key that mints every
  identity→role. Generate ≥2048-bit, inject via secret (not baked into the image),
  restrict volume perms (the `.ai/` stores are already 0600 on the running container),
  and have a rotation plan — there is no `kid`-based multi-key rotation, so rotation is
  a restart with re-auth. Treat this key as the crown jewel; its leak = full
  impersonation.
- [ ] **Rate-limiting**: there is no in-app throttle on `/token`, `/authorize`,
  `/register`, or bearer validation. Token/code entropy makes brute force infeasible,
  but put a Cloudflare rate-limit rule on the auth endpoints anyway (DoS + abuse).
- [ ] **CORS**: `BRAIN_API_CORS_ORIGINS` defaults to loopback — good. If you set it,
  set explicit origins, never `*`. (Auth is bearer-header, not cookie, so CORS isn't a
  token-theft path, but keep it tight.)
- [ ] **Keep Cloudflare Access OFF the MCP hostname** (per the OAuth brief — Access
  would intercept the OAuth redirects); the tunnel provides transport only, the app
  owns authn/authz.
- [ ] **Bind note**: both servers bind `0.0.0.0` inside the container. Fine behind the
  tunnel; do not publish the container ports to the host/LAN directly. Auth is required
  on every `/mcp` and `/api` route, so DNS-rebinding can't reach tools unauthenticated,
  but don't widen the exposure.

## Lower-severity notes (not blockers)

- **Single-key, single-process by design.** RefreshStore/AuthState are in-memory or
  single-file; a multi-replica deployment needs a shared store (already documented in
  the code comments). For one homelab container this is fine.
- **Write-path create oracle** (documented, accepted): a restricted write to a
  non-existent path vs. a forbidden-existing path can differ (403 vs 404). The
  mitigation is the profile discipline of folder-homogeneous layers — worth a line in
  `docs/rbac.md` (the plan flagged this).
- **`/register` open registration** grows a bounded on-disk store of stranger-created
  clients (capped at 100). Harmless given the role gate, but you may prefer to disable
  DCR and pre-register the claude.ai client once, if the surfaces you use allow it.
- **Consider an external conformance pass.** The logic reviews clean, but for
  self-hosted OAuth a one-time run against an OAuth 2.1 / MCP-auth conformance suite (or
  a second human security review) is cheap insurance before you rely on it.

## Bottom line

The code is well above the bar I expect from hand-rolled auth, and materially safer
than a naive implementation. The failure modes that would actually bite are
*operational*: the signing key leaking, or `default_role` being set to something with
access. Nail the two [CRITICAL] checklist items, put Cloudflare rate-limiting in front,
and this is a reasonable thing to run internet-facing for a single-user (plus scoped
agent principals) deployment.
