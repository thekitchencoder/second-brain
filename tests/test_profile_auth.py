import textwrap
from lib.profile import load_profile, validate_profile


def _write(tmp_path, body):
    (tmp_path / "profile.toml").write_text(body)
    return load_profile(str(tmp_path))


def _profile(tmp_path, body):
    (tmp_path / "profile.toml").write_text(body)
    (tmp_path / "templates").mkdir(exist_ok=True)
    return load_profile(str(tmp_path)), str(tmp_path)


def test_auth_defaults_to_none_with_no_rbac(tmp_path):
    p = _write(tmp_path, textwrap.dedent('''\
        name = "ace"
        folders = ["Atlas"]
        [plugin]
        name = "second-brain"
        author = "kitchencoder"
        marker = "brain"
    '''))
    assert p.auth.mode == "none"
    assert p.auth.rbac is None


def test_auth_rbac_loads(tmp_path):
    p = _write(tmp_path, textwrap.dedent('''\
        name = "fenn"
        folders = ["canon"]
        [plugin]
        name = "fiction"
        author = "chris"
        marker = "fiction"
        [auth]
        mode = "oauth"
        [auth.rbac]
        default_role = "guest"
        [auth.rbac.roles]
        owner = { layers = ["*"] }
        fenn-agent = { layers = ["fiction"] }
        guest = { layers = [] }
        [auth.rbac.identities]
        "chris@example.com" = "owner"
        [auth.rbac.principals]
        fenn-agent = "fenn-agent"
    '''))
    assert p.auth.mode == "oauth"
    assert p.auth.rbac.default_role == "guest"
    assert p.auth.rbac.roles["fenn-agent"] == {"layers": ["fiction"]}
    assert p.auth.rbac.identities["chris@example.com"] == "owner"
    assert p.auth.rbac.principals["fenn-agent"] == "fenn-agent"


_BASE = '''\
name = "fenn"
folders = ["canon"]
[plugin]
name = "fiction"
author = "chris"
marker = "fiction"
[auth]
mode = "oauth"
'''


def test_oauth_requires_rbac(tmp_path):
    prof, pdir = _profile(tmp_path, _BASE)
    errs = validate_profile(prof, pdir)
    assert any("rbac" in e for e in errs)


def test_identity_role_must_exist(tmp_path):
    body = _BASE + textwrap.dedent('''\
        [auth.rbac]
        [auth.rbac.roles]
        owner = { layers = ["*"] }
        [auth.rbac.identities]
        "x@y.com" = "nonesuch"
    ''')
    prof, pdir = _profile(tmp_path, body)
    errs = validate_profile(prof, pdir)
    assert any("nonesuch" in e for e in errs)


def test_valid_oauth_block_has_no_auth_errors(tmp_path):
    body = _BASE + textwrap.dedent('''\
        [auth.rbac]
        default_role = "owner"
        [auth.rbac.roles]
        owner = { layers = ["*"] }
        [auth.rbac.principals]
        agent = "owner"
    ''')
    prof, pdir = _profile(tmp_path, body)
    errs = [e for e in validate_profile(prof, pdir) if "role" in e or "rbac" in e or "layer" in e]
    assert errs == []
