"""End-to-end distribution behaviours, composed against local fixture repos."""
import os
import subprocess
import sys
import tomllib

_HERE = os.path.dirname(__file__)


def _resolve(name):
    for cand in (os.path.join(_HERE, "..", "tools", name),  # local dev
                 os.path.join(_HERE, "..", name)):          # container (flattened)
        if os.path.isfile(cand):
            return os.path.abspath(cand)
    raise FileNotFoundError(name)


_BRAIN_INIT = _resolve("brain-init")
_BRAIN_PROFILE = _resolve("brain-profile")

from tests.test_brain_init_profile import _make_local_profile_repo, _FIXTURE_ACE  # noqa: E402


def _auto(brain, *extra, env_extra=None):
    env = dict(os.environ, BRAIN_PATH=str(brain), **(env_extra or {}))
    return subprocess.run([sys.executable, _BRAIN_INIT, "--auto", *extra, str(brain)],
                          capture_output=True, text=True, env=env)


def test_default_is_offline_fixture_seeded_ace(tmp_path):
    brain = tmp_path / "b"; brain.mkdir()
    # Seed from the frozen fixture so this stays offline; assert the ace
    # identity + a folder. (The true network default — no source at all —
    # is covered by test_brain_init_profile.py's dedicated dead-proxy tests.)
    assert _auto(brain, env_extra={"BRAIN_PROFILE_REPO": _FIXTURE_ACE}).returncode == 0
    assert tomllib.loads((brain / ".brain" / "profile.toml").read_text())["name"] == "ace"
    assert (brain / "Atlas").is_dir()


def test_custom_clone_then_update_cycle(tmp_path):
    repo = _make_local_profile_repo(tmp_path)
    brain = tmp_path / "b2"; brain.mkdir()
    assert _auto(brain, "--profile-repo", str(repo)).returncode == 0
    assert (brain / "Zone").is_dir()  # custom folder from the fixture profile
    # upstream advances; update pulls
    (repo / "templates" / "extra.md").write_text("# x\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "-m", "x"], cwd=repo, check=True)
    up = subprocess.run([sys.executable, _BRAIN_PROFILE, "update", str(brain)],
                        capture_output=True, text=True, env=dict(os.environ, BRAIN_PATH=str(brain)))
    assert up.returncode == 0
    assert (brain / ".brain" / "templates" / "extra.md").is_file()


def test_second_init_does_not_reclone(tmp_path):
    repo = _make_local_profile_repo(tmp_path)
    brain = tmp_path / "b3"; brain.mkdir()
    _auto(brain, "--profile-repo", str(repo))
    # a second --auto with NO --profile-repo must keep the cloned custom profile
    assert _auto(brain).returncode == 0
    assert tomllib.loads((brain / ".brain" / "profile.toml").read_text())["name"] == "custom"
