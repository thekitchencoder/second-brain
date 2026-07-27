"""Admin REST surface — /api/admin/* — owner-gated policy edits + token mint/revoke.

Security-critical gate: every failure mode short of an authenticated admin
principal (mode=none, unauthenticated, authenticated-but-not-admin) must
return the SAME 404 an unknown route would produce (oracle-safety).
"""
import json
import sys
import textwrap
from unittest.mock import MagicMock

if "sqlite_vec" not in sys.modules:
    sys.modules["sqlite_vec"] = MagicMock()
if "openai" not in sys.modules:
    sys.modules["openai"] = MagicMock()

import pytest
from fastapi.testclient import TestClient

from lib.policy_edit import PolicyEditError


def _make_brain(tmp_path, auth_block=""):
    brain = tmp_path / "brain"
    (brain / ".ai").mkdir(parents=True)
    (brain / ".zk" / "templates").mkdir(parents=True)
    (brain / ".zk" / "templates" / "default.md").write_text("---\ntitle: {{title}}\n---\n")
    pdir = brain / ".brain"
    pdir.mkdir()
    (pdir / "profile.toml").write_text(textwrap.dedent('''\
        name = "ace"
        folders = ["Cards"]
        [plugin]
        name = "second-brain"
        author = "kitchencoder"
        marker = "brain"
    ''') + auth_block)
    return brain


# Two static-bearer principals: "helper" maps to a non-admin role, "root"
# maps to a role with admin = true.
_ADMIN_OAUTH = textwrap.dedent('''\
    [auth]
    mode = "oauth"

    [auth.rbac.roles.maker]
    read = ["*"]
    write = ["*"]

    [auth.rbac.roles.owner]
    read = ["*"]
    write = ["*"]
    admin = true

    [auth.rbac.principals]
    helper = "maker"
    root = "owner"
''')


