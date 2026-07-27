import os
import textwrap
import time
import pytest
from lib.policy import ProfilePolicyProvider, get_policy_provider


BASE_TOML = """
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
def profile_dir(tmp_path):
    (tmp_path / "profile.toml").write_text(textwrap.dedent(BASE_TOML))
    return str(tmp_path)


def test_get_rbac_reads_profile(profile_dir):
    p = ProfilePolicyProvider(profile_dir)
    rbac = p.get_rbac()
    assert rbac.default_role == "reader"
    assert rbac.identities["chris@example.com"] == "reader"


def test_get_rbac_hot_reloads_on_mtime_change(profile_dir):
    p = ProfilePolicyProvider(profile_dir)
    assert p.get_rbac().default_role == "reader"
    path = os.path.join(profile_dir, "profile.toml")
    text = open(path).read().replace('default_role = "reader"',
                                     'default_role = "writer"')
    text = text.replace("[auth.rbac.roles.reader]",
                        "[auth.rbac.roles.writer]\nread = [\"work\"]\nwrite = [\"work\"]\n\n[auth.rbac.roles.reader]")
    with open(path, "w") as f:
        f.write(text)
    os.utime(path, (time.time() + 2, time.time() + 2))   # force mtime forward
    assert p.get_rbac().default_role == "writer"


def test_get_rbac_none_when_no_rbac_block(tmp_path):
    (tmp_path / "profile.toml").write_text('name = "t"\nfolders = ["X"]\n[plugin]\nname="t"\nauthor="a"\nmarker="t"\n[auth]\nmode = "none"\n')
    assert ProfilePolicyProvider(str(tmp_path)).get_rbac() is None


def test_auth_mode_from_profile(profile_dir, monkeypatch):
    monkeypatch.delenv("BRAIN_AUTH_MODE", raising=False)
    assert ProfilePolicyProvider(profile_dir).get_auth_mode() == "oauth"


def test_auth_mode_env_override(profile_dir, monkeypatch):
    monkeypatch.setenv("BRAIN_AUTH_MODE", "none")
    assert ProfilePolicyProvider(profile_dir).get_auth_mode() == "none"


def test_auth_mode_invalid_env_fails_loud(profile_dir, monkeypatch):
    monkeypatch.setenv("BRAIN_AUTH_MODE", "totp")
    with pytest.raises(RuntimeError, match="BRAIN_AUTH_MODE"):
        ProfilePolicyProvider(profile_dir).get_auth_mode()


def test_verify_agent_token_env_backend(profile_dir, monkeypatch):
    monkeypatch.setenv("BRAIN_AUTH_PRINCIPAL_TOKENS",
                       '{"fenn-desk": "sekrit-token"}')
    p = ProfilePolicyProvider(profile_dir, credential_backend="env")
    assert p.verify_agent_token("sekrit-token") == "fenn-desk"
    assert p.verify_agent_token("wrong") is None


def test_factory_defaults(profile_dir, monkeypatch):
    monkeypatch.delenv("BRAIN_POLICY_CREDENTIALS", raising=False)

    class _Cfg:
        # NB: resolved via a method (closure) — a class-body assignment would
        # skip the enclosing function scope and hit the module-level fixture.
        @property
        def profile_dir(self):
            return profile_dir
        database_url = ""
    p = get_policy_provider(_Cfg())
    assert p.credential_backend == "env"


def test_factory_postgres_without_dsn_fails_loud(profile_dir, monkeypatch):
    monkeypatch.setenv("BRAIN_POLICY_CREDENTIALS", "postgres")

    class _Cfg:
        @property
        def profile_dir(self):
            return profile_dir
        database_url = ""
    with pytest.raises(RuntimeError, match="BRAIN_DATABASE_URL"):
        get_policy_provider(_Cfg())


def test_factory_unknown_backend_fails_loud(profile_dir, monkeypatch):
    monkeypatch.setenv("BRAIN_POLICY_CREDENTIALS", "vault")

    class _Cfg:
        @property
        def profile_dir(self):
            return profile_dir
        database_url = ""
    with pytest.raises(RuntimeError, match="vault"):
        get_policy_provider(_Cfg())


def test_verify_agent_token_postgres_missing_module_fails_loud(profile_dir, monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "lib.credentials", None)  # forces ImportError
    p = ProfilePolicyProvider(profile_dir, credential_backend="postgres",
                              dsn="postgresql://u:p@h:5432/brain")
    with pytest.raises(RuntimeError, match="credential backend not available"):
        p.verify_agent_token("any-token")


def test_auth_mode_missing_profile_fails_closed(tmp_path, monkeypatch):
    monkeypatch.delenv("BRAIN_AUTH_MODE", raising=False)
    p = ProfilePolicyProvider(str(tmp_path))          # no profile.toml
    with pytest.raises(RuntimeError, match="refusing to fail open"):
        p.get_auth_mode()


def test_auth_mode_missing_profile_env_override_still_works(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAIN_AUTH_MODE", "none")
    assert ProfilePolicyProvider(str(tmp_path)).get_auth_mode() == "none"
