"""tools/brain_admin.py — the brain-admin CLI.

Local transport is exercised against a real git profile repo (the same
fixture shape as tests/lib/test_policy_edit.py) so mutations are verified
end-to-end (commit lands, sha is printed). Token subcommands mock
PgCredentialStore (no real Postgres in unit tests). The remote transport is
exercised with httpx.Client mocked out entirely.
"""
import json
import subprocess
import textwrap
from unittest.mock import MagicMock

import pytest

import brain_admin
from lib.policy_edit import PolicyEditError

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

[auth.rbac.identities]
"chris@example.com" = "reader"

[auth.rbac.principals]
fenn-desk = "reader"
"""


@pytest.fixture
def tmp_profile_repo(tmp_path, monkeypatch):
    """A brain root whose .brain/ is a real git clone (PolicyEditor requires
    a git repo). BRAIN_PATH is set so Config().profile_dir resolves to it."""
    brain = tmp_path / "brain"
    profile_dir = brain / ".brain"
    profile_dir.mkdir(parents=True)
    (profile_dir / "profile.toml").write_text(textwrap.dedent(TOML))
    subprocess.run(["git", "init", "-q"], cwd=profile_dir, check=True)
    subprocess.run(["git", "add", "-A"], cwd=profile_dir, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "seed"], cwd=profile_dir, check=True)
    monkeypatch.setenv("BRAIN_PATH", str(brain))
    monkeypatch.delenv("BRAIN_POLICY_CREDENTIALS", raising=False)
    monkeypatch.delenv("BRAIN_DATABASE_URL", raising=False)
    monkeypatch.delenv("BRAIN_API_URL", raising=False)
    monkeypatch.delenv("BRAIN_ADMIN_TOKEN", raising=False)
    return profile_dir


def _toml(profile_dir):
    import tomllib
    with open(profile_dir / "profile.toml", "rb") as f:
        return tomllib.load(f)


def _log(profile_dir):
    return subprocess.run(["git", "log", "--oneline"], cwd=profile_dir,
                          capture_output=True, text=True).stdout


# ── local transport: mutations ──────────────────────────────────────────

def test_role_set_local_invokes_editor(tmp_profile_repo, capsys):
    rc = brain_admin.main(["role", "set", "maker", "--read", "*", "--write", "*", "--admin"])
    out = capsys.readouterr().out.strip()
    assert rc == 0
    assert _toml(tmp_profile_repo)["auth"]["rbac"]["roles"]["maker"] == {
        "read": ["*"], "write": ["*"], "admin": True}
    assert out and out[:7] in _log(tmp_profile_repo)


def test_role_set_without_admin_flag_defaults_false(tmp_profile_repo):
    rc = brain_admin.main(["role", "set", "maker", "--read", "*", "--write", "*"])
    assert rc == 0
    spec = _toml(tmp_profile_repo)["auth"]["rbac"]["roles"]["maker"]
    assert spec["read"] == ["*"] and spec["write"] == ["*"] and "admin" not in spec


def test_role_rm_local(tmp_profile_repo):
    brain_admin.main(["role", "set", "maker", "--read", "*", "--write", "*"])
    rc = brain_admin.main(["role", "rm", "maker"])
    assert rc == 0
    assert "maker" not in _toml(tmp_profile_repo)["auth"]["rbac"]["roles"]


def test_identity_map_and_unmap_local(tmp_profile_repo):
    rc = brain_admin.main(["identity", "map", "eve@example.com", "reader"])
    assert rc == 0
    assert _toml(tmp_profile_repo)["auth"]["rbac"]["identities"]["eve@example.com"] == "reader"
    rc = brain_admin.main(["identity", "unmap", "eve@example.com"])
    assert rc == 0
    assert "eve@example.com" not in _toml(tmp_profile_repo)["auth"]["rbac"]["identities"]


def test_principal_set_and_rm_local(tmp_profile_repo):
    rc = brain_admin.main(["principal", "set", "oz-desk", "reader"])
    assert rc == 0
    assert _toml(tmp_profile_repo)["auth"]["rbac"]["principals"]["oz-desk"] == "reader"
    rc = brain_admin.main(["principal", "rm", "oz-desk"])
    assert rc == 0
    assert "oz-desk" not in _toml(tmp_profile_repo)["auth"]["rbac"]["principals"]


def test_default_role_set_local(tmp_profile_repo):
    brain_admin.main(["role", "set", "owner", "--read", "*", "--write", "*"])
    rc = brain_admin.main(["default-role", "set", "owner"])
    assert rc == 0
    assert _toml(tmp_profile_repo)["auth"]["rbac"]["default_role"] == "owner"


# ── local transport: admin log wiring (slice 3) ─────────────────────────

def test_local_role_set_logs_admin_row(tmp_profile_repo, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(brain_admin, "safe_log_admin",
                        lambda *a: calls.append(a))
    rc = brain_admin.main(["role", "set", "maker", "--read", "*", "--write", "*"])
    sha = capsys.readouterr().out.strip()
    assert rc == 0
    assert len(calls) == 1
    principal, tool, subj = calls[0]
    assert principal == "local-admin"
    assert tool == "policy_edit"
    assert sha[:7] in subj


def test_local_token_mint_logs_pid_never_token(tmp_profile_repo, monkeypatch):
    monkeypatch.setenv("BRAIN_POLICY_CREDENTIALS", "postgres")
    monkeypatch.setenv("BRAIN_DATABASE_URL", "postgresql://x/y")
    fake_store = MagicMock()
    fake_store.mint.return_value = "plaintext-token-xyz"
    monkeypatch.setattr(brain_admin.LocalTransport, "_credential_store",
                        lambda self: fake_store)
    calls = []
    monkeypatch.setattr(brain_admin, "safe_log_admin",
                        lambda *a: calls.append(a))
    rc = brain_admin.main(["token", "mint", "fenn-desk"])
    assert rc == 0
    assert calls == [("local-admin", "token_mint", "fenn-desk")]
    assert not any("plaintext-token-xyz" in str(arg)
                  for call in calls for arg in call)


def test_local_mutations_flag_off_no_log_calls_into_store(tmp_profile_repo, monkeypatch):
    # BRAIN_RETRIEVAL_LOG left unset by the fixture — safe_log_admin must
    # short-circuit before ever touching the retrieval-log store, so a
    # local mutation succeeds even if the store would blow up if reached.
    def _boom(dsn):
        raise AssertionError("get_retrieval_log should not be called when flag is off")
    monkeypatch.setattr(brain_admin.retrieval_log, "get_retrieval_log", _boom)
    rc = brain_admin.main(["role", "set", "maker", "--read", "*", "--write", "*"])
    assert rc == 0
    spec = _toml(tmp_profile_repo)["auth"]["rbac"]["roles"]["maker"]
    assert spec["read"] == ["*"] and spec["write"] == ["*"]


# ── local transport: reads ──────────────────────────────────────────────

def test_policy_show_renders_rbac(tmp_profile_repo, capsys):
    rc = brain_admin.main(["policy", "show"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "auth_mode:" in out and "oauth" in out
    assert "reader" in out and "fenn-desk" in out and "chris@example.com" in out


def test_role_list_local(tmp_profile_repo, capsys):
    rc = brain_admin.main(["role", "list"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "reader" in out


def test_principal_list_local(tmp_profile_repo, capsys):
    rc = brain_admin.main(["principal", "list"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "fenn-desk -> reader" in out


# ── local transport: error handling ─────────────────────────────────────

def test_role_rm_referenced_is_user_error(tmp_profile_repo, capsys):
    rc = brain_admin.main(["role", "rm", "reader"])  # still referenced
    err = capsys.readouterr().err
    assert rc == 1
    assert err.startswith("Error:")
    assert "referenced" in err


def test_identity_map_unknown_role_is_user_error(tmp_profile_repo, capsys):
    rc = brain_admin.main(["identity", "map", "eve@example.com", "ghost"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "unknown role" in err


def test_non_git_profile_is_infra_error(tmp_path, monkeypatch, capsys):
    brain = tmp_path / "brain2"
    profile_dir = brain / ".brain"
    profile_dir.mkdir(parents=True)
    (profile_dir / "profile.toml").write_text(textwrap.dedent(TOML))
    monkeypatch.setenv("BRAIN_PATH", str(brain))
    rc = brain_admin.main(["role", "set", "maker", "--read", "*", "--write", "*"])
    err = capsys.readouterr().err
    assert rc == 1
    assert err.startswith("Error (infra):")
    assert "git" in err


# ── tokens (local, PgCredentialStore mocked) ────────────────────────────

def test_token_mint_prints_token_once(tmp_profile_repo, monkeypatch, capsys):
    monkeypatch.setenv("BRAIN_POLICY_CREDENTIALS", "postgres")
    monkeypatch.setenv("BRAIN_DATABASE_URL", "postgresql://x/y")
    fake_store = MagicMock()
    fake_store.mint.return_value = "plaintext-token-xyz"
    monkeypatch.setattr(brain_admin.LocalTransport, "_credential_store",
                        lambda self: fake_store)
    rc = brain_admin.main(["token", "mint", "fenn-desk"])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out.strip() == "plaintext-token-xyz"
    fake_store.mint.assert_called_once_with("fenn-desk")


def test_token_mint_unknown_principal_is_user_error(tmp_profile_repo, monkeypatch, capsys):
    monkeypatch.setenv("BRAIN_POLICY_CREDENTIALS", "postgres")
    monkeypatch.setenv("BRAIN_DATABASE_URL", "postgresql://x/y")
    fake_store = MagicMock()
    monkeypatch.setattr(brain_admin.LocalTransport, "_credential_store",
                        lambda self: fake_store)
    rc = brain_admin.main(["token", "mint", "ghost"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "unknown principal" in err
    fake_store.mint.assert_not_called()


def test_token_mint_env_backend_fails_actionably(tmp_profile_repo, capsys):
    # BRAIN_POLICY_CREDENTIALS left at default ("env") by the fixture.
    rc = brain_admin.main(["token", "mint", "fenn-desk"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "BRAIN_POLICY_CREDENTIALS=postgres" in err
    assert "plaintext" not in err.lower()


def test_token_revoke_local(tmp_profile_repo, monkeypatch, capsys):
    monkeypatch.setenv("BRAIN_POLICY_CREDENTIALS", "postgres")
    monkeypatch.setenv("BRAIN_DATABASE_URL", "postgresql://x/y")
    fake_store = MagicMock()
    fake_store.revoke.return_value = 2
    monkeypatch.setattr(brain_admin.LocalTransport, "_credential_store",
                        lambda self: fake_store)
    rc = brain_admin.main(["token", "revoke", "fenn-desk"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "2" in out and "fenn-desk" in out
    fake_store.revoke.assert_called_once_with("fenn-desk")


def test_token_list_local_never_prints_secret(tmp_profile_repo, monkeypatch, capsys):
    monkeypatch.setenv("BRAIN_POLICY_CREDENTIALS", "postgres")
    monkeypatch.setenv("BRAIN_DATABASE_URL", "postgresql://x/y")
    fake_store = MagicMock()
    fake_store.list_tokens.return_value = [
        {"principal_id": "fenn-desk", "created_at": "2026-01-01", "revoked_at": None},
    ]
    monkeypatch.setattr(brain_admin.LocalTransport, "_credential_store",
                        lambda self: fake_store)
    rc = brain_admin.main(["token", "list"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "fenn-desk" in out and "active" in out
    assert "plaintext" not in out.lower() and "token-" not in out


# ── remote transport ─────────────────────────────────────────────────────

class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, calls, response):
        self._calls = calls
        self._response = response

    def request(self, method, path, json=None):
        self._calls.append((method, path, json))
        return self._response


def test_remote_transport_puts_role(monkeypatch):
    calls = []
    fake_client = _FakeClient(calls, _FakeResponse(200, {"commit": "deadbeef"}))
    client_kwargs = {}

    def fake_ctor(*args, **kwargs):
        client_kwargs.update(kwargs)
        return fake_client

    monkeypatch.setattr(brain_admin.httpx, "Client", fake_ctor)
    rc = brain_admin.main(["--url", "http://x", "--token", "t",
                           "role", "set", "maker", "--read", "*", "--write", "*", "--admin"])
    assert rc == 0
    assert calls == [("PUT", "/api/admin/roles/maker",
                      {"read": ["*"], "write": ["*"], "admin": True})]
    assert client_kwargs["headers"]["Authorization"] == "Bearer t"


def test_remote_transport_policy_show(monkeypatch, capsys):
    payload = {"auth_mode": "oauth", "credential_backend": "env",
               "rbac": {"default_role": "reader", "roles": {"reader": {"read": ["*"], "write": []}},
                        "identities": {}, "principals": {}}}
    fake_client = _FakeClient([], _FakeResponse(200, payload))
    monkeypatch.setattr(brain_admin.httpx, "Client", lambda *a, **kw: fake_client)
    rc = brain_admin.main(["--url", "http://x", "--token", "t", "policy", "show"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "oauth" in out and "reader" in out


def test_remote_transport_404_reports_not_found_or_not_authorized(monkeypatch, capsys):
    fake_client = _FakeClient([], _FakeResponse(404, {"detail": "Not Found"}))
    monkeypatch.setattr(brain_admin.httpx, "Client", lambda *a, **kw: fake_client)
    rc = brain_admin.main(["--url", "http://x", "--token", "bad", "policy", "show"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "not found or not authorized" in err.lower()


def test_remote_transport_user_error_is_400(monkeypatch, capsys):
    fake_client = _FakeClient([], _FakeResponse(400, {"detail": "unknown role: ghost"}))
    monkeypatch.setattr(brain_admin.httpx, "Client", lambda *a, **kw: fake_client)
    rc = brain_admin.main(["--url", "http://x", "--token", "t",
                           "identity", "map", "eve@example.com", "ghost"])
    err = capsys.readouterr().err
    assert rc == 1
    assert err.startswith("Error:")
    assert "unknown role: ghost" in err


def test_remote_transport_token_mint(monkeypatch, capsys):
    fake_client = _FakeClient([], _FakeResponse(200, {"principal_id": "fenn-desk", "token": "secret-abc"}))
    monkeypatch.setattr(brain_admin.httpx, "Client", lambda *a, **kw: fake_client)
    rc = brain_admin.main(["--url", "http://x", "--token", "t", "token", "mint", "fenn-desk"])
    out = capsys.readouterr().out
    assert rc == 0
    assert out.strip() == "secret-abc"


def test_remote_transport_token_list(monkeypatch, capsys):
    calls = []
    payload = {"tokens": [
        {"principal_id": "fenn-desk", "created_at": "2026-01-01", "revoked_at": None},
    ]}
    fake_client = _FakeClient(calls, _FakeResponse(200, payload))
    monkeypatch.setattr(brain_admin.httpx, "Client", lambda *a, **kw: fake_client)
    rc = brain_admin.main(["--url", "http://x", "--token", "t", "token", "list"])
    out = capsys.readouterr().out
    assert rc == 0
    assert calls == [("GET", "/api/admin/tokens", None)]
    assert "fenn-desk" in out and "active" in out


def test_remote_transport_default_role_set(monkeypatch, capsys):
    calls = []
    fake_client = _FakeClient(calls, _FakeResponse(200, {"commit": "cafebabe"}))
    monkeypatch.setattr(brain_admin.httpx, "Client", lambda *a, **kw: fake_client)
    rc = brain_admin.main(["--url", "http://x", "--token", "t", "default-role", "set", "owner"])
    out = capsys.readouterr().out
    assert rc == 0
    assert calls == [("PUT", "/api/admin/default-role", {"role": "owner"})]
    assert out.strip() == "cafebabe"


def test_url_without_token_is_infra_error(capsys):
    rc = brain_admin.main(["--url", "http://x", "policy", "show"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "--token" in err


# ── log query (local, PgRetrievalLog mocked) ────────────────────────────
# Reading the log is deliberately not itself an admin-logged event — no
# assertion needed here, there's simply no safe_log_admin call in the path.


def test_log_query_local_passes_filters(tmp_profile_repo, monkeypatch, capsys):
    monkeypatch.setenv("BRAIN_RETRIEVAL_LOG", "postgres")
    monkeypatch.setenv("BRAIN_DATABASE_URL", "postgresql://x/y")
    fake_log = MagicMock()
    fake_log.query.return_value = [
        {"ts": "2026-01-01T00:00:00+00:00", "principal_id": "x", "kind": "read",
         "tool": "brain_search", "subject": None, "filepath": "a/b.md", "request_id": None},
    ]
    monkeypatch.setattr(brain_admin.retrieval_log, "get_retrieval_log", lambda dsn: fake_log)
    rc = brain_admin.main(["log", "query", "--principal", "x", "--kind", "read",
                           "--tool", "brain_search", "--since", "2026-01-01",
                           "--until", "2026-12-31", "--path", "a", "--limit", "5"])
    out = capsys.readouterr().out
    assert rc == 0
    fake_log.query.assert_called_once_with(
        principal="x", kind="read", tool="brain_search",
        since="2026-01-01", until="2026-12-31", path="a", limit=5)
    assert "brain_search" in out and "a/b.md" in out


def test_log_query_local_defaults_all_filters_none(tmp_profile_repo, monkeypatch, capsys):
    monkeypatch.setenv("BRAIN_RETRIEVAL_LOG", "postgres")
    monkeypatch.setenv("BRAIN_DATABASE_URL", "postgresql://x/y")
    fake_log = MagicMock()
    fake_log.query.return_value = []
    monkeypatch.setattr(brain_admin.retrieval_log, "get_retrieval_log", lambda dsn: fake_log)
    rc = brain_admin.main(["log", "query"])
    out = capsys.readouterr().out
    assert rc == 0
    fake_log.query.assert_called_once_with(
        principal=None, kind=None, tool=None, since=None, until=None, path=None, limit=100)
    assert "no entries" in out.lower()


def test_log_query_local_off_fails_actionably(tmp_profile_repo, capsys):
    # BRAIN_RETRIEVAL_LOG left unset by the fixture.
    rc = brain_admin.main(["log", "query"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "BRAIN_RETRIEVAL_LOG=postgres" in err


# ── log query (remote) ──────────────────────────────────────────────────


def test_remote_transport_log_query(monkeypatch, capsys):
    calls = []
    payload = {"entries": [
        {"ts": "2026-01-01T00:00:00+00:00", "principal_id": "x", "kind": "read",
         "tool": "brain_search", "subject": None, "filepath": "a/b.md", "request_id": None},
    ]}
    fake_client = _FakeClient(calls, _FakeResponse(200, payload))
    monkeypatch.setattr(brain_admin.httpx, "Client", lambda *a, **kw: fake_client)
    rc = brain_admin.main(["--url", "http://x", "--token", "t", "log", "query",
                           "--principal", "x", "--kind", "read", "--tool", "brain_search",
                           "--since", "2026-01-01", "--until", "2026-12-31",
                           "--path", "a", "--limit", "5"])
    out = capsys.readouterr().out
    assert rc == 0
    assert calls == [("GET",
                      "/api/admin/retrievals?principal=x&kind=read&tool=brain_search&"
                      "since=2026-01-01&until=2026-12-31&path=a&limit=5", None)]
    assert "brain_search" in out and "a/b.md" in out


def test_remote_transport_log_query_only_sends_non_none_filters(monkeypatch, capsys):
    calls = []
    fake_client = _FakeClient(calls, _FakeResponse(200, {"entries": []}))
    monkeypatch.setattr(brain_admin.httpx, "Client", lambda *a, **kw: fake_client)
    rc = brain_admin.main(["--url", "http://x", "--token", "t", "log", "query"])
    assert rc == 0
    assert calls == [("GET", "/api/admin/retrievals?limit=100", None)]


# ── argparse plumbing ────────────────────────────────────────────────────

def test_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        brain_admin.main(["--help"])
    assert exc.value.code == 0
    assert "brain-admin" in capsys.readouterr().out


def test_role_set_help_documents_flags(capsys):
    with pytest.raises(SystemExit) as exc:
        brain_admin.main(["role", "set", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--read" in out and "--write" in out and "--admin" in out
