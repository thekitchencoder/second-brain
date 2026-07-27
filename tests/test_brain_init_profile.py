import os
import subprocess
import sys
import textwrap
import tomllib

_HERE = os.path.dirname(__file__)
_BRAIN_INIT_CANDIDATES = [
    os.path.join(_HERE, "..", "tools", "brain-init"),  # local dev repo layout
    os.path.join(_HERE, "..", "brain-init"),           # container: tools/ flattened into brain-tools/
]
_BRAIN_INIT = next(p for p in _BRAIN_INIT_CANDIDATES if os.path.isfile(p))

_FIXTURE_ACE = os.path.join(_HERE, "fixtures", "profile-ace")

# Forces any accidental network clone to fail fast and deterministically,
# online or offline.
_DEAD_PROXY = {"https_proxy": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9"}


def _run_init(brain_path):
    # Unit tests seed from the frozen fixture; the remote-default path has
    # its own dedicated tests below.
    env = dict(os.environ, BRAIN_PATH=str(brain_path),
               BRAIN_PROFILE_REPO=_FIXTURE_ACE)
    return subprocess.run(
        [sys.executable, _BRAIN_INIT, "--auto", str(brain_path)],
        capture_output=True, text=True, env=env,
    )


def test_init_seeds_brain_dir_from_ace(tmp_path):
    r = _run_init(tmp_path)
    assert r.returncode == 0, r.stderr
    assert os.path.isfile(tmp_path / ".brain" / "profile.toml")
    assert os.path.isdir(tmp_path / ".brain" / "templates")


def test_init_second_run_is_idempotent(tmp_path):
    _run_init(tmp_path)
    r = _run_init(tmp_path)
    assert r.returncode == 0, r.stderr
    assert os.path.isfile(tmp_path / ".brain" / "profile.toml")


def test_init_creates_profile_folders(tmp_path):
    _run_init(tmp_path)
    for folder in ["Atlas", "Efforts", "Cards", "Calendar", "Sources"]:
        assert os.path.isdir(tmp_path / folder), f"missing {folder}"


def test_init_composes_zk_config_with_templates_excluded(tmp_path):
    _run_init(tmp_path)
    cfg_path = tmp_path / ".zk" / "config.toml"
    assert cfg_path.is_file()
    data = tomllib.loads(cfg_path.read_text())
    assert "templates/" in data["notebook"]["exclude"]
    assert data["note"]["filename"] == "{{slug title}}"
    assert data["extra"]["author"] == "Chris"


def test_init_copies_templates_from_profile(tmp_path):
    _run_init(tmp_path)
    assert os.path.isfile(tmp_path / ".zk" / "templates" / "default.md")


def test_init_composes_zk_config_from_custom_profile_conventions(tmp_path):
    # Pre-seed a custom profile whose zk conventions + template name differ from
    # ace's, so the composed .zk/config.toml and copied templates can ONLY come
    # from _PROFILE.zk / _PROFILE_DIR, not a static zk/ copy.
    bd = tmp_path / ".brain"
    (bd / "templates").mkdir(parents=True)
    (bd / "templates" / "default.md").write_text("# default\n")
    (bd / "templates" / "custom-note.md").write_text("# custom\n")  # ace has no such template
    (bd / "profile.toml").write_text(textwrap.dedent('''
        name = "custom"
        folders = ["Zone"]
        [plugin]
        name = "custom-brain"
        author = "kitchencoder"
        marker = "custom"
        [skills]
        global = []
        vault = []
        [zk]
        filename = "{{id}}"
        default_template = "default.md"
        author = "Ziggy"
        [auth]
        mode = "none"
    '''))
    r = _run_init(tmp_path)
    assert r.returncode == 0, r.stderr
    data = tomllib.loads((tmp_path / ".zk" / "config.toml").read_text())
    assert data["note"]["filename"] == "{{id}}"       # custom, not ace's "{{slug title}}"
    assert data["extra"]["author"] == "Ziggy"         # custom, not "Chris"
    assert "templates/" in data["notebook"]["exclude"]  # structural guarantee holds
    assert (tmp_path / ".zk" / "templates" / "custom-note.md").is_file()  # profile-sourced


import json


def test_init_stages_all_11_global_skills(tmp_path):
    _run_init(tmp_path)
    staged = os.listdir(tmp_path / ".ai" / "brain-plugin" / "skills")
    assert "brain-distil" in staged  # the fix
    assert len(staged) == 11


def test_init_stages_vault_skills_from_profile(tmp_path):
    _run_init(tmp_path)
    vault = os.listdir(tmp_path / ".claude" / "skills")
    assert set(vault) >= {"brain-daily", "brain-extract", "brain-hygiene",
                          "brain-rename", "brain-reorganise"}


def test_plugin_manifest_uses_profile_identity(tmp_path):
    _run_init(tmp_path)
    manifest = json.loads(
        (tmp_path / ".ai" / "brain-plugin" / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["name"] == "second-brain"
    assert manifest["author"]["name"] == "kitchencoder"


def test_mcp_json_server_key_is_brain_for_ace(tmp_path):
    _run_init(tmp_path)
    mcp = json.loads((tmp_path / ".ai" / "brain-plugin" / ".mcp.json").read_text())
    assert list(mcp["mcpServers"].keys()) == ["brain"]  # today's value, not plugin.name


import subprocess as _sp


def _make_local_profile_repo(tmp_path, name="custom"):
    """Create a git repo containing a minimal valid profile; return its path."""
    repo = tmp_path / f"{name}-profile-src"
    (repo / "templates").mkdir(parents=True)
    (repo / "templates" / "default.md").write_text("# default\n")
    (repo / "profile.toml").write_text(
        'name = "%s"\n'
        'folders = ["Zone"]\n'
        '[plugin]\n'
        'name = "%s-brain"\n'
        'author = "kitchencoder"\n'
        'marker = "%s"\n'
        'mcp_server = "%s"\n'
        '[skills]\n'
        'global = []\n'
        'vault = []\n'
        '[zk]\n'
        'default_template = "default.md"\n'
        '[auth]\n'
        'mode = "none"\n' % (name, name, name, name)
    )
    _sp.run(["git", "init", "-q"], cwd=repo, check=True)
    _sp.run(["git", "add", "-A"], cwd=repo, check=True)
    _sp.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo


def test_profile_repo_flag_clones_local_git_repo(tmp_path):
    repo = _make_local_profile_repo(tmp_path)
    brain = tmp_path / "brain"; brain.mkdir()
    env = dict(os.environ, BRAIN_PATH=str(brain))
    r = _sp.run([sys.executable, _BRAIN_INIT, "--auto", "--profile-repo", str(repo), str(brain)],
                capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    # the CUSTOM profile was used, not bundled ace
    data = tomllib.loads((brain / ".brain" / "profile.toml").read_text())
    assert data["name"] == "custom"
    # cloned → .brain is a git repo (enables `update`)
    assert (brain / ".brain" / ".git").is_dir()


def test_profile_repo_env_copies_plain_dir(tmp_path):
    # A plain (non-git) directory is copied, not cloned.
    src = tmp_path / "plain-profile"
    (src / "templates").mkdir(parents=True)
    (src / "templates" / "default.md").write_text("# d\n")
    (src / "profile.toml").write_text(
        'name = "plain"\nfolders = ["Z"]\n[plugin]\nname="p"\nauthor="a"\nmarker="p"\n'
        '[skills]\nglobal=[]\nvault=[]\n[zk]\ndefault_template="default.md"\n[auth]\nmode="none"\n')
    brain = tmp_path / "brain2"; brain.mkdir()
    env = dict(os.environ, BRAIN_PATH=str(brain), BRAIN_PROFILE_REPO=str(src))
    r = _sp.run([sys.executable, _BRAIN_INIT, "--auto", str(brain)],
                capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert tomllib.loads((brain / ".brain" / "profile.toml").read_text())["name"] == "plain"
    assert not (brain / ".brain" / ".git").exists()  # copied, not cloned


def test_default_source_is_remote_and_fails_loud_when_unreachable(tmp_path):
    # No custom source → brain-init attempts the default remote clone. The
    # dead proxy makes it fail; the error must name the URL and the remedy.
    brain = tmp_path / "brain3"; brain.mkdir()
    env = dict(os.environ, BRAIN_PATH=str(brain), **_DEAD_PROXY)
    env.pop("BRAIN_PROFILE_REPO", None)
    r = _sp.run([sys.executable, _BRAIN_INIT, "--auto", str(brain)],
                capture_output=True, text=True, env=env)
    assert r.returncode != 0
    out = r.stdout + r.stderr
    assert "https://github.com/thekitchencoder/brain-profile-ace" in out
    assert "BRAIN_PROFILE_REPO" in out
    assert "traceback" not in out.lower()
    assert not (brain / ".brain" / "profile.toml").exists()


def test_existing_brain_short_circuits_default_clone(tmp_path):
    # A brain with .brain/profile.toml never resolves a source → no network.
    brain = tmp_path / "brain4"; brain.mkdir()
    seed_env = dict(os.environ, BRAIN_PATH=str(brain),
                    BRAIN_PROFILE_REPO=_FIXTURE_ACE)
    r = _sp.run([sys.executable, _BRAIN_INIT, "--auto", str(brain)],
                capture_output=True, text=True, env=seed_env)
    assert r.returncode == 0, r.stderr
    env = dict(os.environ, BRAIN_PATH=str(brain), **_DEAD_PROXY)
    env.pop("BRAIN_PROFILE_REPO", None)
    r = _sp.run([sys.executable, _BRAIN_INIT, "--auto", str(brain)],
                capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr


def test_profile_repo_value_equal_to_brain_path_is_not_swallowed(tmp_path):
    repo = _make_local_profile_repo(tmp_path)
    brain = tmp_path / "brain"; brain.mkdir()
    # pass the SAME string is unrealistic; instead assert the brain path (distinct) is honored
    # even though a value is given — index-based parsing must not drop the positional.
    env = dict(os.environ, BRAIN_PATH=str(brain))
    r = _sp.run([sys.executable, _BRAIN_INIT, "--auto", "--profile-repo", str(repo), str(brain)],
                capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert (brain / ".brain" / "profile.toml").is_file()


def test_profile_repo_flag_like_value_errors_cleanly(tmp_path):
    brain = tmp_path / "brain2"; brain.mkdir()
    r = _sp.run([sys.executable, _BRAIN_INIT, "--auto", "--profile-repo", "--auto", str(brain)],
                capture_output=True, text=True, env=dict(os.environ, BRAIN_PATH=str(brain)))
    assert r.returncode != 0
    assert "requires a value" in (r.stdout + r.stderr).lower()
    assert "traceback" not in (r.stdout + r.stderr).lower()


def test_init_profile_without_templates_dir_is_clean(tmp_path):
    # A custom profile that declares no zk.default_template and ships no templates/.
    bd = tmp_path / ".brain"; bd.mkdir()
    (bd / "profile.toml").write_text(
        'name = "min"\nfolders = ["Z"]\n[plugin]\nname="m"\nauthor="a"\nmarker="m"\n'
        '[skills]\nglobal=[]\nvault=[]\n[zk]\n[auth]\nmode="none"\n')
    r = _run_init(tmp_path)
    assert r.returncode == 0, r.stderr        # no FileNotFoundError crash
    assert (tmp_path / ".zk" / "config.toml").is_file()


def test_init_writes_brain_gitignore(tmp_path):
    _run_init(tmp_path)
    gi = (tmp_path / ".gitignore").read_text()
    for entry in (".ai/", ".zk/", ".brain/.git/"):
        assert entry in gi


def test_init_gitignore_preserves_existing_lines(tmp_path):
    (tmp_path / ".gitignore").write_text("mine/\n")
    _run_init(tmp_path)
    gi = (tmp_path / ".gitignore").read_text()
    assert "mine/" in gi and ".ai/" in gi


def test_profile_repo_clone_without_profile_toml_errors_and_cleans_up(tmp_path):
    # A git repo that clones fine but has no profile.toml → clean error, no poisoned .brain/
    bad = tmp_path / "bad-src"; bad.mkdir()
    (bad / "readme.md").write_text("not a profile\n")
    _sp.run(["git", "init", "-q"], cwd=bad, check=True)
    _sp.run(["git", "add", "-A"], cwd=bad, check=True)
    _sp.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "x"], cwd=bad, check=True)
    brain = tmp_path / "brain"; brain.mkdir()
    r = _sp.run([sys.executable, _BRAIN_INIT, "--auto", "--profile-repo", str(bad), str(brain)],
                capture_output=True, text=True, env=dict(os.environ, BRAIN_PATH=str(brain)))
    assert r.returncode != 0
    assert "traceback" not in (r.stdout + r.stderr).lower()
    assert not os.path.exists(brain / ".brain")   # poisoned partial seed removed


def test_preexisting_brain_not_deleted_on_validation_error(tmp_path):
    # If .brain/ already existed (not freshly seeded), a validation error must NOT delete it.
    brain = tmp_path / "brain2"; brain.mkdir()
    bd = brain / ".brain"; bd.mkdir()
    (bd / "profile.toml").write_text('name="x"\n')  # missing required keys → ProfileError/invalid
    sentinel = bd / "user-data.txt"; sentinel.write_text("keep me\n")
    r = _sp.run([sys.executable, _BRAIN_INIT, "--auto", str(brain)],
                capture_output=True, text=True, env=dict(os.environ, BRAIN_PATH=str(brain)))
    assert r.returncode != 0
    assert sentinel.exists()   # pre-existing .brain/ preserved
