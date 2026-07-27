"""brain-admin: manage auth policy — roles, identities, principals, tokens.

Two transports behind one method-per-operation interface:

- Local (default): operates directly on the profile repo (via
  lib.policy_edit.PolicyEditor / lib.policy.ProfilePolicyProvider) and, for
  `token` subcommands, Postgres (via lib.credentials.PgCredentialStore). This
  is the docker-exec recovery path — it needs no running API and no network.
- Remote (--url/BRAIN_API_URL + --token/BRAIN_ADMIN_TOKEN): talks to the
  admin REST API (/api/admin/*) over HTTP with a bearer token.

Both transports raise the same two exception types so `main()` has a single
error-handling path:
  - PolicyEditError — a user error (bad input, unknown role, etc): print to
    stderr, exit 1.
  - RuntimeError — an infra/config problem (misconfigured credentials,
    unreachable API, not found/not authorized): print to stderr, exit 1,
    with wording distinct from the user-error case.

Tokens are printed to stdout ONLY by `token mint` — nowhere else, ever.
"""
from __future__ import annotations

import argparse
import os
import sys
from urllib.parse import urlencode

import httpx

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

from lib.config import Config  # noqa: E402
from lib.policy_edit import PolicyEditError  # noqa: E402
from lib import retrieval_log  # noqa: E402
from lib.retrieval_log import safe_log_admin  # noqa: E402

# The local transport is the docker-exec recovery path (see module docstring
# above) — there is no resolved OAuth/bearer principal to attribute a
# mutation to here, only whatever trust comes from having a shell inside the
# container. Every admin-log row written from this transport is attributed
# to this fixed sentinel rather than a real principal id.
_LOCAL_ADMIN_PRINCIPAL = "local-admin"


def _rbac_dict(rbac):
    if rbac is None:
        return {"default_role": None, "roles": {}, "identities": {}, "principals": {}}
    return {
        "default_role": rbac.default_role,
        "roles": rbac.roles or {},
        "identities": rbac.identities or {},
        "principals": rbac.principals or {},
    }


# ── Local transport ─────────────────────────────────────────────────────

