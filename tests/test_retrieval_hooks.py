# tests/test_retrieval_hooks.py
"""Slice 3: retrieval/audit-log hooks at every read/write/admin boundary.

Two legs are tested:
  - handler leg: lib.brain.handle_brain_* called directly, patching
    lib.brain.safe_log_reads / safe_log_write (where they're looked up).
  - REST leg: brain_api routes driven via TestClient, patching
    brain_api.safe_log_reads / safe_log_write / safe_log_admin.

The oracle extends to the log: a forbidden note must never be logged, and
error paths never log — those are exercised explicitly below.
"""
import json
import os
import sys
import textwrap
from unittest.mock import MagicMock, patch

if "sqlite_vec" not in sys.modules:
    sys.modules["sqlite_vec"] = MagicMock()
if "openai" not in sys.modules:
    sys.modules["openai"] = MagicMock()

import pytest
from fastapi.testclient import TestClient

import lib.brain as lib_brain
from lib.brain import (
    handle_brain_backlinks,
    handle_brain_create,
    handle_brain_edit,
    handle_brain_query,
    handle_brain_read,
    handle_brain_related,
    handle_brain_restore,
    handle_brain_search,
    handle_brain_trash,
    handle_brain_write,
)
from lib.auth import OWNER, Principal
from lib.profile import Field
from lib.embeddings import EmbeddingError


def _recorder(monkeypatch, module, name):
    calls = []
    monkeypatch.setattr(module, name, lambda *a, **k: calls.append((a, k)))
    return calls


class _FakeStore:
    """Duck-typed vector store — canned, already-ordered rows."""

    def __init__(self, rows, vectors=None):
        self._rows = rows
        self._vectors = [[0.1, 0.2, 0.3]] if vectors is None else vectors

    def search(self, vector, k, allowed_layers=None):
        return list(self._rows[:k])

    def get_chunk_embeddings(self, filepath):
        return self._vectors


def _reviewer():
    """Read-unrestricted, write-restricted to 'fiction' — the layer combo that
    lets a write fail on authorization without also failing the read gate."""
    return Principal(id="reviewer", role="reviewer", read_layers=("*",),
                     write_layers=("fiction",), kind="static")


def _fenn():
    return Principal(id="fenn", role="fenn", read_layers=("fiction",),
                     write_layers=("fiction",), kind="static")


FIELDS = [Field("known_by", "list", "kb", visibility="allow")]


# ═══════════════════════════════════════════════════════════════════
# Handler leg — tools/lib/brain.py
# ═══════════════════════════════════════════════════════════════════


# ── reads ──────────────────────────────────────────────────────────


def test_search_handler_logs_surfaced_notes(monkeypatch):
    calls = _recorder(monkeypatch, lib_brain, "safe_log_reads")
    rows = [{"filepath": "a.md", "distance": 0.1},
            {"filepath": "b.md", "distance": 0.2},
            {"filepath": "a.md", "distance": 0.3}]  # dup, must dedupe
    with patch("lib.embeddings.get_embedding", return_value=[0.1, 0.2]), \
         patch("lib.vectorstore.get_store", return_value=_FakeStore(rows)):
        handle_brain_search("my query", 5, ":memory:", principal=OWNER)
    assert len(calls) == 1
    args, kwargs = calls[0]
    principal, tool, subject, filepaths = args
    assert principal is OWNER
    assert tool == "brain_search"
    assert subject == "my query"
    assert filepaths == ["a.md", "b.md"]   # deduped, one row per note


def test_search_handler_no_log_on_embedding_error(monkeypatch):
    calls = _recorder(monkeypatch, lib_brain, "safe_log_reads")
    with patch("lib.embeddings.get_embedding", side_effect=EmbeddingError("down")):
        result = handle_brain_search("q", 5, ":memory:", principal=OWNER)
    assert "error" in result.lower() or "embedding" in result.lower()
    assert calls == []


def test_related_handler_logs_surfaced_notes(tmp_path, monkeypatch):
    calls = _recorder(monkeypatch, lib_brain, "safe_log_reads")
    target = tmp_path / "target.md"
    target.write_text("hello")
    rows = [{"filepath": "a.md", "distance": 0.1}, {"filepath": "b.md", "distance": 0.2}]
    with patch("lib.vectorstore.get_store", return_value=_FakeStore(rows)):
        handle_brain_related("target.md", 5, ":memory:", str(tmp_path), principal=OWNER)
    assert len(calls) == 1
    principal, tool, subject, filepaths = calls[0][0]
    assert tool == "brain_related"
    assert subject == "target.md"
    assert filepaths == ["a.md", "b.md"]


