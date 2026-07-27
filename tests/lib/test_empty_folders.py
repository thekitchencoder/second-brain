"""folders = [] is a legitimate 'no prescribed taxonomy' choice (obsidian
profile); a MISSING folders key remains an error."""
import pytest
from lib.profile import load_profile, validate_profile, ProfileError


def _write_profile(tmp_path, body):
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "default.md").write_text("# d\n")
    (tmp_path / "profile.toml").write_text(body)
    return str(tmp_path)


_BASE = (
    '[plugin]\nname = "m"\nauthor = "a"\nmarker = "m"\n'
    '[skills]\nglobal = []\nvault = []\n'
    '[zk]\ndefault_template = "default.md"\n'
    '[auth]\nmode = "none"\n'
)


def test_empty_folders_is_valid(tmp_path):
    d = _write_profile(tmp_path, 'name = "min"\nfolders = []\n' + _BASE)
    p = load_profile(d)
    assert p.folders == []
    assert validate_profile(p, d) == []


def test_missing_folders_key_still_errors(tmp_path):
    d = _write_profile(tmp_path, 'name = "min"\n' + _BASE)
    with pytest.raises(ProfileError):
        load_profile(d)
