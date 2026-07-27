# Authentication (auth gate)

The second-brain engine can gate both its REST API (`brain-api`) and its MCP HTTP
transport behind bearer-token authentication. This is a **profile dimension** —
declared in `profile.auth`, resolved once per request into a `Principal` — not a
separate service to stand up.

This page is a deploy guide. For the design rationale (why the brain is its own
authorization server, why stdio stays unauthenticated, why there's no "act as
role X" parameter), see `docs/superpowers/plans/2026-07-25-brain-profile-plan-d-auth.md`.

Auth answers "who is this caller?" For "which notes can that caller read or
write?" — the role-based `[auth.rbac.roles]` `read`/`write` layer model, field
visibility, and the deploy/re-index steps that come with turning it on — see
[docs/rbac.md](rbac.md).

## The `mode` gate

```toml
[auth]
mode = "none"   # or "oauth"
```

- **`mode = "none"` (the default)** is a total no-op. No token is required, no
  `BRAIN_AUTH_*` environment variable is read, and every request resolves to the
  synthetic `OWNER` principal (full access). This is the bundled `ace` profile's
  setting today — installing this feature changes nothing until you opt in.
- **`mode = "oauth"`** turns on bearer-token enforcement on both the REST API
  (`/api/*`) and the MCP HTTP transport (`/mcp`), and — if you configure the
  upstream IdP variables — mounts a self-contained OAuth 2.1 authorization
  server (`/authorize`, `/callback`, `/token`, `/register`, and the
  `/.well-known/*` metadata documents).

Switching modes is a profile + `.env` change, not a code change. Nothing about
`mode = "none"` deployments needs to change to adopt this — it's opt-in per brain.

### The `BRAIN_AUTH_MODE` instance seam

`profile.auth.mode` is the profile's *declared* mode, but the actual mode a
running instance enforces is resolved by `lib.policy.ProfilePolicyProvider`,
which checks the `BRAIN_AUTH_MODE` environment variable first and only falls
back to the profile's `mode` when it's unset:

```bash
BRAIN_AUTH_MODE=none    # or: oauth
```

This exists so **one profile repo** — one set of roles, identities, and
principal mappings — can serve both an owner-only local instance (laptop,
`docker exec`, no network exposure) and an oauth+RBAC deployment (internet-
facing, behind a tunnel), without maintaining two profiles or hand-editing
`profile.toml` when you move between them: the profile stays at
`mode = "oauth"` and the local instance simply sets `BRAIN_AUTH_MODE=none` in
its own `.env`. An invalid value (anything but `none`/`oauth`) fails loud at
resolution time rather than silently falling back to a default. If
`profile.toml` is missing or unreadable *and* `BRAIN_AUTH_MODE` is unset, the
provider fails closed (raises) rather than guessing a mode — an explicit
`BRAIN_AUTH_MODE` always overrides that failure, by design, since it's the
instance operator's affirmative choice.

## Env var reference

These are read **only when `profile.auth.mode = "oauth"`**. In `mode = "none"`
none of them are consulted, so leaving them unset (or present but unused) is safe.

| Variable | Meaning |
|---|---|
| `BRAIN_AUTH_ISSUER` | Public base URL of the brain; becomes the `iss` claim on brain-issued tokens (e.g. `https://brain.example.com`). |
| `BRAIN_AUTH_AUDIENCE` | Expected `aud` claim on brain-issued tokens — the brain's own resource URI (e.g. `https://brain.example.com/mcp`). |
| `BRAIN_AUTH_SIGNING_KEY` | RSA private key (PEM) the brain signs its JWTs with; the public JWKS is derived from it and served at `/.well-known/jwks.json`. **Required** in oauth mode — the process hard-fails at boot without it. |
| `BRAIN_AUTH_SESSION_SECRET` | Optional. Secret for the upstream-login CSRF session cookie. If unset, derived as `sha256(BRAIN_AUTH_SIGNING_KEY)` — set it explicitly if you'd rather not derive a session secret from the signing key. |
| `BRAIN_AUTH_UPSTREAM_ISSUER` | The upstream OIDC identity provider the brain federates human login to (Google is the reference; e.g. `https://accounts.google.com`). |
| `BRAIN_AUTH_UPSTREAM_CLIENT_ID` | The brain's client ID registered at the upstream IdP. |
| `BRAIN_AUTH_UPSTREAM_CLIENT_SECRET` | The brain's client secret at the upstream IdP. |
| `BRAIN_AUTH_PRINCIPAL_TOKENS` | JSON object `{"<principal-id>": "<token>"}` for static (non-OAuth) callers — see the static principals recipe below. Only consulted when `BRAIN_POLICY_CREDENTIALS` is unset or `env` (the default) — see below. |

`BRAIN_AUTH_ISSUER`, `_AUDIENCE`, and `_SIGNING_KEY` describe the brain's **own**
authorization server. `BRAIN_AUTH_UPSTREAM_*` describes the **upstream** IdP the
brain federates human login to. The upstream provider's JWKS is discovered
automatically from `BRAIN_AUTH_UPSTREAM_ISSUER`'s OIDC metadata
(`/.well-known/openid-configuration`); there is no separate JWKS URL to
configure. The brain never stores passwords — it only ever validates an
upstream `id_token` and mints its own JWT.

## Static principals recipe (the agent path)

Use this when a caller is a program (an agent, a script, a service) rather than
a human clicking through an OAuth consent screen — no browser flow required.
This recipe covers the default `env` credential backend, where the secret
lives in an environment variable; see
[Agent-token credential backends](#agent-token-credential-backends-brain_policy_credentials)
below for the Postgres-backed alternative, which adds instant revocation.

1. In the brain's profile, declare a role and a static principal mapped to it:

   ```toml
   [auth]
   mode = "oauth"

   [auth.rbac.roles]
   fenn-agent = { layers = ["fiction"] }

   [auth.rbac.principals]
   fenn-agent = "fenn-agent"   # principal-id -> role
   ```

2. Set the token value in the container's environment (`<brain>/.env`), never
   in the profile:

   ```bash
   BRAIN_AUTH_PRINCIPAL_TOKENS={"fenn-agent": "<a long random secret>"}
   ```

3. The agent calls the brain with that token as a standard bearer credential:

   ```bash
   curl -H "Authorization: Bearer <a long random secret>" \
     https://brain.example.com/api/templates
   ```

**Server-side authority — restated.** The token *is* the principal. There is
**no "act as role X" request parameter**, anywhere in this system — not a header,
not a query string, not a body field. The server looks up which principal a
token belongs to and which role that principal has; nothing in the request
itself can select or override that mapping. This is a deliberate anti-pattern
guard: an endpoint that let a caller *assert* its own role would be a textbook
[confused deputy](https://en.wikipedia.org/wiki/Confused_deputy_problem) — any
caller could simply claim to be `owner`. If you need a caller to have a
different role, mint it a different token bound to a different principal; don't
add a parameter that changes what a token means.

> ⚠️ **stdio is unauthenticated — quarantined agents must use HTTP only**
>
> `docker exec -i brain brain-mcp-server` (the stdio transport) carries **no
> token and no authentication check**. It runs as `OWNER` with full access to
> the entire corpus, including anything marked `never_tell`. This is
> deliberate: local `docker exec` access is treated as equivalent to root on
> the container, and stdio is the local **operator** channel — the person
> running the container talking to their own brain.
>
> A quarantined, in-character, or otherwise untrusted agent **must never be
> given stdio or `docker exec` access to the brain.** Give it **only** an
> authenticated HTTP endpoint (`mode = "oauth"`, port 7780) plus its own
> principal token from the static-principals recipe above. This is the
> deployment corollary of the virtual-principal decision: a principal's
> restricted role means nothing if the same agent can also reach the
> unauthenticated operator channel and bypass it entirely.

## Agent-token credential backends (`BRAIN_POLICY_CREDENTIALS`)

Static-principal bearer tokens (the recipe above) can be checked against
either of two backends, selected by:

```bash
BRAIN_POLICY_CREDENTIALS=env       # default — BRAIN_AUTH_PRINCIPAL_TOKENS map
BRAIN_POLICY_CREDENTIALS=postgres  # agent_tokens table; requires BRAIN_DATABASE_URL
```

| Variable | Meaning |
|---|---|
| `BRAIN_POLICY_CREDENTIALS` | `env` (default) or `postgres`. Any other value fails loud at provider construction. |
| `BRAIN_DATABASE_URL` | Postgres DSN; **required** when `BRAIN_POLICY_CREDENTIALS=postgres` — the provider raises at construction time if it's unset, rather than silently falling back to `env`. |

- **`env`** is the recipe above: one secret per principal, in
  `BRAIN_AUTH_PRINCIPAL_TOKENS`, compared with a constant-time check. Rotating
  or revoking a token means editing `.env` and restarting the process.
- **`postgres`** stores only a SHA-256 hash of each token (`lib.credentials.PgCredentialStore`,
  table `agent_tokens`) — the plaintext is never persisted, and is printed to
  the operator exactly once, when `brain-admin token mint <pid>` creates it.
  Because verification is a live table lookup on every request, revocation
  (`brain-admin token revoke <pid>`) takes effect immediately, with no
  restart and no waiting on a token's expiry. This backend needs the
  `:full` image (or `pip install 'psycopg[binary,pool]'`) for the `psycopg`
  driver — a plain `env`-backend brain has no such dependency.

Minting, listing, and revoking tokens is a `brain-admin` job, not a manual
SQL or `.env` edit — see
[Administering policy: Token lifecycle](rbac.md#token-lifecycle-agent-credentials)
in `docs/rbac.md`, and the
[compose recipe](recipes/full-stack-compose.md) for a worked example that
turns this backend on.

Either backend only ever resolves the principal id a bearer token belongs
to — the role that principal maps to still comes from
`[auth.rbac.principals]` in the profile, same as the `env` backend. Switching
`BRAIN_POLICY_CREDENTIALS` changes where the *secret* lives; it never changes
where the *grant* lives (see [docs/rbac.md](rbac.md#the-git-truth-model)).

## The retrieval log (`BRAIN_RETRIEVAL_LOG`)

Unlike everything else on this page, the retrieval log is not gated on
`profile.auth.mode` — it's read regardless of auth mode, since even a
`mode = "none"` (owner-only) instance may want a record of what got surfaced:

```bash
BRAIN_RETRIEVAL_LOG=off       # default — no store is ever constructed
BRAIN_RETRIEVAL_LOG=postgres  # append-only log; requires BRAIN_DATABASE_URL
```

| Variable | Meaning |
|---|---|
| `BRAIN_RETRIEVAL_LOG` | `off` (default) or `postgres`. Any other value fails loud at server startup (`check_retrieval_log_config`), never mid-request. |
| `BRAIN_DATABASE_URL` | Postgres DSN; **required** when `BRAIN_RETRIEVAL_LOG=postgres` — same variable the pgvector store and Postgres credential backend use, all sharing one Postgres instance in the full-stack tier. |

See [docs/rbac.md: The retrieval log](rbac.md#the-retrieval-log) for what
gets recorded, the best-effort/loud semantics, and how to query it.

## OAuth / claude.ai custom-connector recipe

Use this when a human needs to log in from claude.ai (web or mobile) or another
OAuth-capable client, with persistent, auto-refreshing access — no daily
re-auth.

1. **Generate the brain's RSA signing key:**

   ```bash
   openssl genrsa -out brain-signing.pem 2048
   ```

   Put its contents in `BRAIN_AUTH_SIGNING_KEY` (the whole PEM, including the
   `BEGIN`/`END` lines) in `<brain>/.env`. Set `BRAIN_AUTH_ISSUER` to the
   brain's public URL and `BRAIN_AUTH_AUDIENCE` to that URL's MCP path (e.g.
   `https://brain.example.com/mcp`).

2. **Register the brain as an OAuth client at the upstream IdP** (Google is the
   reference implementation). Create an OAuth 2.0 client, add
   `https://brain.example.com/callback` as an authorized redirect URI, and set:

   ```bash
   BRAIN_AUTH_UPSTREAM_ISSUER=https://accounts.google.com
   BRAIN_AUTH_UPSTREAM_CLIENT_ID=<from Google Cloud Console>
   BRAIN_AUTH_UPSTREAM_CLIENT_SECRET=<from Google Cloud Console>
   ```

3. **Map the logged-in identity to a role** in the profile:

   ```toml
   [auth.rbac.roles]
   owner = { layers = ["*"] }

   [auth.rbac.identities]
   "you@example.com" = "owner"
   ```

   > ⚠️ **`default_role` grants access to *any* upstream-authenticated user.**
   >
   > When a validated upstream identity is **not** listed in `[auth.rbac].identities`,
   > it falls back to `[auth.rbac].default_role` — but only if you set one. That
   > fallback applies to **anyone who can complete your upstream login** (e.g. any
   > Google account), not just people you know. So:
   > - **Leave `default_role` unset** (the safe default) to *deny* unknown
   >   identities with a `401`. This is almost always what you want for a private
   >   brain — access is an explicit allowlist in `identities`.
   > - If you do set it, set it only to a **genuinely minimal** role (e.g. one with
   >   `layers = []`), **never** `owner` or any role with broad `layers`. A
   >   privileged `default_role` turns "signed in with Google" into "has that role
   >   on my brain".

4. **Add the brain as a claude.ai custom connector.** claude.ai's Dynamic
   Client Registration (DCR) flow calls the brain's `/register` endpoint
   automatically — there's no manual client_id/secret exchange to do on the
   brain side. Just point claude.ai at the brain's URL and follow its
   "Add custom connector" flow; the brain's `/.well-known` metadata tells it
   the rest.

5. **Discovery endpoints** claude.ai (and any spec-compliant MCP client) will
   fetch automatically:

   | Endpoint | Purpose |
   |---|---|
   | `/.well-known/oauth-protected-resource` | RFC 9728 — advertises which authorization server protects this resource. |
   | `/.well-known/oauth-authorization-server` | RFC 8414 — the brain's own AS metadata (`/authorize`, `/token`, `/register`, JWKS URI). |
   | `/.well-known/jwks.json` | The brain's public signing key(s), for validating its own JWTs. |

6. **Consent screen.** After the upstream login succeeds, the brain does not
   immediately issue an authorization code. It shows the logged-in user a
   consent screen naming the requesting client (its registered `client_name`)
   and the exact `redirect_uri` it will be sent to, and requires an explicit
   approve before a code is minted. This is the control that stops a rogue
   client — registered through the intentionally-open `/register` endpoint
   (see the DCR hardening note below) — from silently phishing a token off
   the back of a legitimate upstream login: the human reviewing the screen is
   the last line of defence against a client they don't recognize.

## Token lifecycle

- **Access tokens** are short-lived (~1 hour) brain-issued JWTs, validated
  against the brain's own JWKS. They are not individually revocable — their
  short lifetime is the mitigation, so there's no denylist to maintain.
- **Refresh tokens** are longer-lived and tracked server-side in
  `<brain>/.ai/oauth-refresh.json` (not JWTs — opaque IDs looked up in this
  store). Each refresh token is:
  - **Rotated on every use** — redeeming a refresh token issues a new one and
    retires the one just used; the old value stops working immediately.
  - **Reuse-detected** — presenting an already-rotated (retired) refresh token
    again is treated as a theft signal and revokes the *entire* chain
    descending from that token, not just the replayed one.
  - **Bound to the client that registered it** — a refresh token can only be
    redeemed with the `client_id` it was issued to; presenting it with a
    different `client_id` fails (and does not revoke it — see `/revoke`
    below).
  - **Revocable on demand** via `POST /revoke` (RFC 7009), advertised at the
    AS metadata's `revocation_endpoint`. Revocation also requires the
    matching `client_id`; revoking with the wrong `client_id` returns `200`
    per the RFC but leaves the token live for its actual owner.

## DCR hardening note

`/register` (Dynamic Client Registration, RFC 7591) is **intentionally
unauthenticated** — that's what lets claude.ai self-register without a manual
step. Two guardrails limit the blast radius of that openness:

- **A hard cap of 100 registered clients.** Past the cap, `/register` returns
  `429` rather than growing the client store without bound.
- **`redirect_uris` must be `https://` (or loopback `http://127.0.0.1` /
  `http://localhost`, for local development).** A registrant can only ever
  redirect to a URI it supplies at registration time and that's matched
  exactly at `/authorize` — it cannot register a URI it doesn't control, and
  it cannot get a code redirected somewhere else later.

The residual risk: **anyone who can reach `/register` can create an OAuth
client.** That client is still gated behind the human upstream login at
`/authorize` (it can't mint tokens for identities it doesn't control), but it
does let an attacker register — and enumerate — a client entry. For a
tunnel-fronted private brain, keep `/register` reachable only through the
tunnel (don't additionally expose it on a public IP), and treat the 100-client
cap as a tripwire, not just a resource limit.

## Other deployment cautions

- **Don't set `BRAIN_API_CORS_ORIGINS=*` in oauth mode.** The REST API's CORS
  policy allows the `Authorization` header for the configured origins. This is
  low-risk by default (browsers don't auto-attach bearer tokens, and the
  default origins are loopback), but a wildcard origin combined with bearer
  auth lets any web page a user visits make authenticated requests to the brain
  with a token it can obtain. Set `BRAIN_API_CORS_ORIGINS` to the explicit
  origin(s) that actually need browser access, or leave it unset.
- **Review `default_role` before enabling oauth mode** — see the warning in the
  OAuth recipe above. Unset means deny-unknown, which is the safe default.

## Cloudflare arrangement

If the brain sits behind a Cloudflare Tunnel, the tunnel and OAuth need to
divide responsibilities cleanly:

- **Remove Cloudflare Access from the MCP hostname.** Access intercepts
  requests before they reach the brain and would swallow the OAuth
  redirect/callback flow (`/authorize` → upstream → `/callback`) before the
  brain ever sees it. Access and the brain's own OAuth cannot both gate the
  same hostname.
- **Keep the tunnel** for TLS termination and network transport only — it just
  gets traffic to the container; authentication is the brain's job once
  `mode = "oauth"` is on.
- **Interim, before OAuth is configured:** Cloudflare Access **service
  tokens** (`CF-Access-Client-Id` / `CF-Access-Client-Secret` headers) work
  fine for non-interactive clients — Claude Code and Claude Desktop, which
  support custom headers. They do **not** work for claude.ai's web and mobile
  connectors, which need the OAuth flow itself.

## Manual smoke test (upstream federation)

The upstream OIDC federation path — the one unit tests can't cover, because it
needs a live IdP and a browser — should be walked through by hand after
configuring `mode = "oauth"`:

1. Start the brain with `mode = "oauth"` and the env vars above set (signing
   key, issuer, audience, and the upstream `BRAIN_AUTH_UPSTREAM_*` vars).
2. In a browser, hit:

   ```
   https://brain.example.com/authorize?response_type=code&client_id=<id>&redirect_uri=<uri>&code_challenge=<c>&code_challenge_method=S256&state=<s>
   ```

   (Register a test client via `POST /register` first if you don't already
   have a `client_id`.)
3. Complete the upstream Google login when redirected there.
4. Confirm you land on the brain's **consent page**, naming the client you
   registered and the `redirect_uri` it will send you to. Approve it.
5. Confirm the browser is then redirected back to your `redirect_uri` with a
   `code` and matching `state` query parameter.
6. Exchange the code for a token:

   ```bash
   curl -X POST https://brain.example.com/token \
     -d grant_type=authorization_code \
     -d code=<code> \
     -d redirect_uri=<uri> \
     -d client_id=<id> \
     -d code_verifier=<verifier>
   ```

   Confirm the response is `200` with an `access_token` and `token_type: Bearer`.
7. Call an authenticated endpoint with the returned token:

   ```bash
   curl -H "Authorization: Bearer <access_token>" \
     https://brain.example.com/api/templates
   ```

   Confirm `200`, not `401`.

If any step fails, check first that `BRAIN_AUTH_ISSUER` matches the URL you're
actually reaching the brain on (it's validated as both the OAuth `iss` and the
`/callback` redirect target), and that the upstream IdP's redirect URI is
registered as exactly `<BRAIN_AUTH_ISSUER>/callback`.