def test_related_handler_no_log_when_not_indexed(tmp_path, monkeypatch):
    calls = _recorder(monkeypatch, lib_brain, "safe_log_reads")
    with patch("lib.vectorstore.get_store", return_value=_FakeStore([], vectors=[])):
        result = handle_brain_related("nope.md", 5, ":memory:", str(tmp_path), principal=OWNER)
    assert "No embeddings found" in result
    assert calls == []


def test_read_handler_logs_only_on_success(tmp_path, monkeypatch):
    calls = _recorder(monkeypatch, lib_brain, "safe_log_reads")
    note = tmp_path / "note.md"
    note.write_text("---\ntitle: X\n---\nbody")

    missing = handle_brain_read("missing.md", str(tmp_path), principal=OWNER)
    assert "File not found" in missing
    assert calls == []

    found = handle_brain_read("note.md", str(tmp_path), principal=OWNER)
    assert "body" in found
    assert len(calls) == 1
    principal, tool, subject, filepaths = calls[0][0]
    assert tool == "brain_read"
    assert subject == "note.md"
    assert filepaths == ["note.md"]


def test_read_handler_no_log_on_forbidden(tmp_path, monkeypatch):
    """A forbidden note returns 'File not found' AND is never logged — the
    oracle extends to the log, not just the response body."""
    calls = _recorder(monkeypatch, lib_brain, "safe_log_reads")
    secret = tmp_path / "secret.md"
    secret.write_text("---\nlayer: classified\n---\nspoiler")

    forbidden = handle_brain_read("secret.md", str(tmp_path), principal=_fenn(), fields=FIELDS)
    absent = handle_brain_read("nope.md", str(tmp_path), principal=_fenn(), fields=FIELDS)
    assert forbidden == absent == "File not found"
    assert calls == []


def test_query_handler_logs_file_list_frontmatter_branch(tmp_path, monkeypatch):
    calls = _recorder(monkeypatch, lib_brain, "safe_log_reads")
    (tmp_path / "a.md").write_text("---\nstatus: active\n---\n")
    (tmp_path / "b.md").write_text("---\nstatus: done\n---\n")
    result = handle_brain_query(str(tmp_path), fields={"status": "active"}, principal=OWNER)
    assert "a.md" in result
    assert len(calls) == 1
    principal, tool, subject, filepaths = calls[0][0]
    assert tool == "brain_query"
    assert subject == "tag=None filters=['status']"   # compact, content-free repr
    assert filepaths == ["a.md"]


def test_query_handler_no_log_on_no_match(tmp_path, monkeypatch):
    calls = _recorder(monkeypatch, lib_brain, "safe_log_reads")
    (tmp_path / "a.md").write_text("---\nstatus: active\n---\n")
    result = handle_brain_query(str(tmp_path), fields={"status": "nonexistent"}, principal=OWNER)
    assert "No notes matched" in result
    assert calls == []


def test_query_handler_no_log_on_validation_error(tmp_path, monkeypatch):
    calls = _recorder(monkeypatch, lib_brain, "safe_log_reads")
    result = handle_brain_query(str(tmp_path), tag="bad tag!", principal=OWNER)
    assert "invalid" in result.lower()
    assert calls == []


def test_backlinks_handler_logs_source_filepaths(tmp_path, monkeypatch):
    calls = _recorder(monkeypatch, lib_brain, "safe_log_reads")
    target = tmp_path / "target.md"
    target.write_text("---\ntitle: Target\n---\n\nHello.")
    linker = tmp_path / "linker.md"
    linker.write_text("---\ntitle: Linker\n---\n\nSee [[target]] for details.")

    handle_brain_backlinks("target.md", str(tmp_path), principal=OWNER)
    assert len(calls) == 1
    principal, tool, subject, filepaths = calls[0][0]
    assert tool == "brain_backlinks"
    assert subject == "target.md"
    assert filepaths == ["linker.md"]


