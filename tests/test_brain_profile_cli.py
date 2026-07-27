import os
import subprocess
import sys

_HERE = os.path.dirname(__file__)


def _resolve(name):
    candidates = [
        os.path.join(_HERE, "..", "tools", name),  # local dev repo layout
        os.path.join(_HERE, "..", name),           # container: tools/ flattened into brain-tools/
    ]
    return next(p for p in candidates if os.path.isfile(p))


_BRAIN_INIT = _resolve("brain-init")
_BRAIN_PROFILE = _resolve("brain-profile")


def _init_from(source, brain, env_extra=None):
    env = dict(os.environ, BRAIN_PATH=str(brain), **(env_extra or {}))
    r = subprocess.run([sys.executable, _BRAIN_INIT, "--auto", "--profile-repo", str(source), str(brain)],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr


def _make_local_profile_repo(tmp_path):
    from tests.test_brain_init_profile import _make_local_profile_repo as mk  # reuse
    return mk(tmp_path)


def test_update_pulls_a_cloned_profile(tmp_path):
    repo = _make_local_profile_repo(tmp_path)
    brain = tmp_path / "brain"; brain.mkdir()
    _init_from(repo, brain)
    # advance the upstream repo by one commit
    (repo / "templates" / "new.md").write_text("# new\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "-m", "add template"], cwd=repo, check=True)
    r = subprocess.run([sys.executable, _BRAIN_PROFILE, "update", str(brain)],
                       capture_output=True, text=True, env=dict(os.environ, BRAIN_PATH=str(brain)))
    assert r.returncode == 0, r.stderr
    assert (brain / ".brain" / "templates" / "new.md").is_file()


def test_update_on_plain_dir_profile_is_graceful(tmp_path):
    # A profile seeded from a plain (non-git) local directory is copied, not
    # cloned; `brain-profile update` must say so, not attempt a git pull.
    # (Previously this exercised the no-BRAIN_PROFILE_REPO default, which
    # used to fall back to a bundled copy; the default is now always a
    # remote clone, so the plain-copy path is exercised explicitly here.)
    src = tmp_path / "plain-profile"
    (src / "templates").mkdir(parents=True)
    (src / "templates" / "default.md").write_text("# d\n")
    (src / "profile.toml").write_text(
        'name = "plain"\nfolders = ["Z"]\n[plugin]\nname="p"\nauthor="a"\nmarker="p"\n'
        '[skills]\nglobal=[]\nvault=[]\n[zk]\ndefault_template="default.md"\n[auth]\nmode="none"\n')
    brain = tmp_path / "brain2"; brain.mkdir()
    subprocess.run([sys.executable, _BRAIN_INIT, "--auto", str(brain)],
                   capture_output=True, text=True,
                   env=dict(os.environ, BRAIN_PATH=str(brain), BRAIN_PROFILE_REPO=str(src)),
                   check=True)
    r = subprocess.run([sys.executable, _BRAIN_PROFILE, "update", str(brain)],
                       capture_output=True, text=True, env=dict(os.environ, BRAIN_PATH=str(brain)))
    assert r.returncode == 0, r.stderr
    assert "not a git clone" in (r.stdout + r.stderr).lower()
