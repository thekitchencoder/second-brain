# MCP auth across all Claude surfaces — spike findings (2026-07-24)

## Bottom line
claude.ai custom connectors (web + mobile) **do support OAuth 2.1 + PKCE with seamless
token refresh** — after a one-time initial login, the connection stays live without
re-auth. That is the fix for the "Cloudflare Access expires daily" pain. The clean
arrangement: **give second-brain's MCP its own OAuth 2.1 and REMOVE Cloudflare Access
from the MCP hostname** (keep the tunnel for transport only).

## Per-surface support
- **claude.ai web + mobile connectors**: OAuth 2.1 + PKCE ✅, Dynamic Client Registration
  (RFC 7591) ✅, and static bearer/API-key headers now in **beta** (≤4 headers, not
  `Authorization` when OAuth is used). Token refresh is automatic/persistent.
- **Claude Code / Desktop**: custom HTTP headers ✅ (so a Cloudflare Access **service
  token** via `CF-Access-Client-Id/Secret` works today, non-interactive), and OAuth 2.1 ✅
  with auto-refresh. `claude mcp add <name> --transport http --header "Authorization: Bearer …" <url>`.

## What the MCP server must expose (MCP auth spec 2025-11-25 → 2026-07-28 RC)
- `GET /.well-known/oauth-protected-resource` (RFC 9728) advertising the auth server.
  (Also expose `/.well-known/oauth-authorization-server` (RFC 8414) — many current
  clients still look there; serve both for compatibility.)
- On unauthenticated requests: `401` with
  `WWW-Authenticate: Bearer resource_metadata="https://brain.example.com/.well-known/oauth-protected-resource"`.
- Auth server endpoints `/authorize`, `/token`, optional `/register` (DCR).
- PKCE S256 mandatory; validate `aud` (audience) = server URI; bind token via
  `resource=` param (RFC 8707).

## Implementation options for second-brain's Python MCP (his own code)
1. **mcp-oauth-proxy sidecar** (github.com/obot-platform/mcp-oauth-proxy) in front of the
   MCP — handles OAuth flows/DCR/token validation; MCP just reads the bearer token.
   **~<1 day. Recommended quick start.**
2. Hand-roll with `authlib` in the Python server (~3–5 days, full control).
3. FastMCP built-in OAuth (only if we move the MCP onto FastMCP).
4. oauth2-proxy sidecar (mature, generic; two OAuth layers can confuse refresh).
- The `modelcontextprotocol` Python SDK already implements OAuth **as a client**; server
  side still needs the endpoints above (via option 1–3).

## Cloudflare arrangement
- **Remove Access from the MCP hostname** (Access would intercept the OAuth redirects);
  keep the tunnel for TLS/transport. MCP does authn/authz via OAuth.
- Interim, before OAuth is built: Access **service tokens** work for Code/Desktop
  (non-interactive) — NOT for web/mobile connectors (which want OAuth).
- Note: cloudflared 2026.6.0 had a service-token regression (fixed after); we installed
  2026.7.3, so we're clear.
- "Access for SaaS / OIDC" is NOT the right fit here.

## Recommended plan
1. Add OAuth to second-brain's MCP (option 1: mcp-oauth-proxy sidecar) — becomes a good
   upstream contribution to the public project.
2. Serve RFC 9728 protected-resource metadata + 401 WWW-Authenticate from the MCP.
3. Deploy brain instances behind the tunnel with **no Access** on the MCP hostname.
4. Add to each Claude surface once (OAuth consent) → persistent thereafter.

Sources: modelcontextprotocol.io/specification (2025-11-25 auth), support.claude.com custom
connectors, claude.com/docs/connectors/custom/remote-mcp, developers.cloudflare.com
(session mgmt, service tokens), github.com/obot-platform/mcp-oauth-proxy.
