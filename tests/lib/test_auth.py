import json
from dataclasses import dataclass

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

from lib.auth import Principal, OWNER, resolve_static, resolve_principal, role_layers, AuthSettings
from lib.profile import Auth, Rbac, Profile, Plugin


def _profile(mode, rbac=None):
    return Profile(name="t", folders=["x"], fields=[], global_skills=[], vault_skills=[],
                   plugin=Plugin("p", "a", "m"), zk={}, auth=Auth(mode=mode, rbac=rbac), origin=None)


def _rbac():
    return Rbac(default_role=None,
                roles={"owner": {"layers": ["*"]}, "fenn-agent": {"layers": ["fiction"]}},
                identities={}, principals={"fenn-agent": "fenn-agent"})


def test_mode_none_returns_owner_without_token(monkeypatch):
    monkeypatch.delenv("BRAIN_AUTH_PRINCIPAL_TOKENS", raising=False)
    assert resolve_principal(None, _profile("none"), None) is OWNER


def test_role_layers_reads_role_spec():
    assert role_layers(_rbac(), "fenn-agent") == ("fiction",)
    assert role_layers(_rbac(), "owner") == ("*",)


def test_static_token_resolves_to_principal(monkeypatch):
    monkeypatch.setenv("BRAIN_AUTH_PRINCIPAL_TOKENS", json.dumps({"fenn-agent": "s3cret"}))
    prof = _profile("oauth", _rbac())
    p = resolve_principal("s3cret", prof, None)
    assert p == Principal(id="fenn-agent", role="fenn-agent", layers=("fiction",), kind="static")


def test_wrong_token_is_denied(monkeypatch):
    monkeypatch.setenv("BRAIN_AUTH_PRINCIPAL_TOKENS", json.dumps({"fenn-agent": "s3cret"}))
    prof = _profile("oauth", _rbac())
    assert resolve_principal("nope", prof, None) is None


def test_token_for_unmapped_principal_is_denied(monkeypatch):
    # token id 'ghost' has no entry in rbac.principals
    monkeypatch.setenv("BRAIN_AUTH_PRINCIPAL_TOKENS", json.dumps({"ghost": "s3cret"}))
    prof = _profile("oauth", _rbac())
    assert resolve_principal("s3cret", prof, None) is None


def test_oauth_missing_token_is_denied():
    assert resolve_principal(None, _profile("oauth", _rbac()), None) is None


@pytest.fixture
def signing_key():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


@pytest.fixture
def settings(monkeypatch, signing_key):
    monkeypatch.setenv("BRAIN_AUTH_ISSUER", "https://brain.example")
    monkeypatch.setenv("BRAIN_AUTH_AUDIENCE", "https://brain.example/mcp")
    monkeypatch.setenv("BRAIN_AUTH_SIGNING_KEY", signing_key)
    return AuthSettings.from_env()


def test_roundtrip_issue_and_validate(settings):
    token = settings.issue_jwt("chris@example.com")
    claims = settings.validate_jwt(token)
    assert claims["sub"] == "chris@example.com"
    assert claims["iss"] == "https://brain.example"
    assert claims["aud"] == "https://brain.example/mcp"


def test_validate_rejects_wrong_audience(settings, monkeypatch, signing_key):
    token = settings.issue_jwt("chris@example.com")
    monkeypatch.setenv("BRAIN_AUTH_AUDIENCE", "https://other")
    other = AuthSettings.from_env()
    assert other.validate_jwt(token) is None


def test_validate_rejects_garbage(settings):
    assert settings.validate_jwt("not.a.jwt") is None


def test_jwt_maps_identity_to_role(settings, monkeypatch):
    monkeypatch.delenv("BRAIN_AUTH_PRINCIPAL_TOKENS", raising=False)
    rbac = Rbac(default_role=None,
                roles={"owner": {"layers": ["*"]}},
                identities={"chris@example.com": "owner"}, principals={})
    prof = _profile("oauth", rbac)
    token = settings.issue_jwt("chris@example.com", extra={"email": "chris@example.com"})
    p = resolve_principal(token, prof, settings)
    assert p == Principal(id="chris@example.com", role="owner", layers=("*",), kind="oauth")


def test_jwt_unknown_subject_uses_default_role(settings, monkeypatch):
    monkeypatch.delenv("BRAIN_AUTH_PRINCIPAL_TOKENS", raising=False)
    rbac = Rbac(default_role="guest",
                roles={"guest": {"layers": []}}, identities={}, principals={})
    prof = _profile("oauth", rbac)
    token = settings.issue_jwt("stranger@example.com", extra={"email": "stranger@example.com"})
    p = resolve_principal(token, prof, settings)
    assert p.role == "guest" and p.kind == "oauth"


def test_jwt_unknown_subject_denied_without_default(settings, monkeypatch):
    monkeypatch.delenv("BRAIN_AUTH_PRINCIPAL_TOKENS", raising=False)
    rbac = Rbac(default_role=None, roles={"owner": {"layers": ["*"]}},
                identities={}, principals={})
    prof = _profile("oauth", rbac)
    token = settings.issue_jwt("stranger@example.com", extra={"email": "stranger@example.com"})
    assert resolve_principal(token, prof, settings) is None


def test_validate_rejects_non_rs256_alg(settings):
    """FIX 2: the algorithm allowlist is pinned to RS256 explicitly. An
    HS256-signed token (even one with plausible iss/aud/exp claims) must be
    rejected regardless of what secret it's signed with — alg-confusion
    protection, not a signature check."""
    from authlib.jose import JsonWebToken
    import time
    now = int(time.time())
    payload = {"iss": settings.issuer, "aud": settings.audience, "sub": "chris@example.com",
               "iat": now, "exp": now + 3600}
    hs_jwt = JsonWebToken(["HS256"])
    token = hs_jwt.encode({"alg": "HS256"}, payload, "some-shared-secret").decode()
    assert settings.validate_jwt(token) is None


def test_consent_ticket_roundtrip(settings):
    t = settings.issue_consent({"client_id": "c1", "subject": "u@e.com"})
    claims = settings.verify_consent(t)
    assert claims["client_id"] == "c1" and claims["subject"] == "u@e.com"
    assert claims["typ"] == "consent"


def test_consent_ticket_is_not_a_resource_token(settings):
    # A consent ticket must NOT authenticate a resource call (distinct audience).
    t = settings.issue_consent({"client_id": "c1", "subject": "u@e.com"})
    assert settings.validate_jwt(t) is None


def test_access_token_is_not_a_consent_ticket(settings):
    access = settings.issue_jwt("u@e.com", {"email": "u@e.com"})
    assert settings.verify_consent(access) is None


def test_expired_consent_ticket_rejected(settings):
    t = settings.issue_consent({"client_id": "c1", "subject": "u@e.com"}, ttl=-1)
    assert settings.verify_consent(t) is None


def test_refresh_token_rejected_as_bearer(settings, monkeypatch):
    """A refresh token (same iss/aud, typ=refresh) must NOT authenticate a resource call."""
    monkeypatch.delenv("BRAIN_AUTH_PRINCIPAL_TOKENS", raising=False)
    rbac = Rbac(default_role=None, roles={"owner": {"layers": ["*"]}},
                identities={"chris@example.com": "owner"}, principals={})
    prof = _profile("oauth", rbac)
    refresh = settings.issue_jwt("chris@example.com",
                                 extra={"email": "chris@example.com", "typ": "refresh"},
                                 ttl=30 * 86400)
    assert resolve_principal(refresh, prof, settings) is None
