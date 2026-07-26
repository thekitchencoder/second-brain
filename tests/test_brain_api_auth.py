"""Auth enforcement on the REST API."""
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


def _client(monkeypatch, brain):
    monkeypatch.setenv("BRAIN_PATH", str(brain))
    import importlib
    import brain_api
    importlib.reload(brain_api)
    return TestClient(brain_api.app)


def test_mode_none_allows_unauthenticated(monkeypatch, tmp_path):
    brain = _make_brain(tmp_path)
    client = _client(monkeypatch, brain)
    r = client.get("/api/templates")
    assert r.status_code == 200


_OAUTH = textwrap.dedent('''\
    [auth]
    mode = "oauth"
    [auth.rbac]
    [auth.rbac.roles]
    owner = { layers = ["*"] }
    [auth.rbac.principals]
    agent = "owner"
''')


def _signing_key() -> str:
    """A real RSA PEM — oauth mode hard-fails without BRAIN_AUTH_SIGNING_KEY."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    return rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()).decode()


def test_oauth_rejects_missing_token(monkeypatch, tmp_path):
    monkeypatch.setenv("BRAIN_AUTH_PRINCIPAL_TOKENS", json.dumps({"agent": "s3cret"}))
    monkeypatch.setenv("BRAIN_AUTH_SIGNING_KEY", _signing_key())
    brain = _make_brain(tmp_path, _OAUTH)
    client = _client(monkeypatch, brain)
    r = client.get("/api/templates")
    assert r.status_code == 401
    assert "Bearer" in r.headers.get("WWW-Authenticate", "")


def test_oauth_allows_valid_static_token(monkeypatch, tmp_path):
    monkeypatch.setenv("BRAIN_AUTH_PRINCIPAL_TOKENS", json.dumps({"agent": "s3cret"}))
    monkeypatch.setenv("BRAIN_AUTH_SIGNING_KEY", _signing_key())
    brain = _make_brain(tmp_path, _OAUTH)
    client = _client(monkeypatch, brain)
    r = client.get("/api/templates", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200


def test_well_known_served_in_oauth_mode(monkeypatch, tmp_path):
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()).decode()
    monkeypatch.setenv("BRAIN_AUTH_ISSUER", "https://brain.example")
    monkeypatch.setenv("BRAIN_AUTH_AUDIENCE", "https://brain.example/mcp")
    monkeypatch.setenv("BRAIN_AUTH_SIGNING_KEY", key)
    monkeypatch.setenv("BRAIN_AUTH_PRINCIPAL_TOKENS", json.dumps({"agent": "s3cret"}))
    brain = _make_brain(tmp_path, _OAUTH)
    client = _client(monkeypatch, brain)

    r = client.get("/.well-known/oauth-protected-resource")
    assert r.status_code == 200 and r.json()["resource"] == "https://brain.example/mcp"

    r = client.get("/.well-known/jwks.json")
    assert r.status_code == 200 and r.json()["keys"][0]["kty"] == "RSA"


def test_well_known_absent_in_none_mode(monkeypatch, tmp_path):
    brain = _make_brain(tmp_path)
    client = _client(monkeypatch, brain)
    assert client.get("/.well-known/jwks.json").status_code == 404
