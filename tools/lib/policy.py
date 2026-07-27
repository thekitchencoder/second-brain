"""PolicyProvider — the engine's single view of auth policy.

Policy TRUTH is the profile repo (world-machine architecture §9.7): the
[auth] block of <brain>/.brain/profile.toml. This provider reads it with
an mtime-based hot-reload cache, applies the BRAIN_AUTH_MODE instance
seam, and verifies agent (static-bearer) credentials against either the
legacy env map or the Postgres agent_tokens table. Nothing here writes
policy — lib/policy_edit.py is the only writer.
"""
from __future__ import annotations

import hmac
import os
import tomllib

from lib.profile import _load_auth

_VALID_MODES = ("none", "oauth")


class ProfilePolicyProvider:
    def __init__(self, profile_dir: str, credential_backend: str = "env",
                 dsn: str = ""):
        self._path = os.path.join(profile_dir, "profile.toml")
        self._mtime: float | None = None
        self._auth = None
        self.credential_backend = credential_backend
        self._dsn = dsn
        self._cred_store = None

    # ── policy (read-only, hot-reloading) ────────────────────────────

    def _load(self):
        try:
            mtime = os.stat(self._path).st_mtime
        except OSError:
            self._auth, self._mtime = None, None
            return
        if self._auth is None or mtime != self._mtime:
            with open(self._path, "rb") as f:
                raw = tomllib.load(f)
            self._auth = _load_auth(raw.get("auth", {}))
            self._mtime = mtime

    def invalidate(self) -> None:
        self._mtime = None

    def get_rbac(self):
        self._load()
        return self._auth.rbac if self._auth else None

    def get_auth_mode(self) -> str:
        env = os.environ.get("BRAIN_AUTH_MODE", "")
        if env:
            if env not in _VALID_MODES:
                raise RuntimeError(
                    f"Invalid BRAIN_AUTH_MODE: {env!r} (expected 'none' or 'oauth')")
            return env
        self._load()
        if self._auth is None:
            raise RuntimeError(
                f"cannot determine auth mode: {self._path} is missing or "
                "unreadable — refusing to fail open (set BRAIN_AUTH_MODE "
                "explicitly to override)")
        return self._auth.mode

    # ── credentials ──────────────────────────────────────────────────

    def verify_agent_token(self, token: str) -> str | None:
        """Return the principal id for a valid agent bearer token, else None."""
        if self.credential_backend == "postgres":
            if self._cred_store is None:
                try:
                    from lib.credentials import get_credential_store
                except ImportError as e:
                    raise RuntimeError(
                        "postgres credential backend not available: "
                        "lib.credentials could not be imported "
                        "(broken or incomplete install?)"
                    ) from e
                self._cred_store = get_credential_store(self._dsn)
            return self._cred_store.verify(token)
        # env backend — legacy BRAIN_AUTH_PRINCIPAL_TOKENS map
        from lib.auth import _principal_tokens
        for pid, secret in _principal_tokens().items():
            if hmac.compare_digest(token, secret):
                return pid
        return None


def get_policy_provider(cfg) -> ProfilePolicyProvider:
    """Fail-loud construction from Config. Never silently downgrades."""
    backend = os.environ.get("BRAIN_POLICY_CREDENTIALS", "env")
    if backend == "env":
        return ProfilePolicyProvider(cfg.profile_dir)
    if backend == "postgres":
        dsn = getattr(cfg, "database_url", "") or ""
        if not dsn:
            raise RuntimeError(
                "BRAIN_POLICY_CREDENTIALS=postgres requires BRAIN_DATABASE_URL")
        return ProfilePolicyProvider(cfg.profile_dir,
                                     credential_backend="postgres", dsn=dsn)
    raise RuntimeError(
        f"Unknown BRAIN_POLICY_CREDENTIALS: {backend!r} (expected 'env' or 'postgres')")
