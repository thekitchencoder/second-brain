import json
import os
import subprocess

_HOOK = os.path.join(os.path.dirname(__file__), "fixtures", "profile-ace", "hooks",
                     "session-start.sh")


def _run_hook(cwd):
    r = subprocess.run(["bash", _HOOK], cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]


def test_hook_silent_when_no_marker(tmp_path):
    # A project with no brain-marked CLAUDE.md should get empty context.
    ctx = _run_hook(str(tmp_path))
    assert ctx == ""


def test_hook_primes_when_marker_present(tmp_path):
    (tmp_path / "CLAUDE.md").write_text(
        "# Project\n<!-- brain -->\neffort: Efforts/x.md\nsummary: hi\n<!-- /brain -->\n")
    ctx = _run_hook(str(tmp_path))
    assert "Efforts/x.md" in ctx


import shutil


def _run_hook_at(hook_path, cwd):
    r = subprocess.run(["bash", str(hook_path)], cwd=str(cwd),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]


def test_hook_marker_file_overrides_default(tmp_path):
    hook_dir = tmp_path / "hooks"
    hook_dir.mkdir()
    hook = hook_dir / "session-start.sh"
    shutil.copy(_HOOK, hook)
    (hook_dir / "marker").write_text("brain-work\n")
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "CLAUDE.md").write_text(
        "<!-- brain-work -->\neffort: Efforts/x.md\n<!-- /brain-work -->\n")
    assert "Efforts/x.md" in _run_hook_at(hook, proj)


def test_hook_marker_file_makes_plain_marker_inert(tmp_path):
    hook_dir = tmp_path / "hooks"
    hook_dir.mkdir()
    hook = hook_dir / "session-start.sh"
    shutil.copy(_HOOK, hook)
    (hook_dir / "marker").write_text("brain-work\n")
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "CLAUDE.md").write_text(
        "<!-- brain -->\neffort: Efforts/x.md\n<!-- /brain -->\n")
    assert _run_hook_at(hook, proj) == ""


def test_hook_without_marker_file_falls_back_to_brain(tmp_path):
    hook_dir = tmp_path / "hooks"
    hook_dir.mkdir()
    hook = hook_dir / "session-start.sh"
    shutil.copy(_HOOK, hook)          # no marker file beside the copy
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "CLAUDE.md").write_text(
        "<!-- brain -->\neffort: Efforts/x.md\n<!-- /brain -->\n")
    assert "Efforts/x.md" in _run_hook_at(hook, proj)
