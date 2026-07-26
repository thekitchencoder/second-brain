import sys
from unittest.mock import MagicMock

if "sqlite_vec" not in sys.modules:
    sys.modules["sqlite_vec"] = MagicMock()
if "openai" not in sys.modules:
    sys.modules["openai"] = MagicMock()

# add to tests/test_oauth_endpoints.py — reuse the _make_brain/_client helpers.
# Import them from the api-auth test module to avoid duplication:
from tests.test_brain_api_auth import _make_brain, _client, _OAUTH
import json


def _oauth_env(monkeypatch, tmp_path):
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()).decode()
    monkeypatch.setenv("BRAIN_AUTH_ISSUER", "https://brain.example")
    monkeypatch.setenv("BRAIN_AUTH_AUDIENCE", "https://brain.example/mcp")
    monkeypatch.setenv("BRAIN_AUTH_SIGNING_KEY", key)
    monkeypatch.setenv("BRAIN_AUTH_PRINCIPAL_TOKENS", json.dumps({"agent": "s3cret"}))
    return _make_brain(tmp_path, _OAUTH)


def test_dcr_register(monkeypatch, tmp_path):
    brain = _oauth_env(monkeypatch, tmp_path)
    client = _client(monkeypatch, brain)
    r = client.post("/register", json={"redirect_uris": ["https://claude.ai/cb"],
                                       "client_name": "Claude"})
    assert r.status_code == 201
    assert r.json()["client_id"]


def test_dcr_rejects_non_https_redirect(monkeypatch, tmp_path):
    brain = _oauth_env(monkeypatch, tmp_path)
    client = _client(monkeypatch, brain)
    r = client.post("/register", json={"redirect_uris": ["http://evil.example/cb"]})
    assert r.status_code == 400


def test_dcr_rejects_loopback_prefix_bypass(monkeypatch, tmp_path):
    brain = _oauth_env(monkeypatch, tmp_path)
    client = _client(monkeypatch, brain)
    for bad in ["http://localhost.evil.com/cb", "http://127.0.0.1.evil.com/cb",
                "http://127.0.0.1@evil.com/cb"]:
        r = client.post("/register", json={"redirect_uris": [bad]})
        assert r.status_code == 400, bad


def test_dcr_still_accepts_real_loopback(monkeypatch, tmp_path):
    brain = _oauth_env(monkeypatch, tmp_path)
    client = _client(monkeypatch, brain)
    r = client.post("/register", json={"redirect_uris": ["http://localhost:8080/cb"]})
    assert r.status_code == 201


def test_client_store_registers_and_persists(tmp_path):
    from lib.oauth_server import ClientStore
    path = tmp_path / "oauth-clients.json"
    store = ClientStore(str(path))
    reg = store.register({"redirect_uris": ["https://claude.ai/cb"], "client_name": "Claude"})
    assert reg["client_id"]
    assert reg["redirect_uris"] == ["https://claude.ai/cb"]
    # persisted + reloadable
    store2 = ClientStore(str(path))
    assert store2.get(reg["client_id"])["client_name"] == "Claude"


def test_client_store_survives_corrupt_file(tmp_path):
    """FIX 3: a corrupt (non-JSON) oauth-clients.json must not crash construction —
    it should log/ignore and start empty rather than bricking startup."""
    from lib.oauth_server import ClientStore
    path = tmp_path / "oauth-clients.json"
    path.write_text("{not valid json::")
    store = ClientStore(str(path))
    assert store.all() == []
    # and it's still usable afterwards
    reg = store.register({"redirect_uris": ["https://claude.ai/cb"]})
    assert reg["client_id"]


def test_client_store_defaults_public_pkce(tmp_path):
    from lib.oauth_server import ClientStore
    store = ClientStore(str(tmp_path / "c.json"))
    reg = store.register({"redirect_uris": ["https://x/cb"]})
    assert reg["token_endpoint_auth_method"] == "none"
    assert "authorization_code" in reg["grant_types"]