def test_backlinks_handler_no_content_leak_on_none_found(tmp_path, monkeypatch):
    """No backlinks -> the hook still fires (harmlessly, on an empty list) but
    the response carries no path-specific detail."""
    calls = _recorder(monkeypatch, lib_brain, "safe_log_reads")
    (tmp_path / "target.md").write_text("---\ntitle: Target\n---\n\nHello.")
    result = handle_brain_backlinks("target.md", str(tmp_path), principal=OWNER)
    assert "No backlinks" in result
    assert len(calls) == 1
    assert calls[0][0][3] == []   # empty filepaths — safe_log_reads itself no-ops on this


# ── writes ─────────────────────────────────────────────────────────


def test_write_handler_logs_post_success_only(tmp_path, monkeypatch):
    calls = _recorder(monkeypatch, lib_brain, "safe_log_write")
    classified = tmp_path / "classified.md"
    classified.write_text("---\nlayer: classified\n---\nold")

    failed = handle_brain_write(
        "classified.md", "---\nlayer: classified\n---\nnew",
        str(tmp_path), principal=_reviewer(), fields=[],
    )
    assert "Not authorized" in failed
    assert calls == []

    ok = handle_brain_write(
        "open.md", "---\nlayer: fiction\n---\nnew content",
        str(tmp_path), principal=_reviewer(), fields=[],
    )
    assert "Written" in ok
    assert len(calls) == 1
    principal, tool, filepath = calls[0][0]
    assert tool == "write"
    assert filepath == "open.md"


def test_edit_handler_logs_with_op_detail(tmp_path, monkeypatch):
    calls = _recorder(monkeypatch, lib_brain, "safe_log_write")
    note = tmp_path / "note.md"
    note.write_text("---\ntitle: X\n---\n\n# Tasks\n\n- one\n")

    not_found = handle_brain_edit("missing.md", "find_replace", str(tmp_path),
                                  find="x", replace="y", principal=OWNER)
    assert "File not found" in not_found
    assert calls == []

    result = handle_brain_edit("note.md", "replace_section", str(tmp_path),
                               heading="Tasks", body="- done", principal=OWNER)
    assert "replace_section" in result
    assert len(calls) == 1
    principal, tool, filepath = calls[0][0]
    kwargs = calls[0][1]
    assert tool == "edit"
    assert filepath == "note.md"
    assert kwargs.get("subject") == "replace_section: Tasks"


def test_edit_handler_no_log_on_duplicate_wikilink_noop(tmp_path, monkeypatch):
    """insert_wikilink's 'already present' path never writes to disk — no log."""
    calls = _recorder(monkeypatch, lib_brain, "safe_log_write")
    note = tmp_path / "note.md"
    note.write_text("---\ntitle: X\n---\n\nSee [[existing]].")
    result = handle_brain_edit("note.md", "insert_wikilink", str(tmp_path),
                               target="existing", principal=OWNER)
    assert "already present" in result
    assert calls == []


def test_create_handler_logs_write(tmp_path, monkeypatch):
    calls = _recorder(monkeypatch, lib_brain, "safe_log_write")
    tpl_dir = tmp_path / ".zk" / "templates"
    tpl_dir.mkdir(parents=True)
    (tpl_dir / "default.md").write_text("---\ntitle: {{title}}\n---\n")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=str(tmp_path / "new.md") + "\n", stderr="")
        result = handle_brain_create("default", "New Note", str(tmp_path), principal=OWNER)
    assert len(calls) == 1
    principal, tool, filepath = calls[0][0]
    assert tool == "create"
    assert filepath == result
    assert "template=default" in calls[0][1].get("subject", "")


def test_create_handler_no_log_on_zk_failure(tmp_path, monkeypatch):
    calls = _recorder(monkeypatch, lib_brain, "safe_log_write")
    tpl_dir = tmp_path / ".zk" / "templates"
    tpl_dir.mkdir(parents=True)
    (tpl_dir / "default.md").write_text("---\ntitle: {{title}}\n---\n")
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="boom")
        result = handle_brain_create("default", "New Note", str(tmp_path), principal=OWNER)
    assert "failed" in result.lower()
    assert calls == []


def test_trash_handler_logs_post_success_only(tmp_path, monkeypatch):
    calls = _recorder(monkeypatch, lib_brain, "safe_log_write")
    note = tmp_path / "Cards" / "foo.md"
    note.parent.mkdir(parents=True)
    note.write_text("---\ntitle: Foo\n---\n\nHello.")

    not_found = handle_brain_trash("Cards/nonexistent.md", str(tmp_path), db_path=":memory:", principal=OWNER)
    assert "Error" in not_found
    assert calls == []

    with patch("lib.vectorstore.SqliteVecStore.delete_file_chunks"):
        result = handle_brain_trash("Cards/foo.md", str(tmp_path), db_path=":memory:", principal=OWNER)
    assert "Trashed" in result
    assert len(calls) == 1
    principal, tool, filepath = calls[0][0]
    assert tool == "trash"
    assert filepath == "Cards/foo.md"


