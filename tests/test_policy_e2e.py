"""End-to-end story test for the slice 2 policy/admin stack: a profile repo
(git truth for RBAC) plus Postgres agent-token credentials, exercised through
the same seams the admin plane and REST/MCP boundaries use — PolicyEditor,
PgCredentialStore, ProfilePolicyProvider, and resolve_principal(). This is
the acceptance test for the slice: it walks one agent's whole lifecycle,
mint through revoke, and proves hot-reload needs no restart.
"""
import os
import subprocess
import textwrap
import time

import pytest

from lib.auth import resolve_principal
from lib.policy import ProfilePolicyProvider
from lib.policy_edit import PolicyEditor

TOML = """
name = "t"
folders = ["X"]

[plugin]
name = "t"
author = "a"
marker = "t"

[auth]
mode = "oauth"

[auth.rbac]
default_role = "reader"

[auth.rbac.roles.reader]
read = ["work"]
write = []
"""


@pytest.fixture
def tmp_profile_repo(tmp_path):
    (tmp_path / "profile.toml").write_text(textwrap.dedent(TOML))
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "seed"], cwd=tmp_path, check=True)
    return str(tmp_path)


@pytest.fixture(scope="session")
def pg_dsn():
    tc = pytest.importorskip("testcontainers.postgres")
    with tc.PostgresContainer("pgvector/pgvector:pg17") as pg:
        # psycopg DSN (testcontainers returns a SQLAlchemy-style URL)
        yield pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")


@pytest.mark.integration
def test_full_agent_lifecycle(pg_dsn, tmp_profile_repo, monkeypatch):
    """One agent, cradle to grave: policy commits + Postgres credentials +
    a live provider that never needs restarting to see either kind of
    change."""
    from lib.credentials import PgCredentialStore

    monkeypatch.delenv("BRAIN_AUTH_MODE", raising=False)

    # Fresh table for this run — mirrors tests/lib/test_credentials.py's
    # store fixture so re-runs against the same container don't collide.
    seed_store = PgCredentialStore(pg_dsn)
    with seed_store._pool.connection() as conn:
        conn.execute("DROP TABLE IF EXISTS agent_tokens")
    seed_store.init()

    editor = PolicyEditor(tmp_profile_repo)
    provider = ProfilePolicyProvider(tmp_profile_repo, credential_backend="postgres",
                                     dsn=pg_dsn)

    # ── Stage 1: principal_set via PolicyEditor -> commit exists ────────
    editor.role_set("maker", read=["*"], write=["*"])
    editor.principal_set("fenn-desk", "maker")
    log = subprocess.run(["git", "log", "--oneline"], cwd=tmp_profile_repo,
                         capture_output=True, text=True).stdout
    assert "policy: set role maker" in log
    assert "policy: map principal fenn-desk -> maker" in log

    # ── Stage 2: mint via PgCredentialStore ─────────────────────────────
    token = seed_store.mint("fenn-desk")
    assert len(token) >= 32

    # ── Stage 3: resolve_principal(token, provider, None) -> Principal
    # with role layers, resolved through the SAME provider instance the
    # rest of this test keeps using ─────────────────────────────────────
    principal = resolve_principal(token, provider, None)
    assert principal is not None
    assert principal.id == "fenn-desk"
    assert principal.role == "maker"
    assert principal.read_layers == ("*",)
    assert principal.write_layers == ("*",)
    assert principal.kind == "static"

    # ── Stage 4: revoke -> resolve_principal -> None ────────────────────
    assert seed_store.revoke("fenn-desk") == 1
    assert resolve_principal(token, provider, None) is None

    # ── Stage 5: role_set changes layers -> provider hot-reloads -> next
    # resolve sees new layers with no restart/invalidate() call ─────────
    token2 = seed_store.mint("fenn-desk")
    principal_before = resolve_principal(token2, provider, None)
    assert principal_before is not None
    assert principal_before.read_layers == ("*",)
    assert principal_before.write_layers == ("*",)

    editor.role_set("maker", read=["work"], write=[])
    # Force mtime forward — commits made within the same second as the
    # provider's last read would otherwise be invisible to the mtime-based
    # hot-reload cache (lib/policy.py's ProfilePolicyProvider._load), which
    # would make this assertion flaky rather than wrong.
    path = os.path.join(tmp_profile_repo, "profile.toml")
    os.utime(path, (time.time() + 2, time.time() + 2))

    principal_after = resolve_principal(token2, provider, None)
    assert principal_after is not None
    assert principal_after.id == "fenn-desk"
    assert principal_after.role == "maker"
    assert principal_after.read_layers == ("work",)
    assert principal_after.write_layers == ()

    seed_store.close()
