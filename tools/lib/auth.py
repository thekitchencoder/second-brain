"""Authentication core — resolve a bearer token to a Principal.

Framework-agnostic. brain_api (REST) and brain_mcp_server (MCP HTTP) both call
resolve_principal() at their request boundary. Gated on profile.auth.mode:
"none" bypasses entirely (OWNER); "oauth" enforces static tokens then JWTs.
No request input may influence the resulting role — the token IS the principal.
"""
from __future__ import annotations

import hmac
import json
import os
import time
from dataclasses import dataclass

from authlib.jose import JsonWebKey, JsonWebToken

# Explicit algorithm allowlist — RS256 only. A generic `jwt.decode()` (no
# whitelist) trusts the `alg` in the token header, so a future authlib change
# (or an attacker-supplied token) could reopen alg-confusion (e.g. HS256 using
# the public key as an HMAC secret). Pinning here means only RS256 is ever
# accepted, independent of what the token claims about itself.
_JWT = JsonWebToken(["RS256"])


@dataclass(frozen=True)
class Principal:
    id: str                          # oauth subject, static principal id, or "owner"
    role: str
    layers: tuple[str, ...]          # ("*",) means all layers; consumed by Plan E
    kind: str                        # "owner" | "static" | "oauth"


OWNER = Principal(id="owner", role="owner", layers=("*",), kind="owner")

# Deny sentinel — the default when no boundary has established a principal.
# Plan E treats layers=() / kind="anonymous" as "deny everything". Never
# default any principal state to OWNER (fail-open); grant OWNER explicitly.
ANONYMOUS = Principal(id="anonymous", role="", layers=(), kind="anonymous")


def role_layers(rbac, role: str) -> tuple[str, ...]:
    spec = (rbac.roles or {}).get(role) or {}
    return tuple(spec.get("layers", []))


def _principal_tokens() -> dict[str, str]:
    raw = os.environ.get("BRAIN_AUTH_PRINCIPAL_TOKENS", "")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def resolve_static(token: str, rbac) -> Principal | None:
    """Match token against configured static principal tokens (constant-time)."""
    for pid, secret in _principal_tokens().items():
        if hmac.compare_digest(token, secret):
            role = (rbac.principals or {}).get(pid)
            if not role or role not in (rbac.roles or {}):
                return None
            return Principal(id=pid, role=role, layers=role_layers(rbac, role), kind="static")
    return None


class AuthSettings:
    """Signs and validates the brain's own RS256 JWTs via authlib."""

    def __init__(self, issuer, audience, private_key_pem):
        self.issuer = issuer
        self.audience = audience
        self._private_pem = private_key_pem
        self._jwk = JsonWebKey.import_key(private_key_pem, {"kty": "RSA"}) if private_key_pem else None

    @classmethod
    def from_env(cls):
        return cls(
            issuer=os.environ.get("BRAIN_AUTH_ISSUER", ""),
            audience=os.environ.get("BRAIN_AUTH_AUDIENCE", ""),
            private_key_pem=os.environ.get("BRAIN_AUTH_SIGNING_KEY", ""),
        )

    def public_jwks(self) -> dict:
        pub = self._jwk.as_dict(is_private=False)
        pub.setdefault("use", "sig")
        pub.setdefault("alg", "RS256")
        return {"keys": [pub]}

    def issue_jwt(self, subject: str, extra: dict | None = None, ttl: int = 3600) -> str:
        now = int(time.time())
        payload = {"iss": self.issuer, "aud": self.audience, "sub": subject,
                   "iat": now, "exp": now + ttl}
        if extra:
            payload.update(extra)
        header = {"alg": "RS256", "kid": self._jwk.thumbprint()}
        return _JWT.encode(header, payload, self._private_pem).decode()

    def validate_jwt(self, token: str) -> dict | None:
        claims_opts = {
            "iss": {"essential": True, "value": self.issuer},
            "aud": {"essential": True, "value": self.audience},
            "exp": {"essential": True},
        }
        try:
            claims = _JWT.decode(token, self._jwk, claims_options=claims_opts)
            claims.validate()
            return dict(claims)
        except Exception:
            return None

    def _consent_audience(self) -> str:
        return f"{self.issuer}#consent"

    def issue_consent(self, payload: dict, ttl: int = 300) -> str:
        now = int(time.time())
        body = {"iss": self.issuer, "aud": self._consent_audience(),
                "typ": "consent", "iat": now, "exp": now + ttl}
        body.update(payload)
        header = {"alg": "RS256", "kid": self._jwk.thumbprint()}
        return _JWT.encode(header, body, self._private_pem).decode()

    def verify_consent(self, token: str) -> dict | None:
        opts = {
            "iss": {"essential": True, "value": self.issuer},
            "aud": {"essential": True, "value": self._consent_audience()},
            "exp": {"essential": True},
        }
        try:
            claims = _JWT.decode(token, self._jwk, claims_options=opts)
            claims.validate()
            if claims.get("typ") != "consent":
                return None
            return dict(claims)
        except Exception:
            return None


def resolve_jwt(token: str, rbac, settings) -> Principal | None:
    """Validate a brain-issued JWT and map its subject to a role."""
    if settings is None:
        return None
    claims = settings.validate_jwt(token)
    if claims is None:
        return None
    if claims.get("typ") == "refresh":
        return None                       # refresh tokens are NOT resource credentials
    subject = claims.get("email") or claims.get("sub")
    if not subject:
        return None
    role = (rbac.identities or {}).get(subject) or rbac.default_role
    if not role or role not in (rbac.roles or {}):
        return None
    return Principal(id=subject, role=role, layers=role_layers(rbac, role), kind="oauth")


def resolve_principal(token, profile, settings) -> Principal | None:
    if profile.auth.mode == "none":
        return OWNER
    if not token:
        return None
    rbac = profile.auth.rbac
    if rbac is None:
        return None
    return resolve_static(token, rbac) or resolve_jwt(token, rbac, settings)