class LocalTransport:
    """The docker-exec recovery path: operates on Config().profile_dir /
    BRAIN_DATABASE_URL directly, no API involved."""

    def __init__(self, cfg: Config):
        self.cfg = cfg

    def _editor(self):
        from lib.policy_edit import PolicyEditor
        return PolicyEditor(self.cfg.profile_dir)

    def _provider(self):
        from lib.policy import ProfilePolicyProvider
        return ProfilePolicyProvider(self.cfg.profile_dir)

    def _credential_store(self):
        if os.environ.get("BRAIN_POLICY_CREDENTIALS", "env") != "postgres":
            raise RuntimeError(
                "Token minting requires BRAIN_POLICY_CREDENTIALS=postgres")
        if not self.cfg.database_url:
            raise RuntimeError(
                "BRAIN_POLICY_CREDENTIALS=postgres requires BRAIN_DATABASE_URL")
        from lib.credentials import get_credential_store
        return get_credential_store(self.cfg.database_url)

    # reads
    def policy_show(self):
        p = self._provider()
        return {
            "auth_mode": p.get_auth_mode(),
            "credential_backend": os.environ.get("BRAIN_POLICY_CREDENTIALS", "env"),
            "rbac": _rbac_dict(p.get_rbac()),
        }

    def role_list(self):
        return {"roles": _rbac_dict(self._provider().get_rbac())["roles"]}

    def principal_list(self):
        return {"principals": _rbac_dict(self._provider().get_rbac())["principals"]}

    # mutations — all return {"commit": sha}; each logs post-success under
    # the local-admin sentinel, mirroring brain_api._admin_edit's subjects.
    def role_set(self, name, read, write, admin=False):
        sha = self._editor().role_set(name, read, write, admin=admin)
        safe_log_admin(_LOCAL_ADMIN_PRINCIPAL, "policy_edit",
                       f"role_set {name} ({sha[:7]})")
        return {"commit": sha}

    def role_rm(self, name):
        sha = self._editor().role_rm(name)
        safe_log_admin(_LOCAL_ADMIN_PRINCIPAL, "policy_edit",
                       f"role_rm {name} ({sha[:7]})")
        return {"commit": sha}

    def identity_map(self, subject, role):
        sha = self._editor().identity_map(subject, role)
        safe_log_admin(_LOCAL_ADMIN_PRINCIPAL, "policy_edit",
                       f"identity_map {subject} -> {role} ({sha[:7]})")
        return {"commit": sha}

    def identity_unmap(self, subject):
        sha = self._editor().identity_unmap(subject)
        safe_log_admin(_LOCAL_ADMIN_PRINCIPAL, "policy_edit",
                       f"identity_unmap {subject} ({sha[:7]})")
        return {"commit": sha}

    def principal_set(self, pid, role):
        sha = self._editor().principal_set(pid, role)
        safe_log_admin(_LOCAL_ADMIN_PRINCIPAL, "policy_edit",
                       f"principal_set {pid} -> {role} ({sha[:7]})")
        return {"commit": sha}

    def principal_rm(self, pid):
        sha = self._editor().principal_rm(pid)
        safe_log_admin(_LOCAL_ADMIN_PRINCIPAL, "policy_edit",
                       f"principal_rm {pid} ({sha[:7]})")
        return {"commit": sha}

    def default_role_set(self, role):
        sha = self._editor().default_role_set(role)
        safe_log_admin(_LOCAL_ADMIN_PRINCIPAL, "policy_edit",
                       f"default_role_set {role} ({sha[:7]})")
        return {"commit": sha}

    # tokens
    def token_mint(self, pid):
        rbac = self._provider().get_rbac()
        if pid not in (_rbac_dict(rbac)["principals"]):
            raise PolicyEditError(
                f"unknown principal: {pid} — add it first (principal set {pid} ROLE)")
        token = self._credential_store().mint(pid)
        safe_log_admin(_LOCAL_ADMIN_PRINCIPAL, "token_mint", pid)
        return {"principal_id": pid, "token": token}

    def token_revoke(self, pid):
        revoked = self._credential_store().revoke(pid)
        safe_log_admin(_LOCAL_ADMIN_PRINCIPAL, "token_revoke", pid)
        return {"principal_id": pid, "revoked": revoked}

    def token_list(self):
        tokens = self._credential_store().list_tokens()
        safe_log_admin(_LOCAL_ADMIN_PRINCIPAL, "token_list", f"{len(tokens)} tokens")
        return {"tokens": tokens}

    # retrieval log — reading it is NOT itself logged as an admin event
    # (no safe_log_admin equivalent here); see brain_api.admin_retrievals.
    def log_query(self, principal=None, kind=None, tool=None, since=None,
                  until=None, path=None, limit=100):
        if not retrieval_log.enabled():
            raise RuntimeError("Retrieval log requires BRAIN_RETRIEVAL_LOG=postgres")
        if not self.cfg.database_url:
            raise RuntimeError(
                "BRAIN_RETRIEVAL_LOG=postgres requires BRAIN_DATABASE_URL")
        log = retrieval_log.get_retrieval_log(self.cfg.database_url)
        return {"entries": log.query(principal=principal, kind=kind, tool=tool,
                                     since=since, until=until, path=path,
                                     limit=limit)}


# ── Remote transport ────────────────────────────────────────────────────

def _detail(response):
    try:
        body = response.json()
    except ValueError:
        return response.text or f"HTTP {response.status_code}"
    if isinstance(body, dict) and "detail" in body:
        return body["detail"]
    return response.text or f"HTTP {response.status_code}"


