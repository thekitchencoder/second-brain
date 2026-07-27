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
