"""Self-contained OAuth 2.1 authorization server for the brain (oauth mode).

Federates human login to an upstream OIDC IdP, issues brain-scoped JWTs via
AuthSettings, and supports Dynamic Client Registration for claude.ai. Mounted
by brain_api only when profile.auth.mode == "oauth".
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time


# /register is unauthenticated (RFC 7591 open registration). Cap the store so an
# internet-reachable endpoint can't grow oauth-clients.json without bound (DoS on
# the brain volume). Raises RegistrationError past the cap → 429 at the route.
MAX_CLIENTS = 100


class RegistrationError(Exception):
    pass


class ClientStore:
    def __init__(self, path: str):
        self.path = path
        self._clients = {}
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self._clients = json.load(f)
            except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                # Corrupt/unreadable store must not brick startup — fall back
                # to an empty registry rather than crashing construction.
                self._clients = {}

    def _flush(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        # Write-then-rename: a mid-write crash leaves the old file intact
        # instead of a half-written oauth-clients.json that fails to parse
        # on the next startup.
        tmp_path = f"{self.path}.tmp-{os.getpid()}"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self._clients, f, indent=2)
        os.replace(tmp_path, self.path)

    def register(self, metadata: dict) -> dict:
        if len(self._clients) >= MAX_CLIENTS:
            raise RegistrationError("client registration limit reached")
        client_id = secrets.token_urlsafe(16)
        reg = {
            "client_id": client_id,
            "redirect_uris": metadata.get("redirect_uris", []),
            "client_name": metadata.get("client_name", ""),
            "token_endpoint_auth_method": metadata.get("token_endpoint_auth_method", "none"),
            "grant_types": metadata.get("grant_types", ["authorization_code", "refresh_token"]),
            "response_types": metadata.get("response_types", ["code"]),
        }
        self._clients[client_id] = reg
        self._flush()
        return reg

    def get(self, client_id: str) -> dict | None:
        return self._clients.get(client_id)

    def all(self) -> list:
        return list(self._clients.values())


MAX_REFRESH = 5000


class RefreshStore:
    """Persistent record of issued refresh tokens (by jti) for rotation +
    revocation. Same atomic write + corrupt-load guard as ClientStore, and the
    same sweep+cap as AuthState. Single-process container; a multi-replica
    deployment moves this to a shared store."""

    def __init__(self, path: str):
        self.path = path
        self._tokens = {}
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self._tokens = json.load(f)
            except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                self._tokens = {}

    def _flush(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = f"{self.path}.tmp-{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._tokens, f, indent=2)
        os.replace(tmp, self.path)

    def _sweep(self):
        now = int(time.time())
        for j in [k for k, r in self._tokens.items() if r.get("exp", 0) < now]:
            del self._tokens[j]

    def issue(self, subject: str, client_id: str, ttl: int):
        self._sweep()
        if len(self._tokens) >= MAX_REFRESH:
            raise RegistrationError("refresh token limit reached")
        jti = secrets.token_urlsafe(24)
        exp = int(time.time()) + ttl
        self._tokens[jti] = {"subject": subject, "client_id": client_id,
                             "exp": exp, "revoked": False}
        self._flush()
        return jti, exp

    def get(self, jti: str):
        return self._tokens.get(jti)

    def revoke(self, jti: str):
        rec = self._tokens.get(jti)
        if rec and not rec["revoked"]:
            rec["revoked"] = True
            self._flush()

    def revoke_all_for(self, subject: str, client_id: str):
        changed = False
        for rec in self._tokens.values():
            if rec["subject"] == subject and rec["client_id"] == client_id and not rec["revoked"]:
                rec["revoked"] = True
                changed = True
        if changed:
            self._flush()

    def rotate(self, old_jti: str, subject: str, client_id: str, ttl: int):
        jti, exp = self.issue(subject, client_id, ttl)  # if this raises, old token stays valid
        self.revoke(old_jti)
        return jti, exp


# /authorize (pending) and the code-issuing step both run unauthenticated
# before an upstream login completes, so both dicts are attacker-reachable.
# Sweep expired entries on every write and hard-cap size so a flood of
# /authorize requests (or, for codes, of successful-but-never-redeemed
# logins) can't grow either dict without bound (memory-DoS).
MAX_PENDING = 2000
MAX_CODES = 2000


class AuthState:
    """In-memory store of pending upstream flows and issued auth codes.

    Single-process container; codes are short-lived and single-use. For a
    multi-replica deployment this moves to a shared store — out of scope here.
    """
    def __init__(self):
        self.pending = {}   # state -> {client_id, redirect_uri, code_challenge, client_state, exp}
        self.codes = {}     # code -> {client_id, redirect_uri, code_challenge, subject, exp}

    def _sweep(self):
        now = int(time.time())
        for store in (self.pending, self.codes):
            expired = [k for k, v in store.items() if v.get("exp", 0) < now]
            for k in expired:
                del store[k]

    def stash_pending(self, state, ttl: int = 600, **kw):
        self._sweep()
        if state not in self.pending and len(self.pending) >= MAX_PENDING:
            raise RegistrationError("pending authorization limit reached")
        kw["exp"] = int(time.time()) + ttl
        self.pending[state] = kw

    def pop_pending(self, state):
        rec = self.pending.pop(state, None)
        if rec is None:
            return None
        if rec["exp"] < int(time.time()):
            return None
        return rec


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def verify_pkce(code_challenge: str, code_verifier: str) -> bool:
    expected = _b64(hashlib.sha256(code_verifier.encode()).digest())
    return secrets.compare_digest(expected, code_challenge)


def issue_auth_code(state: "AuthState", *, client_id, redirect_uri, code_challenge, subject,
                    ttl: int = 300) -> str:
    state._sweep()
    if len(state.codes) >= MAX_CODES:
        raise RegistrationError("auth code limit reached")
    code = secrets.token_urlsafe(24)
    state.codes[code] = {"client_id": client_id, "redirect_uri": redirect_uri,
                         "code_challenge": code_challenge, "subject": subject,
                         "exp": int(time.time()) + ttl}
    return code


def redeem_auth_code(state: "AuthState", *, code, client_id, redirect_uri, code_verifier):
    rec = state.codes.pop(code, None)   # single-use
    if rec is None or rec["exp"] < int(time.time()):
        return None
    if rec["client_id"] != client_id or rec["redirect_uri"] != redirect_uri:
        return None
    if not verify_pkce(rec["code_challenge"], code_verifier):
        return None
    return rec["subject"]
