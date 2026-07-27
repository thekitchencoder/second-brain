"""Integration tests for per-brain identity (brain name, MCP URL/ports).

All runs seed from the frozen fixture (offline) and scrub the four identity
env keys so a developer's shell can't leak values into assertions.
"""
import json
import os
import subprocess
import sys

_HERE = os.path.dirname(__file__)
_BRAIN_INIT = next(p for p in (
    os.path.join(_HERE, "..", "tools", "brain-init"),   # local dev repo layout
    os.path.join(_HERE, "..", "brain-init"),            # container layout
) if os.path.isfile(p))
_FIXTURE_ACE = os.path.join(_HERE, "fixtures", "profile-ace")

_IDENTITY_KEYS = ("BRAIN_NAME", "BRAIN_MCP_PUBLIC_URL",
                  "BRAIN_MCP_HOST_PORT", "BRAIN_API_HOST_PORT")


def _run_init(brain_path, *extra_args, **env_overrides):
    env = dict(os.environ, BRAIN_PATH=str(brain_path),
               BRAIN_PROFILE_REPO=_FIXTURE_ACE)
    for k in _IDENTITY_KEYS:
        env.pop(k, None)
    env.update({k: str(v) for k, v in env_overrides.items()})
    return subprocess.run(
        [sys.executable, _BRAIN_INIT, "--auto", *extra_args, str(brain_path)],
        capture_output=True, text=True, env=env)


def test_invalid_brain_name_exits_1_before_writing(tmp_path):
    r = _run_init(tmp_path, "--brain-name", "Bad_Name")
    assert r.returncode != 0
    out = r.stdout + r.stderr
    assert "lowercase" in out
    assert "traceback" not in out.lower()
    assert not (tmp_path / ".brain").exists()


def test_invalid_port_exits_1(tmp_path):
    r = _run_init(tmp_path, "--mcp-port", "notaport")
    assert r.returncode != 0
    assert "1-65535" in (r.stdout + r.stderr)
    assert not (tmp_path / ".brain").exists()


def test_invalid_mcp_url_exits_1(tmp_path):
    r = _run_init(tmp_path, "--mcp-url", "ftp://x")
    assert r.returncode != 0
    assert "http" in (r.stdout + r.stderr)
    assert not (tmp_path / ".brain").exists()


def test_name_flag_persists_into_existing_env(tmp_path):
    (tmp_path / ".env").write_text("EMBEDDING_MODEL=m\n# BRAIN_NAME=\n")
    r = _run_init(tmp_path, "--brain-name", "work")
    assert r.returncode == 0, r.stderr
    env = (tmp_path / ".env").read_text()
    assert "BRAIN_NAME=work" in env
    assert "EMBEDDING_MODEL=m" in env          # untouched neighbours
    assert "# BRAIN_NAME=" not in env          # placeholder replaced, not duplicated


def test_flag_beats_env_var_beats_dot_env(tmp_path):
    (tmp_path / ".env").write_text("BRAIN_NAME=dotenv\n")
    r = _run_init(tmp_path, "--brain-name", "flag", BRAIN_NAME="envvar")
    assert r.returncode == 0, r.stderr
    assert "BRAIN_NAME=flag" in (tmp_path / ".env").read_text()


def test_no_env_file_means_no_persistence(tmp_path):
    r = _run_init(tmp_path, BRAIN_NAME="work")
    assert r.returncode == 0, r.stderr
    assert not (tmp_path / ".env").exists()


def _staged(brain_path, *parts):
    return os.path.join(str(brain_path), ".ai", "brain-plugin", *parts)


def test_named_init_qualifies_staged_identity(tmp_path):
    r = _run_init(tmp_path, "--brain-name", "work")
    assert r.returncode == 0, r.stderr
    manifest = json.loads(open(_staged(tmp_path, ".claude-plugin", "plugin.json")).read())
    assert manifest["name"] == "second-brain-work"
    marketplace = json.loads(
        open(os.path.join(str(tmp_path), ".ai", ".claude-plugin", "marketplace.json")).read())
    assert marketplace["name"] == "second-brain-work"
    assert marketplace["plugins"][0]["name"] == "second-brain-work"
    mcp = json.loads(open(_staged(tmp_path, ".mcp.json")).read())
    assert list(mcp["mcpServers"].keys()) == ["brain-work"]
    assert mcp["mcpServers"]["brain-work"]["url"] == "http://127.0.0.1:7780/mcp/"
    assert open(_staged(tmp_path, "hooks", "marker")).read().strip() == "brain-work"


def test_mcp_port_flows_into_staged_url(tmp_path):
    r = _run_init(tmp_path, "--mcp-port", "7781")
    assert r.returncode == 0, r.stderr
    mcp = json.loads(open(_staged(tmp_path, ".mcp.json")).read())
    assert mcp["mcpServers"]["brain"]["url"] == "http://127.0.0.1:7781/mcp/"