class RemoteTransport:
    """Talks to the admin REST API (/api/admin/*) over HTTP, bearer-authed."""

    def __init__(self, url: str, token: str):
        self._client = httpx.Client(
            base_url=url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        )

    def _request(self, method, path, json=None):
        try:
            r = self._client.request(method, path, json=json)
        except httpx.HTTPError as e:
            raise RuntimeError(f"could not reach admin API at {path}: {e}") from e
        if r.status_code == 404:
            # Oracle discipline: every auth failure surfaces as 404 too —
            # we cannot tell "route missing" from "not authorized" apart.
            raise RuntimeError("not found or not authorized")
        if r.status_code == 400:
            raise PolicyEditError(_detail(r))
        if r.status_code >= 400:
            raise RuntimeError(_detail(r))
        return r.json()

    # reads
    def policy_show(self):
        return self._request("GET", "/api/admin/policy")

    def role_list(self):
        data = self._request("GET", "/api/admin/policy")
        return {"roles": (data.get("rbac") or {}).get("roles") or {}}

    def principal_list(self):
        data = self._request("GET", "/api/admin/policy")
        return {"principals": (data.get("rbac") or {}).get("principals") or {}}

    # mutations
    def role_set(self, name, read, write, admin=False):
        return self._request("PUT", f"/api/admin/roles/{name}",
                             json={"read": read, "write": write, "admin": admin})

    def role_rm(self, name):
        return self._request("DELETE", f"/api/admin/roles/{name}")

    def identity_map(self, subject, role):
        return self._request("PUT", f"/api/admin/identities/{subject}",
                             json={"role": role})

    def identity_unmap(self, subject):
        return self._request("DELETE", f"/api/admin/identities/{subject}")

    def principal_set(self, pid, role):
        return self._request("PUT", f"/api/admin/principals/{pid}",
                             json={"role": role})

    def principal_rm(self, pid):
        return self._request("DELETE", f"/api/admin/principals/{pid}")

    def default_role_set(self, role):
        return self._request("PUT", "/api/admin/default-role", json={"role": role})

    # tokens
    def token_mint(self, pid):
        return self._request("POST", f"/api/admin/principals/{pid}/token")

    def token_revoke(self, pid):
        return self._request("DELETE", f"/api/admin/principals/{pid}/token")

    def token_list(self):
        return self._request("GET", "/api/admin/tokens")

    # retrieval log
    def log_query(self, principal=None, kind=None, tool=None, since=None,
                  until=None, path=None, limit=100):
        filters = {
            "principal": principal, "kind": kind, "tool": tool,
            "since": since, "until": until, "path": path, "limit": limit,
        }
        params = {k: v for k, v in filters.items() if v is not None}
        qs = urlencode(params)
        path_and_qs = "/api/admin/retrievals" + (f"?{qs}" if qs else "")
        return self._request("GET", path_and_qs)


# ── Output formatting ───────────────────────────────────────────────────

def _print_commit(result):
    print(result["commit"])


def _print_policy(result):
    print(f"auth_mode:          {result.get('auth_mode')}")
    print(f"credential_backend: {result.get('credential_backend')}")
    rbac = result.get("rbac") or {}
    print(f"default_role:       {rbac.get('default_role')}")
    print("roles:")
    for name, spec in (rbac.get("roles") or {}).items():
        print(f"  {name}: {spec}")
    print("identities:")
    for subject, role in (rbac.get("identities") or {}).items():
        print(f"  {subject} -> {role}")
    print("principals:")
    for pid, role in (rbac.get("principals") or {}).items():
        print(f"  {pid} -> {role}")


def _print_roles(result):
    roles = result.get("roles") or {}
    if not roles:
        print("(no roles defined)")
        return
    for name, spec in roles.items():
        print(f"{name}: {spec}")


def _print_principals(result):
    principals = result.get("principals") or {}
    if not principals:
        print("(no principals defined)")
        return
    for pid, role in principals.items():
        print(f"{pid} -> {role}")