def test_refresh_store_issue_get_revoke(tmp_path):
    from lib.oauth_server import RefreshStore
    s = RefreshStore(str(tmp_path / "r.json"))
    jti, exp = s.issue("u@e.com", "c1", ttl=100)
    assert s.get(jti)["subject"] == "u@e.com"
    s.revoke(jti)
    assert s.get(jti)["revoked"] is True


def test_refresh_store_rotate_retires_old(tmp_path):
    from lib.oauth_server import RefreshStore
    s = RefreshStore(str(tmp_path / "r.json"))
    old, _ = s.issue("u@e.com", "c1", ttl=100)
    new, _ = s.rotate(old, "u@e.com", "c1", ttl=100)
    assert s.get(old)["revoked"] is True
    assert s.get(new)["revoked"] is False and new != old


def test_refresh_store_revoke_all_for(tmp_path):
    from lib.oauth_server import RefreshStore
    s = RefreshStore(str(tmp_path / "r.json"))
    a, _ = s.issue("u@e.com", "c1", ttl=100)
    b, _ = s.issue("u@e.com", "c1", ttl=100)
    c, _ = s.issue("other@e.com", "c1", ttl=100)
    s.revoke_all_for("u@e.com", "c1")
    assert s.get(a)["revoked"] and s.get(b)["revoked"]
    assert s.get(c)["revoked"] is False


def test_refresh_store_survives_corrupt_file(tmp_path):
    p = tmp_path / "r.json"
    p.write_text("{ not json")
    from lib.oauth_server import RefreshStore
    s = RefreshStore(str(p))          # must not raise
    assert s.get("anything") is None


import base64
import hashlib


def _pkce():
    verifier = base64.urlsafe_b64encode(b"0" * 40).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def test_authorize_requires_s256(monkeypatch, tmp_path):
    brain = _oauth_env(monkeypatch, tmp_path)
    client = _client(monkeypatch, brain)
    reg = client.post("/register", json={"redirect_uris": ["https://claude.ai/cb"]}).json()
    r = client.get("/authorize", params={
        "response_type": "code", "client_id": reg["client_id"],
        "redirect_uri": "https://claude.ai/cb", "state": "xyz",
    }, follow_redirects=False)
    assert r.status_code == 400  # missing code_challenge