def _signing_key() -> str:
    """A real RSA PEM — oauth mode hard-fails without BRAIN_AUTH_SIGNING_KEY."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    return rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()).decode()


def _client(monkeypatch, brain):
    """Reload brain_api against `brain` and return the (fresh) module."""
    monkeypatch.setenv("BRAIN_PATH", str(brain))
    import importlib
    import brain_api
    importlib.reload(brain_api)
    return brain_api


def _oauth_client(monkeypatch, tmp_path):
    monkeypatch.setenv("BRAIN_AUTH_PRINCIPAL_TOKENS",
                       json.dumps({"helper": "helper-secret", "root": "root-secret"}))
    monkeypatch.setenv("BRAIN_AUTH_SIGNING_KEY", _signing_key())
    brain = _make_brain(tmp_path, _ADMIN_OAUTH)
    api = _client(monkeypatch, brain)
    return api, TestClient(api.app)


ADMIN_AUTH = {"Authorization": "Bearer root-secret"}
NON_ADMIN_AUTH = {"Authorization": "Bearer helper-secret"}


# ── Gate behavior (the security surface) ──────────────────────────────


def test_admin_routes_404_under_mode_none(monkeypatch, tmp_path):
    brain = _make_brain(tmp_path)  # no [auth] block -> mode defaults to "none"
    api = _client(monkeypatch, brain)
    client = TestClient(api.app)
    assert client.get("/api/admin/policy").status_code == 404


def test_admin_routes_404_for_non_admin_principal(monkeypatch, tmp_path):
    _api, client = _oauth_client(monkeypatch, tmp_path)
    r = client.get("/api/admin/policy", headers=NON_ADMIN_AUTH)
    assert r.status_code == 404


def test_admin_routes_404_unauthenticated_oauth(monkeypatch, tmp_path):
    _api, client = _oauth_client(monkeypatch, tmp_path)
    # Settled as 404 (not 401) for oracle-consistency: an unauthenticated
    # caller must see the exact same response as a non-admin principal and
    # as mode=none — never a distinguishing signal.
    assert client.get("/api/admin/policy").status_code == 404


def test_admin_mutation_404_for_non_admin(monkeypatch, tmp_path):
    """The gate is uniform across the whole admin plane, not just GET."""
    _api, client = _oauth_client(monkeypatch, tmp_path)
    r = client.put("/api/admin/roles/maker",
                   json={"read": ["*"], "write": ["*"], "admin": False},
                   headers=NON_ADMIN_AUTH)
    assert r.status_code == 404


def test_admin_policy_visible_to_admin_role(monkeypatch, tmp_path):
    _api, client = _oauth_client(monkeypatch, tmp_path)
    r = client.get("/api/admin/policy", headers=ADMIN_AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["rbac"]["roles"]  # effective policy echoed
    assert body["auth_mode"] == "oauth"


# ── Mutations (PolicyEditor mocked — its own tests own git) ───────────


def test_role_put_calls_editor_and_returns_sha(monkeypatch, tmp_path):
    api, client = _oauth_client(monkeypatch, tmp_path)
    fake_editor = MagicMock()
    fake_editor.role_set.return_value = "abc1234"
    monkeypatch.setattr(api, "_editor", lambda: fake_editor)
    r = client.put("/api/admin/roles/maker",
                   json={"read": ["*"], "write": ["*"], "admin": True},
                   headers=ADMIN_AUTH)
    assert r.status_code == 200 and r.json()["commit"] == "abc1234"
    fake_editor.role_set.assert_called_once_with("maker", ["*"], ["*"], True)


def test_role_put_invalidates_policy_cache(monkeypatch, tmp_path):
    api, client = _oauth_client(monkeypatch, tmp_path)
    fake_editor = MagicMock()
    fake_editor.role_set.return_value = "abc1234"
    monkeypatch.setattr(api, "_editor", lambda: fake_editor)
    calls = []
    monkeypatch.setattr(api._policy, "invalidate", lambda: calls.append(1))
    client.put("/api/admin/roles/maker",
              json={"read": ["*"], "write": ["*"], "admin": True},
              headers=ADMIN_AUTH)
    assert calls == [1]


def test_role_put_validation_error_is_400(monkeypatch, tmp_path):
    api, client = _oauth_client(monkeypatch, tmp_path)
    fake_editor = MagicMock()
    fake_editor.role_set.side_effect = PolicyEditError("read/write must be lists of layer strings")
    monkeypatch.setattr(api, "_editor", lambda: fake_editor)
    r = client.put("/api/admin/roles/maker",
                   json={"read": ["*"], "write": ["*"], "admin": True},
                   headers=ADMIN_AUTH)
    assert r.status_code == 400
    assert "read/write must be lists" in r.json()["detail"]


def test_role_delete_calls_editor(monkeypatch, tmp_path):
    api, client = _oauth_client(monkeypatch, tmp_path)
    fake_editor = MagicMock()
    fake_editor.role_rm.return_value = "def5678"
    monkeypatch.setattr(api, "_editor", lambda: fake_editor)
    r = client.delete("/api/admin/roles/maker", headers=ADMIN_AUTH)
    assert r.status_code == 200 and r.json()["commit"] == "def5678"
    fake_editor.role_rm.assert_called_once_with("maker")


def test_identity_map_and_unmap(monkeypatch, tmp_path):
    api, client = _oauth_client(monkeypatch, tmp_path)
    fake_editor = MagicMock()
    fake_editor.identity_map.return_value = "sha1"
    fake_editor.identity_unmap.return_value = "sha2"
    monkeypatch.setattr(api, "_editor", lambda: fake_editor)
    r = client.put("/api/admin/identities/chris@example.com",
                   json={"role": "maker"}, headers=ADMIN_AUTH)
    assert r.status_code == 200 and r.json()["commit"] == "sha1"
    fake_editor.identity_map.assert_called_once_with("chris@example.com", "maker")

    r = client.delete("/api/admin/identities/chris@example.com", headers=ADMIN_AUTH)
    assert r.status_code == 200 and r.json()["commit"] == "sha2"
    fake_editor.identity_unmap.assert_called_once_with("chris@example.com")


def test_principal_set_and_rm(monkeypatch, tmp_path):
    api, client = _oauth_client(monkeypatch, tmp_path)
    fake_editor = MagicMock()
    fake_editor.principal_set.return_value = "sha3"
    fake_editor.principal_rm.return_value = "sha4"
    monkeypatch.setattr(api, "_editor", lambda: fake_editor)
    r = client.put("/api/admin/principals/fenn-desk",
                   json={"role": "maker"}, headers=ADMIN_AUTH)
    assert r.status_code == 200 and r.json()["commit"] == "sha3"
    fake_editor.principal_set.assert_called_once_with("fenn-desk", "maker")

    r = client.delete("/api/admin/principals/fenn-desk", headers=ADMIN_AUTH)
    assert r.status_code == 200 and r.json()["commit"] == "sha4"
    fake_editor.principal_rm.assert_called_once_with("fenn-desk")


# ── Tokens (PgCredentialStore mocked) ──────────────────────────────────


def test_token_mint_returns_plaintext_once(monkeypatch, tmp_path):
    # _credentials() is monkeypatched wholesale below, so the real
    # BRAIN_POLICY_CREDENTIALS gate never runs here (it's covered by
    # test_token_mint_503_when_credentials_env instead). Leaving it unset
    # also keeps _policy's OWN credential verification (of ADMIN_AUTH's
    # static bearer token) on the fast env backend rather than routing
    # through a real Postgres connection attempt.
    api, client = _oauth_client(monkeypatch, tmp_path)
    fake_store = MagicMock()
    fake_store.mint.return_value = "plaintext-token-xyz"
    monkeypatch.setattr(api, "_credentials", lambda: fake_store)
    r = client.post("/api/admin/principals/helper/token", headers=ADMIN_AUTH)
    assert r.status_code == 200
    assert r.json()["token"] == "plaintext-token-xyz"
    fake_store.mint.assert_called_once_with("helper")


def test_token_mint_requires_principal_in_rbac(monkeypatch, tmp_path):
    api, client = _oauth_client(monkeypatch, tmp_path)
    fake_store = MagicMock()
    monkeypatch.setattr(api, "_credentials", lambda: fake_store)
    r = client.post("/api/admin/principals/ghost/token", headers=ADMIN_AUTH)
    assert r.status_code == 400
    fake_store.mint.assert_not_called()


def test_token_revoke(monkeypatch, tmp_path):
    api, client = _oauth_client(monkeypatch, tmp_path)
    fake_store = MagicMock()
    fake_store.revoke.return_value = 1
    monkeypatch.setattr(api, "_credentials", lambda: fake_store)
    r = client.delete("/api/admin/principals/helper/token", headers=ADMIN_AUTH)
    assert r.status_code == 200
    assert r.json()["revoked"] == 1
    fake_store.revoke.assert_called_once_with("helper")


def test_token_routes_share_one_store_per_dsn(monkeypatch, tmp_path):
    # F1 regression: _credentials() must not construct a fresh
    # PgCredentialStore (and its connection pool) on every admin request —
    # repeated calls within a process should resolve to the same store.
    api, client = _oauth_client(monkeypatch, tmp_path)
    monkeypatch.setenv("BRAIN_POLICY_CREDENTIALS", "postgres")
    api._cfg.database_url = "postgresql://u:p@h:5432/brain"

    import lib.credentials as credentials
    created = []

    class _StubStore:
        def __init__(self, dsn):
            created.append(dsn)

        def mint(self, pid):
            return f"token-for-{pid}"

        def list_tokens(self):
            return []

    monkeypatch.setattr(credentials, "PgCredentialStore", _StubStore)
    monkeypatch.setattr(credentials, "_stores", {}, raising=True)

    r1 = client.post("/api/admin/principals/helper/token", headers=ADMIN_AUTH)
    r2 = client.get("/api/admin/tokens", headers=ADMIN_AUTH)
    assert r1.status_code == 200 and r2.status_code == 200
    assert len(created) == 1


def test_token_mint_503_when_credentials_env(monkeypatch, tmp_path):
    monkeypatch.delenv("BRAIN_POLICY_CREDENTIALS", raising=False)  # default "env"
    _api, client = _oauth_client(monkeypatch, tmp_path)
    r = client.post("/api/admin/principals/helper/token", headers=ADMIN_AUTH)
    assert r.status_code == 503
    assert "BRAIN_POLICY_CREDENTIALS" in r.json()["detail"]


def test_token_list_route_returns_rows(monkeypatch, tmp_path):
    api, client = _oauth_client(monkeypatch, tmp_path)
    fake_store = MagicMock()
    fake_store.list_tokens.return_value = [
        {"principal_id": "helper", "created_at": "2026-01-01", "revoked_at": None},
    ]
    monkeypatch.setattr(api, "_credentials", lambda: fake_store)
    r = client.get("/api/admin/tokens", headers=ADMIN_AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body == {"tokens": [
        {"principal_id": "helper", "created_at": "2026-01-01", "revoked_at": None},
    ]}
    dumped = json.dumps(body)
    assert "hash" not in dumped.lower()


def test_token_list_404_for_non_admin(monkeypatch, tmp_path):
    _api, client = _oauth_client(monkeypatch, tmp_path)
    r = client.get("/api/admin/tokens", headers=NON_ADMIN_AUTH)
    assert r.status_code == 404


def test_default_role_put_calls_editor(monkeypatch, tmp_path):
    api, client = _oauth_client(monkeypatch, tmp_path)
    fake_editor = MagicMock()
    fake_editor.default_role_set.return_value = "sha9"
    monkeypatch.setattr(api, "_editor", lambda: fake_editor)
    r = client.put("/api/admin/default-role", json={"role": "maker"}, headers=ADMIN_AUTH)
    assert r.status_code == 200 and r.json()["commit"] == "sha9"
    fake_editor.default_role_set.assert_called_once_with("maker")


# ── Route-existence oracles above the endpoint layer ───────────────────
# The router resolves 405 (method mismatch) and 307/308 (trailing-slash
# redirect) BEFORE the _require_admin dependency ever runs, so an
# unauthenticated caller could otherwise map which admin routes exist
# without any valid credential. The _admin_oracle_guard middleware must
# normalize both to the same 404 an absent route produces, scoped
# strictly to /api/admin so the rest of the API is unaffected.


def test_admin_method_mismatch_is_404_not_405(monkeypatch, tmp_path):
    # Unauthenticated caller — the oracle must be closed before auth even runs.
    _api, client = _oauth_client(monkeypatch, tmp_path)
    assert client.post("/api/admin/policy").status_code == 404
    assert client.get("/api/admin/roles/maker").status_code == 404
    assert client.request("OPTIONS", "/api/admin/roles/maker").status_code == 404


def test_admin_trailing_slash_is_404_not_redirect(monkeypatch, tmp_path):
    _api, client = _oauth_client(monkeypatch, tmp_path)
    r = client.get("/api/admin/policy/", follow_redirects=False)
    assert r.status_code == 404


def test_admin_404_body_matches_absent_route(monkeypatch, tmp_path):
    _api, client = _oauth_client(monkeypatch, tmp_path)
    absent = client.post("/api/admin/nonexistent")
    gated = client.post("/api/admin/policy")
    assert gated.status_code == absent.status_code == 404
    assert gated.json() == absent.json()


def test_non_admin_paths_keep_405(monkeypatch, tmp_path):
    # Existing surface is unchanged outside /api/admin: an existing GET-only
    # route still 405s on the wrong method — proves the middleware is scoped
    # to the admin prefix rather than blanket-normalizing every route.
    brain = _make_brain(tmp_path)  # mode="none" — no auth needed for the 405 check
    api = _client(monkeypatch, brain)
    client = TestClient(api.app)
    assert client.post("/api/search").status_code == 405


# ── Fail-closed on malformed policy config ─────────────────────────────


_BROKEN_ROLE_OAUTH = textwrap.dedent('''\
    [auth]
    mode = "oauth"

    [auth.rbac.roles]
    broken = "notadict"

    [auth.rbac.principals]
    ghost = "broken"
''')


def test_is_admin_non_dict_role_spec_fails_closed(monkeypatch, tmp_path):
    # Hand-corrupted TOML (roles.broken = "notadict" instead of a table).
    # A principal mapped to that role must fail closed with the standard
    # oracle-safe 404 — never a 500 that would distinguish "malformed role"
    # from "route doesn't exist" or "not admin".
    monkeypatch.setenv("BRAIN_AUTH_PRINCIPAL_TOKENS", json.dumps({"ghost": "ghost-secret"}))
    monkeypatch.setenv("BRAIN_AUTH_SIGNING_KEY", _signing_key())
    brain = _make_brain(tmp_path, _BROKEN_ROLE_OAUTH)
    api = _client(monkeypatch, brain)
    client = TestClient(api.app)
    r = client.get("/api/admin/policy", headers={"Authorization": "Bearer ghost-secret"})
    assert r.status_code == 404


# ── Retrieval log query surface (slice 3) ──────────────────────────────
# Reading the log is deliberately NOT itself logged as an admin event —
# see the comment above admin_retrievals in brain_api.py.


def _retrieval_log_client(monkeypatch, tmp_path):
    monkeypatch.setenv("BRAIN_RETRIEVAL_LOG", "postgres")
    monkeypatch.setenv("BRAIN_DATABASE_URL", "postgresql://x/y")
    return _oauth_client(monkeypatch, tmp_path)


def test_retrievals_route_passes_filters(monkeypatch, tmp_path):
    api, client = _retrieval_log_client(monkeypatch, tmp_path)
    fake_log = MagicMock()
    fake_log.query.return_value = [
        {"ts": "2026-01-01T00:00:00+00:00", "principal_id": "x", "kind": "read",
         "tool": "brain_search", "subject": None, "filepath": "a/b.md", "request_id": None},
    ]
    import lib.retrieval_log as retrieval_log
    monkeypatch.setattr(retrieval_log, "get_retrieval_log", lambda dsn: fake_log)
    r = client.get("/api/admin/retrievals", params={
        "principal": "x", "kind": "read", "tool": "brain_search",
        "since": "2026-01-01", "until": "2026-12-31", "path": "a", "limit": 5,
    }, headers=ADMIN_AUTH)
    assert r.status_code == 200
    assert r.json() == {"entries": fake_log.query.return_value}
    fake_log.query.assert_called_once_with(
        principal="x", kind="read", tool="brain_search",
        since="2026-01-01", until="2026-12-31", path="a", limit=5)


def test_retrievals_route_404_for_non_admin(monkeypatch, tmp_path):
    _api, client = _retrieval_log_client(monkeypatch, tmp_path)
    r = client.get("/api/admin/retrievals", headers=NON_ADMIN_AUTH)
    assert r.status_code == 404


def test_retrievals_route_503_when_log_off(monkeypatch, tmp_path):
    monkeypatch.delenv("BRAIN_RETRIEVAL_LOG", raising=False)
    _api, client = _oauth_client(monkeypatch, tmp_path)
    r = client.get("/api/admin/retrievals", headers=ADMIN_AUTH)
    assert r.status_code == 503
    assert "BRAIN_RETRIEVAL_LOG=postgres" in r.json()["detail"]


def test_retrievals_route_does_not_log_itself_as_admin_event(monkeypatch, tmp_path):
    api, client = _retrieval_log_client(monkeypatch, tmp_path)
    fake_log = MagicMock()
    fake_log.query.return_value = []
    import lib.retrieval_log as retrieval_log
    monkeypatch.setattr(retrieval_log, "get_retrieval_log", lambda dsn: fake_log)
    calls = []
    monkeypatch.setattr(api, "safe_log_admin", lambda *a, **kw: calls.append((a, kw)))
    r = client.get("/api/admin/retrievals", headers=ADMIN_AUTH)
    assert r.status_code == 200
    assert calls == []