def _print_token_mint(result):
    # The ONLY place a token's plaintext is ever printed.
    print(result["token"])


def _print_token_revoke(result):
    print(f"revoked {result['revoked']} token(s) for {result['principal_id']}")


def _print_token_list(result):
    tokens = result.get("tokens") or []
    if not tokens:
        print("(no tokens)")
        return
    for t in tokens:
        status = "revoked" if t.get("revoked_at") else "active"
        print(f"{t['principal_id']}  {status}  "
              f"created={t.get('created_at')}  revoked={t.get('revoked_at')}")


def _print_retrievals(result):
    entries = result.get("entries") or []
    if not entries:
        print("(no entries)")
        return
    # Already ts-desc from PgRetrievalLog.query — print in that order.
    for e in entries:
        kind = e.get("kind") or ""
        print(f"{e.get('ts')}  {e.get('principal_id')}  {kind:<6}  "
              f"{e.get('tool')}  {e.get('filepath') or ''}  {e.get('subject') or ''}")


# ── argparse ─────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="brain-admin",
        description="Manage brain auth policy: roles, identities, principals, "
                     "and agent tokens. Defaults to the local transport "
                     "(operates on the profile repo directly); pass --url/"
                     "--token (or BRAIN_API_URL/BRAIN_ADMIN_TOKEN) to talk to "
                     "a running brain-api instead.")
    p.add_argument("--url", default=os.environ.get("BRAIN_API_URL", ""),
                   help="Admin API base URL — selects the remote transport. "
                        "Env: BRAIN_API_URL")
    p.add_argument("--token", default=os.environ.get("BRAIN_ADMIN_TOKEN", ""),
                   help="Bearer token for the remote admin API. "
                        "Env: BRAIN_ADMIN_TOKEN")
    sub = p.add_subparsers(dest="command", required=True)

    policy = sub.add_parser("policy", help="Inspect the active policy")
    policy_sub = policy.add_subparsers(dest="policy_cmd", required=True)
    policy_sub.add_parser(
        "show", help="Show auth mode, credential backend, and the full RBAC policy")

    role = sub.add_parser("role", help="Manage roles")
    role_sub = role.add_subparsers(dest="role_cmd", required=True)
    role_sub.add_parser("list", help="List all roles")
    rset = role_sub.add_parser("set", help="Create or update a role")
    rset.add_argument("name", help="Role name")
    rset.add_argument("--read", nargs="+", required=True, metavar="LAYER",
                      help="Layers this role may read (e.g. '*' or a folder name)")
    rset.add_argument("--write", nargs="+", required=True, metavar="LAYER",
                      help="Layers this role may write")
    rset.add_argument("--admin", action="store_true",
                      help="Grant this role access to the admin plane")
    rrm = role_sub.add_parser("rm", help="Remove a role (must be unreferenced)")
    rrm.add_argument("name", help="Role name")

    identity = sub.add_parser("identity", help="Manage OAuth identity -> role mappings")
    identity_sub = identity.add_subparsers(dest="identity_cmd", required=True)
    imap = identity_sub.add_parser("map", help="Map an OAuth subject to a role")
    imap.add_argument("subject", help="OAuth subject (email or sub claim)")
    imap.add_argument("role", help="Role name")
    iunmap = identity_sub.add_parser("unmap", help="Remove an identity mapping")
    iunmap.add_argument("subject", help="OAuth subject")

    principal = sub.add_parser("principal", help="Manage static-bearer principal -> role mappings")
    principal_sub = principal.add_subparsers(dest="principal_cmd", required=True)
    principal_sub.add_parser("list", help="List all principals")
    pset = principal_sub.add_parser("set", help="Map a principal to a role")
    pset.add_argument("pid", help="Principal id")
    pset.add_argument("role", help="Role name")
    prm = principal_sub.add_parser("rm", help="Remove a principal mapping")
    prm.add_argument("pid", help="Principal id")

    token = sub.add_parser("token", help="Manage agent bearer tokens (Postgres credential backend)")
    token_sub = token.add_subparsers(dest="token_cmd", required=True)
    tmint = token_sub.add_parser("mint", help="Mint a new token for a principal (prints it once)")
    tmint.add_argument("pid", help="Principal id (must already be mapped to a role)")
    trevoke = token_sub.add_parser("revoke", help="Revoke all active tokens for a principal")
    trevoke.add_argument("pid", help="Principal id")
    token_sub.add_parser("list", help="List minted tokens (metadata only — never the secret)")

    default_role = sub.add_parser("default-role", help="Manage the fallback role for unmapped identities")
    default_role_sub = default_role.add_subparsers(dest="default_role_cmd", required=True)
    drset = default_role_sub.add_parser("set", help="Set the default role")
    drset.add_argument("role", help="Role name")

    log = sub.add_parser("log", help="Query the per-principal retrieval/audit log")
    log_sub = log.add_subparsers(dest="log_cmd", required=True)
    lquery = log_sub.add_parser(
        "query", help="Query the retrieval log (requires BRAIN_RETRIEVAL_LOG=postgres)")
    lquery.add_argument("--principal", default=None, help="Filter by principal id")
    lquery.add_argument("--kind", default=None, help="Filter by kind (read/write/admin)")
    lquery.add_argument("--tool", default=None, help="Filter by tool name")
    lquery.add_argument("--since", default=None, help="Only entries at/after this timestamp")
    lquery.add_argument("--until", default=None, help="Only entries before this timestamp")
    lquery.add_argument("--path", default=None, help="Filter by filepath substring")
    lquery.add_argument("--limit", type=int, default=100, help="Max rows to return (default 100)")

    return p