def test_restore_handler_logs_post_success_only(tmp_path, monkeypatch):
    note = tmp_path / "Cards" / "foo.md"
    note.parent.mkdir(parents=True)
    note.write_text("---\ntitle: Foo\n---\n\nHello.")
    with patch("lib.vectorstore.SqliteVecStore.delete_file_chunks"):
        handle_brain_trash("Cards/foo.md", str(tmp_path), db_path=":memory:", principal=OWNER)

    # Recorder installed AFTER the trash call above, so only restore's own
    # (non-)logging is under test here.
    calls = _recorder(monkeypatch, lib_brain, "safe_log_write")

    bad = handle_brain_restore("Cards/foo.md", str(tmp_path), principal=OWNER)  # not a trash path
    assert "Error" in bad
    assert calls == []

    result = handle_brain_restore(".trash/Cards/foo.md", str(tmp_path), principal=OWNER)
    assert "Restored" in result
    assert len(calls) == 1
    principal, tool, filepath = calls[0][0]
    assert tool == "restore"
    assert filepath == "Cards/foo.md"


# ═══════════════════════════════════════════════════════════════════
# REST leg — tools/brain_api.py
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def brain_env(tmp_path):
    """mode=none brain — every request resolves to OWNER, matching brain_env
    in tests/test_brain_api.py."""
    brain_dir = tmp_path / "brain"
    brain_dir.mkdir()
    (brain_dir / ".ai").mkdir()
    tpl_dir = brain_dir / ".zk" / "templates"
    tpl_dir.mkdir(parents=True)
    (tpl_dir / "default.md").write_text("---\ntitle: {{title}}\n---\n")

    profile_dir = brain_dir / ".brain"
    profile_dir.mkdir(parents=True)
    (profile_dir / "profile.toml").write_text(textwrap.dedent('''\
        name = "ace"
        folders = ["Cards"]
        [plugin]
        name = "second-brain"
        author = "kitchencoder"
        marker = "brain"
        [auth]
        mode = "none"
    '''))

    with patch.dict(os.environ, {"BRAIN_PATH": str(brain_dir)}):
        import importlib
        import lib.config
        importlib.reload(lib.config)
        import brain_api
        importlib.reload(brain_api)
        brain_api._cfg = lib.config.Config()
        yield brain_dir, brain_api


@pytest.fixture
def client(brain_env):
    _, api = brain_env
    return TestClient(api.app)


def test_rest_search_logs(client, brain_env, monkeypatch):
    _, api = brain_env
    calls = _recorder(monkeypatch, api, "safe_log_reads")
    mock_results = [{"filepath": "Cards/a.md", "content": "x", "distance": 0.1}]
    with patch("lib.embeddings.get_embedding", return_value=[0.1] * 4), \
         patch("lib.vectorstore._db_search", return_value=mock_results):
        resp = client.get("/api/search", params={"q": "test"})
    assert resp.status_code == 200
    assert len(calls) == 1
    principal, tool, subject, filepaths = calls[0][0]
    assert tool == "brain_search"
    assert subject == "test"
    assert filepaths == ["Cards/a.md"]


def test_rest_related_logs(client, brain_env, monkeypatch, tmp_path):
    brain_dir, api = brain_env
    calls = _recorder(monkeypatch, api, "safe_log_reads")
    note = brain_dir / "Cards" / "target.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("hello")
    rows = [{"filepath": "Cards/other.md", "distance": 0.1}]
    with patch("lib.vectorstore.get_store", return_value=_FakeStore(rows)):
        resp = client.get("/api/notes/Cards/target.md/related")
    assert resp.status_code == 200
    assert len(calls) == 1
    principal, tool, subject, filepaths = calls[0][0]
    assert tool == "brain_related"
    assert filepaths == ["Cards/other.md"]


