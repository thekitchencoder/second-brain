import subprocess
import textwrap
import pytest
from lib.policy_edit import PolicyEditor, PolicyEditError

TOML = """
# fiction profile — hand-written header comment
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
def repo(tmp_path):
    (tmp_path / "profile.toml").write_text(textwrap.dedent(TOML))
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "seed"], cwd=tmp_path, check=True)
    return str(tmp_path)


def _toml(repo):
    import tomllib
    with open(f"{repo}/profile.toml", "rb") as f:
        return tomllib.load(f)


def test_role_set_writes_and_commits(repo):
    ed = PolicyEditor(repo)
    sha = ed.role_set("maker", read=["*"], write=["*"], admin=True)
    data = _toml(repo)
    assert data["auth"]["rbac"]["roles"]["maker"] == {
        "read": ["*"], "write": ["*"], "admin": True}
    log = subprocess.run(["git", "log", "--oneline"], cwd=repo,
                         capture_output=True, text=True).stdout
    assert sha[:7] in log and "policy:" in log


def test_edit_preserves_comments_and_unrelated_content(repo):
    PolicyEditor(repo).role_set("maker", read=["*"], write=["*"])
    text = open(f"{repo}/profile.toml").read()
    assert "hand-written header comment" in text
    assert 'folders = ["X"]' in text


def test_identity_map_requires_existing_role(repo):
    with pytest.raises(PolicyEditError, match="unknown role"):
        PolicyEditor(repo).identity_map("eve@example.com", "ghost")


def test_role_rm_blocked_while_referenced(repo):
    with pytest.raises(PolicyEditError, match="referenced"):
        PolicyEditor(repo).role_rm("reader")


def test_principal_set_and_rm(repo):
    ed = PolicyEditor(repo)
    ed.principal_set("oz-desk", "reader")
    assert _toml(repo)["auth"]["rbac"]["principals"]["oz-desk"] == "reader"
    ed.principal_rm("oz-desk")
    assert "oz-desk" not in _toml(repo)["auth"]["rbac"]["principals"]


def test_non_git_profile_fails_loud(tmp_path):
    (tmp_path / "profile.toml").write_text(textwrap.dedent(TOML))
    with pytest.raises(RuntimeError, match="git"):
        PolicyEditor(str(tmp_path)).role_set("x", read=[], write=[])


def test_push_failure_warns_but_commit_survives(repo, capsys):
    subprocess.run(["git", "remote", "add", "origin",
                    "/nonexistent/remote.git"], cwd=repo, check=True)
    ed = PolicyEditor(repo)
    ed.role_set("maker", read=["*"], write=["*"])
    assert "push failed" in capsys.readouterr().err.lower()
    log = subprocess.run(["git", "log", "--oneline"], cwd=repo,
                         capture_output=True, text=True).stdout
    assert "policy:" in log


def test_push_timeout_warns_but_commit_survives(repo, monkeypatch, capsys):
    subprocess.run(["git", "remote", "add", "origin",
                    "/nonexistent/remote.git"], cwd=repo, check=True)
    real_run = subprocess.run

    def fake_run(args, *a, **kw):
        if args[:2] == ["git", "push"]:
            raise subprocess.TimeoutExpired(cmd=args, timeout=30)
        return real_run(args, *a, **kw)

    monkeypatch.setattr(subprocess, "run", fake_run)
    ed = PolicyEditor(repo)
    sha = ed.role_set("maker", read=["*"], write=["*"])
    err = capsys.readouterr().err.lower()
    assert "timed out" in err
    log = subprocess.run(["git", "log", "--oneline"], cwd=repo,
                         capture_output=True, text=True).stdout
    assert sha[:7] in log and "policy: set role maker" in log


def test_idempotent_edit_returns_head_without_new_commit(repo):
    ed = PolicyEditor(repo)
    sha1 = ed.role_set("maker", read=["*"], write=["*"], admin=True)
    sha2 = ed.role_set("maker", read=["*"], write=["*"], admin=True)  # no-op
    assert sha2 == sha1                       # HEAD unchanged
    log = subprocess.run(["git", "log", "--oneline"], cwd=repo,
                         capture_output=True, text=True).stdout
    assert log.count("policy: set role maker") == 1


def test_commit_failure_rolls_back_file(repo):
    import os, stat
    hook_dir = os.path.join(repo, ".git", "hooks")
    hook = os.path.join(hook_dir, "pre-commit")
    with open(hook, "w") as f:
        f.write("#!/bin/sh\nexit 1\n")
    os.chmod(hook, os.stat(hook).st_mode | stat.S_IEXEC)

    before = open(f"{repo}/profile.toml").read()
    with pytest.raises(RuntimeError, match="git commit failed"):
        PolicyEditor(repo).role_set("maker", read=["*"], write=["*"])
    after = open(f"{repo}/profile.toml").read()
    assert after == before                    # live policy untouched
    status = subprocess.run(["git", "status", "--porcelain"], cwd=repo,
                            capture_output=True, text=True).stdout
    assert "profile.toml" not in status       # nothing staged/dirty
