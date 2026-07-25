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


def _run_init(brain_path):
    env = dict(os.environ, BRAIN_PATH=str(brain_path))
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