def test_rest_backlinks_logs(client, brain_env, monkeypatch):
    brain_dir, api = brain_env
    calls = _recorder(monkeypatch, api, "safe_log_reads")
    target = brain_dir / "Cards" / "target.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("---\ntitle: Target\n---\n\nHello.")
    linker = brain_dir / "Cards" / "linker.md"
    linker.write_text("---\ntitle: Linker\n---\n\nSee [[target]].")

    resp = client.get("/api/notes/Cards/target.md/backlinks")
    assert resp.status_code == 200
    assert len(calls) == 1
    principal, tool, subject, filepaths = calls[0][0]
    assert tool == "brain_backlinks"
    assert filepaths == ["Cards/linker.md"]


def test_rest_read_logs_only_on_success(client, brain_env, monkeypatch):
    brain_dir, api = brain_env
    calls = _recorder(monkeypatch, api, "safe_log_reads")

    missing = client.get("/api/notes/Cards/nonexistent.md")
    assert missing.status_code == 404
    assert calls == []

    note = brain_dir / "Cards" / "note.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("---\ntitle: X\n---\n\nBody.")
    found = client.get("/api/notes/Cards/note.md")
    assert found.status_code == 200
    assert len(calls) == 1
    principal, tool, subject, filepaths = calls[0][0]
    assert tool == "brain_read"
    assert filepaths == ["Cards/note.md"]


def test_rest_write_logs_post_success_only(client, brain_env, monkeypatch):
    _, api = brain_env
    calls = _recorder(monkeypatch, api, "safe_log_write")
    resp = client.put("/api/notes/Cards/new.md", json={"content": "---\ntitle: X\n---\n\nHi."})
    assert resp.status_code == 200
    assert len(calls) == 1
    principal, tool, filepath = calls[0][0]
    assert tool == "write"
    assert filepath == "Cards/new.md"


def test_rest_edit_logs_with_detail(client, brain_env, monkeypatch):
    brain_dir, api = brain_env
    note = brain_dir / "Cards" / "note.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("---\ntitle: X\n---\n\n# Tasks\n\n- one\n")
    calls = _recorder(monkeypatch, api, "safe_log_write")
    resp = client.patch("/api/notes/Cards/note.md",
                        json={"op": "replace_section", "heading": "Tasks", "body": "- done"})
    assert resp.status_code == 200
    assert len(calls) == 1
    principal, tool, filepath = calls[0][0]
    kwargs = calls[0][1]
    assert tool == "edit"
    assert filepath == "Cards/note.md"
    assert "Tasks" in kwargs.get("subject", "")


def test_rest_edit_no_log_on_duplicate_wikilink_noop(client, brain_env, monkeypatch):
    brain_dir, api = brain_env
    note = brain_dir / "Cards" / "note.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("---\ntitle: X\n---\n\nSee [[existing]].")
    calls = _recorder(monkeypatch, api, "safe_log_write")
    resp = client.patch("/api/notes/Cards/note.md",
                        json={"op": "insert_wikilink", "target": "existing"})
    assert resp.status_code == 200
    assert "already present" in resp.json()["detail"]
    assert calls == []


# ═══════════════════════════════════════════════════════════════════
# Admin plane — brain_api.py oauth-mode fixtures (mirrors test_brain_api_admin.py)
# ═══════════════════════════════════════════════════════════════════


_ADMIN_OAUTH = textwrap.dedent('''\
    [auth]
    mode = "oauth"

    [auth.rbac.roles.owner]
    read = ["*"]
    write = ["*"]
    admin = true

    [auth.rbac.principals]
    root = "owner"
''')


def _signing_key() -> str:
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    return rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()).decode()


ADMIN_AUTH = {"Authorization": "Bearer root-secret"}


@pytest.fixture
def admin_client(monkeypatch, tmp_path):
    brain = tmp_path / "brain"
    (brain / ".ai").mkdir(parents=True)
    (brain / ".zk" / "templates").mkdir(parents=True)
    pdir = brain / ".brain"
    pdir.mkdir()
    (pdir / "profile.toml").write_text(textwrap.dedent('''\
        name = "ace"
        folders = ["Cards"]
        [plugin]
        name = "second-brain"
        author = "kitchencoder"
        marker = "brain"
    ''') + _ADMIN_OAUTH)
    monkeypatch.setenv("BRAIN_AUTH_PRINCIPAL_TOKENS", json.dumps({"root": "root-secret"}))
    monkeypatch.setenv("BRAIN_AUTH_SIGNING_KEY", _signing_key())
    monkeypatch.setenv("BRAIN_PATH", str(brain))
    import importlib
    import brain_api
    importlib.reload(brain_api)
    return brain_api, TestClient(brain_api.app)


