"""End-to-end acceptance test for slice 3: the retrieval log's whole story,
on a live Postgres (testcontainers) — the same pg_dsn fixture pattern used by
tests/lib/test_retrieval_log.py and tests/test_policy_e2e.py.

One story, four stages, each with its own oracle:

  1. A restricted principal searches a SqliteVecStore-backed brain (2 notes
     layer=fiction, 1 note layer=maker) and the log records EXACTLY the
     surfaced fiction notes — the maker note's path is nowhere in the log,
     not just absent from this query's result set.
  2. A successful write logs exactly one row.
  3. An admin mutation (PolicyEditor.role_set via brain_api's real
     _admin_edit) logs exactly one admin row whose subject contains the
     commit sha — the same code path the REST admin routes use.
  4. Flag-off control: with BRAIN_RETRIEVAL_LOG unset, repeating a search
     leaves the row count unchanged — the hook is a real no-op, not just
     quiet.

The vector store is real sqlite-vec (available on this host/venv); the
embedding call is stubbed with deterministic vectors — the LOG is what's
under test here, not embedding quality or ranking.
"""
from __future__ import annotations

import subprocess
import textwrap

import pytest

from lib.auth import Principal
from lib.brain import handle_brain_search, handle_brain_write
from lib.db import init_db, upsert_chunk
from lib.policy_edit import PolicyEditor