def _transport(args):
    if args.url:
        if not args.token:
            raise RuntimeError("--url requires --token (or BRAIN_ADMIN_TOKEN)")
        return RemoteTransport(args.url, args.token)
    return LocalTransport(Config())


def _dispatch(args, t):
    cmd = args.command
    if cmd == "policy":
        return t.policy_show(), _print_policy
    if cmd == "role":
        if args.role_cmd == "list":
            return t.role_list(), _print_roles
        if args.role_cmd == "set":
            return t.role_set(args.name, args.read, args.write, admin=args.admin), _print_commit
        if args.role_cmd == "rm":
            return t.role_rm(args.name), _print_commit
    if cmd == "identity":
        if args.identity_cmd == "map":
            return t.identity_map(args.subject, args.role), _print_commit
        if args.identity_cmd == "unmap":
            return t.identity_unmap(args.subject), _print_commit
    if cmd == "principal":
        if args.principal_cmd == "list":
            return t.principal_list(), _print_principals
        if args.principal_cmd == "set":
            return t.principal_set(args.pid, args.role), _print_commit
        if args.principal_cmd == "rm":
            return t.principal_rm(args.pid), _print_commit
    if cmd == "token":
        if args.token_cmd == "mint":
            return t.token_mint(args.pid), _print_token_mint
        if args.token_cmd == "revoke":
            return t.token_revoke(args.pid), _print_token_revoke
        if args.token_cmd == "list":
            return t.token_list(), _print_token_list
    if cmd == "default-role":
        if args.default_role_cmd == "set":
            return t.default_role_set(args.role), _print_commit
    if cmd == "log":
        if args.log_cmd == "query":
            return t.log_query(principal=args.principal, kind=args.kind, tool=args.tool,
                               since=args.since, until=args.until, path=args.path,
                               limit=args.limit), _print_retrievals
    raise AssertionError(f"unhandled command: {cmd} {vars(args)}")


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        t = _transport(args)
        result, printer = _dispatch(args, t)
    except PolicyEditError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"Error (infra): {e}", file=sys.stderr)
        return 1
    printer(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