def test_admin_edit_logs_action_and_sha(admin_client, monkeypatch):
    api, client = admin_client
    calls = _recorder(monkeypatch, api, "safe_log_admin")
    fake_editor = MagicMock()
    fake_editor.role_set.return_value = "abc1234567"
    monkeypatch.setattr(api, "_editor", lambda: fake_editor)
    r = client.put("/api/admin/roles/maker",
                   json={"read": ["*"], "write": ["*"], "admin": False},
                   headers=ADMIN_AUTH)
    assert r.status_code == 200
    assert len(calls) == 1
    principal, tool, subject = calls[0][0]
    assert tool == "policy_edit"
    assert "abc1234" in subject       # short sha
    assert "maker" in subject


def test_admin_edit_no_log_on_validation_error(admin_client, monkeypatch):
    from lib.policy_edit import PolicyEditError
    api, client = admin_client
    calls = _recorder(monkeypatch, api, "safe_log_admin")
    fake_editor = MagicMock()
    fake_editor.role_set.side_effect = PolicyEditError("bad input")
    monkeypatch.setattr(api, "_editor", lambda: fake_editor)
    r = client.put("/api/admin/roles/maker",
                   json={"read": ["*"], "write": ["*"], "admin": False},
                   headers=ADMIN_AUTH)
    assert r.status_code == 400
    assert calls == []


def test_token_mint_logs_pid_never_token(admin_client, monkeypatch):
    api, client = admin_client
    calls = _recorder(monkeypatch, api, "safe_log_admin")
    fake_store = MagicMock()
    fake_store.mint.return_value = "super-secret-plaintext-token"
    monkeypatch.setattr(api, "_credentials", lambda: fake_store)

    # root is the only rbac principal wired up by _ADMIN_OAUTH — mint on itself.
    r = client.post("/api/admin/principals/root/token", headers=ADMIN_AUTH)
    assert r.status_code == 200
    assert len(calls) == 1
    principal, tool, subject = calls[0][0]
    assert tool == "token_mint"
    assert subject == "root"
    for call in calls:
        for arg in call[0]:
            assert "super-secret-plaintext-token" not in str(arg)
        for v in call[1].values():
            assert "super-secret-plaintext-token" not in str(v)


def test_token_revoke_logs_pid(admin_client, monkeypatch):
    api, client = admin_client
    calls = _recorder(monkeypatch, api, "safe_log_admin")
    fake_store = MagicMock()
    fake_store.revoke.return_value = 1
    monkeypatch.setattr(api, "_credentials", lambda: fake_store)
    r = client.delete("/api/admin/principals/root/token", headers=ADMIN_AUTH)
    assert r.status_code == 200
    assert len(calls) == 1
    principal, tool, subject = calls[0][0]
    assert tool == "token_revoke"
    assert subject == "root"


def test_token_mint_no_log_when_principal_unknown(admin_client, monkeypatch):
    api, client = admin_client
    calls = _recorder(monkeypatch, api, "safe_log_admin")
    fake_store = MagicMock()
    monkeypatch.setattr(api, "_credentials", lambda: fake_store)
    r = client.post("/api/admin/principals/ghost/token", headers=ADMIN_AUTH)
    assert r.status_code == 400
    assert calls == []


# ═══════════════════════════════════════════════════════════════════
# Flag off — the real (unpatched) safe_log_* must never touch the store
# ═══════════════════════════════════════════════════════════════════


def test_flag_off_no_calls_into_store(tmp_path, monkeypatch):
    """With BRAIN_RETRIEVAL_LOG unset, driving a real search must never resolve
    a retrieval-log store — assert at the store layer, not by patching the
    hooks themselves, so this proves the *real* safe_log_reads short-circuits."""
    monkeypatch.delenv("BRAIN_RETRIEVAL_LOG", raising=False)
    import lib.retrieval_log as rl
    monkeypatch.setattr(
        rl, "get_retrieval_log",
        lambda dsn: (_ for _ in ()).throw(AssertionError("must not resolve a store")),
    )
    note = tmp_path / "note.md"
    note.write_text("---\ntitle: X\n---\nbody")
    result = handle_brain_read("note.md", str(tmp_path), principal=OWNER)
    assert "body" in result   # the read itself still works — no-op logging never breaks the request