def _signing_key() -> str:
    """A real RSA PEM — oauth mode hard-fails without BRAIN_AUTH_SIGNING_KEY."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    return rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()).decode()


@pytest.fixture(scope="session")
def pg_dsn():
    tc = pytest.importorskip("testcontainers.postgres")
    with tc.PostgresContainer("pgvector/pgvector:pg17") as pg:
        # psycopg DSN (testcontainers returns a SQLAlchemy-style URL)
        yield pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")


@pytest.fixture
def retrieval_log(pg_dsn, monkeypatch):
    """Fresh retrieval_log table on the shared container, wired up via the
    real env-driven accessor so it's the SAME memoized instance the hooks
    under test resolve to."""
    monkeypatch.setenv("BRAIN_RETRIEVAL_LOG", "postgres")
    monkeypatch.setenv("BRAIN_DATABASE_URL", pg_dsn)
    import lib.retrieval_log as rl
    log = rl.get_retrieval_log(pg_dsn)
    with log._pool.connection() as conn:
        conn.execute("DROP TABLE IF EXISTS retrieval_log")
    log.init()
    yield log
    log.close()
    rl._logs.pop(pg_dsn, None)


@pytest.mark.integration
def test_retrieval_log_acceptance(pg_dsn, retrieval_log, tmp_path, monkeypatch):
    log = retrieval_log

    # ── Brain layout: 2 fiction notes + 1 maker note ────────────────────
    brain = tmp_path / "brain"
    canon = brain / "canon"
    canon.mkdir(parents=True)
    (canon / "story1.md").write_text("---\nlayer: fiction\n---\nA tale of dragons.")
    (canon / "story2.md").write_text("---\nlayer: fiction\n---\nAnother fable.")
    (canon / "roadmap.md").write_text("---\nlayer: maker\n---\nThe maker's secret roadmap.")
    story1 = str(canon / "story1.md")
    story2 = str(canon / "story2.md")
    roadmap = str(canon / "roadmap.md")
    (brain / ".ai").mkdir()

    # ── Profile: git-tracked (PolicyEditor requires a real repo, same as
    # test_policy_e2e.py's tmp_profile_repo) — a fiction-only role plus an
    # admin owner role, for stage 3. ────────────────────────────────────
    profile_dir = brain / ".brain"
    profile_dir.mkdir(parents=True)
    (profile_dir / "profile.toml").write_text(textwrap.dedent('''\
        name = "fiction"
        folders = ["canon"]
        [plugin]
        name = "fiction"
        author = "c"
        marker = "fiction"
        [auth]
        mode = "oauth"
        [auth.rbac]
        default_role = "reader"
        [auth.rbac.roles.reader]
        read = []
        write = []
        [auth.rbac.roles.fiction-only]
        read = ["fiction"]
        write = ["fiction"]
        [auth.rbac.roles.owner]
        read = ["*"]
        write = ["*"]
        admin = true
        [auth.rbac.principals]
        fenn-desk = "fiction-only"
        root = "owner"
    '''))
    subprocess.run(["git", "init", "-q"], cwd=profile_dir, check=True)
    subprocess.run(["git", "add", "-A"], cwd=profile_dir, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "seed"], cwd=profile_dir, check=True)

    # ── Index: real SqliteVecStore (real sqlite-vec extension). Embeddings
    # are stubbed deterministic vectors below — store choice/ranking is
    # irrelevant to the log, only the coarse layer wall + fine visible()
    # filter that gate what handle_brain_search surfaces. ───────────────
    db_path = str(brain / ".ai" / "embeddings.db")
    init_db(db_path, embedding_dim=4)
    meta = {"title": "x", "type": "note", "status": "current",
            "created": "2026-01-01", "tags": []}
    upsert_chunk(db_path, story1, 0, "dragons", "h1", [1.0, 0.0, 0.0, 0.0],
                {**meta, "layer": "fiction"})
    upsert_chunk(db_path, story2, 0, "fable", "h2", [0.9, 0.1, 0.0, 0.0],
                {**meta, "layer": "fiction"})
    upsert_chunk(db_path, roadmap, 0, "secret roadmap", "h3", [0.0, 0.0, 1.0, 0.0],
                {**meta, "layer": "maker"})

    monkeypatch.setenv("BRAIN_PATH", str(brain))
    fenn = Principal(id="fenn-desk", role="fiction-only", read_layers=("fiction",),
                     write_layers=("fiction",), kind="static")

    # ── Stage 1: restricted search -> exactly the fiction notes, and the
    # maker note's path is nowhere in the log (the oracle extends to the
    # log, not just the response). ──────────────────────────────────────
    monkeypatch.setattr("lib.embeddings.get_embedding", lambda q: [1.0, 0.0, 0.0, 0.0])
    result = handle_brain_search("dragons", 5, db_path, principal=fenn, fields=[])
    assert story1 in result and story2 in result
    assert roadmap not in result

    read_rows = log.query(principal="fenn-desk", kind="read")
    assert {r["filepath"] for r in read_rows} == {story1, story2}
    assert all(r["filepath"] != roadmap for r in log.query(limit=1000))

    # ── Stage 2: a successful write logs exactly one row. ───────────────
    write_result = handle_brain_write(
        "canon/story1.md", "---\nlayer: fiction\n---\nA tale of dragons, revised.",
        str(brain), principal=fenn, fields=[])
    assert write_result.startswith("Written")
    write_rows = log.query(principal="fenn-desk", kind="write")
    assert len(write_rows) == 1
    assert write_rows[0]["filepath"] == "canon/story1.md"

    # ── Stage 3: PolicyEditor.role_set via brain_api's real _admin_edit ->
    # one admin row whose subject contains the commit sha. ─────────────
    monkeypatch.setenv("BRAIN_AUTH_SIGNING_KEY", _signing_key())
    import importlib
    import brain_api
    importlib.reload(brain_api)
    root = Principal(id="root", role="owner", read_layers=("*",),
                     write_layers=("*",), kind="static")
    edit_result = brain_api._admin_edit(
        root, "role_set fiction-only",
        lambda ed: ed.role_set("fiction-only", read=["fiction"], write=["fiction"]))
    sha = edit_result["commit"]

    admin_rows = log.query(kind="admin")
    assert len(admin_rows) == 1
    assert sha[:7] in admin_rows[0]["subject"]
    assert "fiction-only" in admin_rows[0]["subject"]

    # ── Stage 4: flag-off control — with BRAIN_RETRIEVAL_LOG unset, the
    # same search leaves the row count unchanged. ──────────────────────
    total_before = len(log.query(limit=10000))
    monkeypatch.delenv("BRAIN_RETRIEVAL_LOG", raising=False)
    handle_brain_search("dragons", 5, db_path, principal=fenn, fields=[])
    total_after = len(log.query(limit=10000))
    assert total_after == total_before

    # ── Final whole-log check: the maker note's path never appears,
    # across every stage — read, write, and admin rows alike. ──────────
    assert all(r["filepath"] != roadmap for r in log.query(limit=10000))