def test_mcp_public_url_staged_verbatim_and_beats_port(tmp_path):
    r = _run_init(tmp_path, "--mcp-url", "https://brain.example.com/mcp/",
                  "--mcp-port", "9999")
    assert r.returncode == 0, r.stderr
    mcp = json.loads(open(_staged(tmp_path, ".mcp.json")).read())
    assert mcp["mcpServers"]["brain"]["url"] == "https://brain.example.com/mcp/"


def test_restage_from_dot_env_is_stable_without_flags(tmp_path):
    # The container re-runs `brain-init --auto` on every start with no flags;
    # identity persisted in .env must survive that round-trip.
    (tmp_path / ".env").write_text("EMBEDDING_MODEL=m\n")
    r = _run_init(tmp_path, "--brain-name", "work")
    assert r.returncode == 0, r.stderr
    r = _run_init(tmp_path)   # no flags, no identity env vars
    assert r.returncode == 0, r.stderr
    manifest = json.loads(open(_staged(tmp_path, ".claude-plugin", "plugin.json")).read())
    assert manifest["name"] == "second-brain-work"


def test_default_init_is_unqualified_with_default_marker(tmp_path):
    r = _run_init(tmp_path)
    assert r.returncode == 0, r.stderr
    manifest = json.loads(open(_staged(tmp_path, ".claude-plugin", "plugin.json")).read())
    assert manifest["name"] == "second-brain"
    mcp = json.loads(open(_staged(tmp_path, ".mcp.json")).read())
    assert list(mcp["mcpServers"].keys()) == ["brain"]
    assert mcp["mcpServers"]["brain"]["url"] == "http://127.0.0.1:7780/mcp/"
    assert open(_staged(tmp_path, "hooks", "marker")).read().strip() == "brain"


def _load_brain_init_module():
    import importlib.machinery
    import importlib.util
    loader = importlib.machinery.SourceFileLoader("brain_init_mod", _BRAIN_INIT)
    spec = importlib.util.spec_from_loader("brain_init_mod", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_generate_env_writes_identity_block(tmp_path):
    mod = _load_brain_init_module()
    cfg = {"embedding_base_url": "http://x/v1", "embedding_model": "m",
           "brain_name": "work", "mcp_public_url": "",
           "mcp_host_port": "7781", "api_host_port": "7779"}
    mod.generate_env(str(tmp_path), cfg)
    env = (tmp_path / ".env").read_text()
    assert "BRAIN_NAME=work" in env
    assert "BRAIN_MCP_HOST_PORT=7781" in env
    assert "# BRAIN_API_HOST_PORT=7779" in env      # default stays a commented example
    assert "# BRAIN_MCP_PUBLIC_URL=" in env


def test_generate_env_without_identity_keeps_placeholders(tmp_path):
    mod = _load_brain_init_module()
    mod.generate_env(str(tmp_path), {"embedding_base_url": "http://x/v1",
                                     "embedding_model": "m"})
    env = (tmp_path / ".env").read_text()
    assert "# BRAIN_NAME=" in env
    assert "BRAIN_NAME=w" not in env


def test_prompt_identity_defaults_come_from_existing_env(tmp_path, monkeypatch):
    # Regenerating .env must not silently drop an existing brain's identity:
    # prompt defaults mirror resolve_identity's precedence.
    for k in _IDENTITY_KEYS:
        monkeypatch.delenv(k, raising=False)
    mod = _load_brain_init_module()
    env_path = tmp_path / ".env"
    env_path.write_text("BRAIN_NAME=work\nBRAIN_MCP_HOST_PORT=7782\n")
    mod._ask_input = lambda prompt, default="": default   # user presses Enter
    cfg = {}
    mod._prompt_identity(cfg, env_path=str(env_path))
    assert cfg["brain_name"] == "work"
    assert cfg["mcp_host_port"] == "7782"
    assert cfg["api_host_port"] == "7779"


def test_rename_prints_guided_cleanup_note(tmp_path):
    r = _run_init(tmp_path, "--brain-name", "work")
    assert r.returncode == 0, r.stderr
    r = _run_init(tmp_path, "--brain-name", "home")
    assert r.returncode == 0, r.stderr
    assert "previously staged as 'second-brain-work'" in r.stdout
    assert "claude plugin uninstall second-brain-work" in r.stdout


def test_unchanged_restage_prints_no_rename_note(tmp_path):
    _run_init(tmp_path, "--brain-name", "work")
    r = _run_init(tmp_path, "--brain-name", "work")
    assert r.returncode == 0, r.stderr
    assert "previously staged" not in r.stdout
