# tests/lib/test_config_profile.py
import textwrap
from lib.config import Config


def _seed_profile(brain_dir):
    bd = brain_dir / ".brain"
    bd.mkdir()
    (bd / "profile.toml").write_text(textwrap.dedent("""
        name = "ace"
        folders = ["Atlas"]
        [plugin]
        name = "second-brain"
        author = "kitchencoder"
        marker = "brain"
        [skills]
        global = []
        vault = []
        [zk]
        default_template = "default.md"
        [auth]
        mode = "none"
    """))


def test_config_profile_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAIN_PATH", str(tmp_path))
    cfg = Config()
    assert cfg.profile_dir == str(tmp_path / ".brain")


def test_config_load_profile(tmp_path, monkeypatch):
    _seed_profile(tmp_path)
    monkeypatch.setenv("BRAIN_PATH", str(tmp_path))
    cfg = Config()
    p = cfg.load_profile()
    assert p.name == "ace"
    assert p.folders == ["Atlas"]
    # cached — same object on second call
    assert cfg.load_profile() is p