def test_token_exchange_with_pkce(monkeypatch, tmp_path):
    """Drive the code path directly: stub the upstream so no network is needed."""
    import brain_api, importlib
    brain = _oauth_env(monkeypatch, tmp_path)
    monkeypatch.setenv("BRAIN_PATH", str(brain))
    importlib.reload(brain_api)
    from fastapi.testclient import TestClient
    client = TestClient(brain_api.app)

    reg = client.post("/register", json={"redirect_uris": ["https://claude.ai/cb"]}).json()
    verifier, challenge = _pkce()

    # Mint a code as the callback would after successful upstream login.
    from lib.oauth_server import issue_auth_code
    code = issue_auth_code(brain_api._auth_state, client_id=reg["client_id"],
                           redirect_uri="https://claude.ai/cb",
                           code_challenge=challenge, subject="chris@example.com")

    r = client.post("/token", data={
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": "https://claude.ai/cb", "client_id": reg["client_id"],
        "code_verifier": verifier,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "Bearer"
    claims = brain_api._auth_settings.validate_jwt(body["access_token"])
    assert claims["sub"] == "chris@example.com"


def test_pending_expiry_is_not_honoured(monkeypatch, tmp_path):
    """FIX 1: pending entries stashed with a negative ttl are already expired —
    pop_pending must not return them, and the sweep must actually remove them
    from the dict (bounding memory rather than leaving dead entries forever)."""
    from lib.oauth_server import AuthState
    state = AuthState()
    state.stash_pending("expired-state", ttl=-1, client_id="c", redirect_uri="https://x/cb",
                        code_challenge="ch", client_state="s")
    assert "expired-state" in state.pending  # present until swept/popped
    assert state.pop_pending("expired-state") is None  # but not honoured
    assert "expired-state" not in state.pending  # and removed by the pop

    # A second stash (which sweeps first) must not resurrect a stale expired
    # entry for an unrelated state either.
    state.stash_pending("expired-2", ttl=-1, client_id="c", redirect_uri="https://x/cb",
                        code_challenge="ch", client_state="s")
    state.stash_pending("fresh", ttl=600, client_id="c", redirect_uri="https://x/cb",
                        code_challenge="ch", client_state="s")
    assert "expired-2" not in state.pending
    assert "fresh" in state.pending


def test_auth_code_is_single_use(monkeypatch, tmp_path):
    """FIX 6: redeeming a valid code once succeeds; replaying the same code
    must be rejected (400) — the code must not be redeemable twice."""
    import brain_api, importlib
    brain = _oauth_env(monkeypatch, tmp_path)
    monkeypatch.setenv("BRAIN_PATH", str(brain))
    importlib.reload(brain_api)
    from fastapi.testclient import TestClient
    client = TestClient(brain_api.app)

    reg = client.post("/register", json={"redirect_uris": ["https://claude.ai/cb"]}).json()
    verifier, challenge = _pkce()

    from lib.oauth_server import issue_auth_code
    code = issue_auth_code(brain_api._auth_state, client_id=reg["client_id"],
                           redirect_uri="https://claude.ai/cb",
                           code_challenge=challenge, subject="chris@example.com")

    token_req = {
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": "https://claude.ai/cb", "client_id": reg["client_id"],
        "code_verifier": verifier,
    }
    first = client.post("/token", data=token_req)
    assert first.status_code == 200

    second = client.post("/token", data=token_req)
    assert second.status_code == 400


def test_token_rejects_bad_verifier(monkeypatch, tmp_path):
    import brain_api, importlib
    brain = _oauth_env(monkeypatch, tmp_path)
    monkeypatch.setenv("BRAIN_PATH", str(brain))
    importlib.reload(brain_api)
    from fastapi.testclient import TestClient
    client = TestClient(brain_api.app)
    reg = client.post("/register", json={"redirect_uris": ["https://claude.ai/cb"]}).json()
    _, challenge = _pkce()
    from lib.oauth_server import issue_auth_code
    code = issue_auth_code(brain_api._auth_state, client_id=reg["client_id"],
                           redirect_uri="https://claude.ai/cb",
                           code_challenge=challenge, subject="chris@example.com")
    r = client.post("/token", data={
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": "https://claude.ai/cb", "client_id": reg["client_id"],
        "code_verifier": "wrong-verifier",
    })
    assert r.status_code == 400


def test_consent_approve_mints_code(monkeypatch, tmp_path):
    import brain_api, importlib
    brain = _oauth_env(monkeypatch, tmp_path)
    monkeypatch.setenv("BRAIN_PATH", str(brain))
    importlib.reload(brain_api)
    from fastapi.testclient import TestClient
    client = TestClient(brain_api.app)
    reg = client.post("/register", json={"redirect_uris": ["https://claude.ai/cb"]}).json()

    ticket = brain_api._auth_settings.issue_consent({
        "client_id": reg["client_id"], "redirect_uri": "https://claude.ai/cb",
        "code_challenge": "abc", "client_state": "xyz", "subject": "u@e.com"})
    r = client.post("/consent", data={"ticket": ticket, "decision": "approve"},
                    follow_redirects=False)
    assert r.status_code == 303
    loc = r.headers["location"]
    assert loc.startswith("https://claude.ai/cb") and "code=" in loc and "state=xyz" in loc


def test_consent_deny_returns_error(monkeypatch, tmp_path):
    import brain_api, importlib
    brain = _oauth_env(monkeypatch, tmp_path)
    monkeypatch.setenv("BRAIN_PATH", str(brain))
    importlib.reload(brain_api)
    from fastapi.testclient import TestClient
    client = TestClient(brain_api.app)
    reg = client.post("/register", json={"redirect_uris": ["https://claude.ai/cb"]}).json()
    ticket = brain_api._auth_settings.issue_consent({
        "client_id": reg["client_id"], "redirect_uri": "https://claude.ai/cb",
        "code_challenge": "abc", "client_state": "xyz", "subject": "u@e.com"})
    r = client.post("/consent", data={"ticket": ticket, "decision": "deny"},
                    follow_redirects=False)
    assert r.status_code == 303
    assert "error=access_denied" in r.headers["location"]


def test_consent_invalid_ticket_400(monkeypatch, tmp_path):
    import brain_api, importlib
    brain = _oauth_env(monkeypatch, tmp_path)
    monkeypatch.setenv("BRAIN_PATH", str(brain))
    importlib.reload(brain_api)
    from fastapi.testclient import TestClient
    client = TestClient(brain_api.app)
    r = client.post("/consent", data={"ticket": "garbage", "decision": "approve"},
                    follow_redirects=False)
    assert r.status_code == 400


def test_consent_page_has_clickjacking_headers(monkeypatch, tmp_path):
    import brain_api, importlib
    brain = _oauth_env(monkeypatch, tmp_path)
    monkeypatch.setenv("BRAIN_PATH", str(brain))
    importlib.reload(brain_api)
    resp = brain_api._consent_page("tk", "SomeClient", "https://claude.ai/cb", "u@e.com")
    assert resp.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in resp.headers["content-security-policy"]
    assert resp.headers["cache-control"] == "no-store"


def _first_refresh(client, brain_api, reg, verifier, challenge):
    from lib.oauth_server import issue_auth_code
    code = issue_auth_code(brain_api._auth_state, client_id=reg["client_id"],
                           redirect_uri="https://claude.ai/cb",
                           code_challenge=challenge, subject="u@e.com")
    r = client.post("/token", data={"grant_type": "authorization_code", "code": code,
                                    "redirect_uri": "https://claude.ai/cb",
                                    "client_id": reg["client_id"], "code_verifier": verifier})
    assert r.status_code == 200
    return r.json()["refresh_token"]


def _setup(monkeypatch, tmp_path):
    import brain_api, importlib
    brain = _oauth_env(monkeypatch, tmp_path)
    monkeypatch.setenv("BRAIN_PATH", str(brain))
    importlib.reload(brain_api)
    from fastapi.testclient import TestClient
    client = TestClient(brain_api.app)
    reg = client.post("/register", json={"redirect_uris": ["https://claude.ai/cb"]}).json()
    return brain_api, client, reg


def test_refresh_rotates_and_retires_old(monkeypatch, tmp_path):
    brain_api, client, reg = _setup(monkeypatch, tmp_path)
    verifier, challenge = _pkce()
    rt1 = _first_refresh(client, brain_api, reg, verifier, challenge)
    r = client.post("/token", data={"grant_type": "refresh_token",
                                    "refresh_token": rt1, "client_id": reg["client_id"]})
    assert r.status_code == 200
    rt2 = r.json()["refresh_token"]
    assert rt2 and rt2 != rt1
    # rt1 is now retired
    r2 = client.post("/token", data={"grant_type": "refresh_token",
                                     "refresh_token": rt1, "client_id": reg["client_id"]})
    assert r2.status_code == 400


def test_refresh_reuse_revokes_chain(monkeypatch, tmp_path):
    brain_api, client, reg = _setup(monkeypatch, tmp_path)
    verifier, challenge = _pkce()
    rt1 = _first_refresh(client, brain_api, reg, verifier, challenge)
    rt2 = client.post("/token", data={"grant_type": "refresh_token", "refresh_token": rt1,
                                      "client_id": reg["client_id"]}).json()["refresh_token"]
    # replay the retired rt1 → theft signal → whole chain revoked
    assert client.post("/token", data={"grant_type": "refresh_token", "refresh_token": rt1,
                                       "client_id": reg["client_id"]}).status_code == 400
    # rt2 (the live one) is now also dead
    assert client.post("/token", data={"grant_type": "refresh_token", "refresh_token": rt2,
                                       "client_id": reg["client_id"]}).status_code == 400


def test_refresh_wrong_client_rejected(monkeypatch, tmp_path):
    brain_api, client, reg = _setup(monkeypatch, tmp_path)
    verifier, challenge = _pkce()
    rt1 = _first_refresh(client, brain_api, reg, verifier, challenge)
    r = client.post("/token", data={"grant_type": "refresh_token", "refresh_token": rt1,
                                    "client_id": "someone-else"})
    assert r.status_code == 400


def test_access_token_not_accepted_as_refresh(monkeypatch, tmp_path):
    brain_api, client, reg = _setup(monkeypatch, tmp_path)
    access = brain_api._auth_settings.issue_jwt("u@e.com", {"email": "u@e.com"})
    r = client.post("/token", data={"grant_type": "refresh_token", "refresh_token": access,
                                    "client_id": reg["client_id"]})
    assert r.status_code == 400


def test_token_cap_returns_503_not_500(monkeypatch, tmp_path):
    import lib.oauth_server as osrv
    brain_api, client, reg = _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(osrv, "MAX_REFRESH", 0)   # any issue() now hits the cap
    verifier, challenge = _pkce()
    from lib.oauth_server import issue_auth_code
    code = issue_auth_code(brain_api._auth_state, client_id=reg["client_id"],
                           redirect_uri="https://claude.ai/cb",
                           code_challenge=challenge, subject="u@e.com")
    r = client.post("/token", data={"grant_type": "authorization_code", "code": code,
                                    "redirect_uri": "https://claude.ai/cb",
                                    "client_id": reg["client_id"], "code_verifier": verifier})
    assert r.status_code == 503


def test_revoke_kills_refresh_token(monkeypatch, tmp_path):
    brain_api, client, reg = _setup(monkeypatch, tmp_path)
    verifier, challenge = _pkce()
    rt = _first_refresh(client, brain_api, reg, verifier, challenge)
    assert client.post("/revoke", data={"token": rt, "client_id": reg["client_id"]}).status_code == 200
    # revoked → refresh now fails
    assert client.post("/token", data={"grant_type": "refresh_token", "refresh_token": rt,
                                       "client_id": reg["client_id"]}).status_code == 400


def test_revoke_unknown_token_still_200(monkeypatch, tmp_path):
    brain_api, client, reg = _setup(monkeypatch, tmp_path)
    assert client.post("/revoke", data={"token": "garbage", "client_id": reg["client_id"]}).status_code == 200


def test_metadata_advertises_revocation(monkeypatch, tmp_path):
    brain_api, client, reg = _setup(monkeypatch, tmp_path)
    md = client.get("/.well-known/oauth-authorization-server").json()
    assert md["revocation_endpoint"].endswith("/revoke")


def test_revoke_wrong_client_does_not_revoke(monkeypatch, tmp_path):
    brain_api, client, reg = _setup(monkeypatch, tmp_path)
    verifier, challenge = _pkce()
    rt = _first_refresh(client, brain_api, reg, verifier, challenge)
    # a caller presenting the token with a DIFFERENT client_id: 200 (RFC 7009) but no revoke
    assert client.post("/revoke", data={"token": rt, "client_id": "someone-else"}).status_code == 200
    # token still works for the real owner
    r = client.post("/token", data={"grant_type": "refresh_token", "refresh_token": rt,
                                    "client_id": reg["client_id"]})
    assert r.status_code == 200


def test_revoke_404_in_none_mode(monkeypatch, tmp_path):
    # In mode=none there is no /revoke route behaviour — it must 404.
    import brain_api, importlib
    from tests.test_brain_api_auth import _make_brain, _client
    brain = _make_brain(tmp_path)   # default = mode=none
    c = _client(monkeypatch, brain)
    assert c.post("/revoke", data={"token": "x", "client_id": "y"}).status_code == 404
