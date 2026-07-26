"""Behaviour test for setup.sh's profile-sourced skill seeding.

Executes setup.sh (not dot-sourced) with SETUP_SEED_SKILLS_ONLY=1 against a
fake HOME + fake brain, asserting ~/.claude/skills is populated from the
profile. Must run under `sh` (not just bash) since the container's /bin/sh
is dash, which does not propagate positional args to a dot-sourced file —
hence the env-var gate instead of a CLI flag.
"""
import os
import subprocess


def _setup_sh_path():
    here = os.path.dirname(__file__)
    for cand in (
        os.path.join(here, "..", "tools", "setup.sh"),  # host checkout
        os.path.join(here, "..", "setup.sh"),            # container (flattened layout)
    ):
        if os.path.isfile(cand):
            return os.path.abspath(cand)
    raise FileNotFoundError("setup.sh not found in either layout")


def test_setup_seeds_skills_from_profile(tmp_path):
    # Fake brain with a resolved profile containing two global + one vault skill.
    brain = tmp_path / "brain"
    for tier, names in (("global", ["brain-capture", "brain-save"]), ("vault", ["brain-daily"])):
        for n in names:
            d = brain / ".brain" / "skills" / tier / n
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text("# skill\n")
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    seed = tmp_path / "seed"

    env = dict(
        os.environ,
        HOME=str(home),
        BRAIN_DIR=str(brain),
        SEED_DIR=str(seed),
        CLAUDE_DIR=str(home / ".claude"),
        SETUP_SEED_SKILLS_ONLY="1",
    )
    r = subprocess.run(["sh", _setup_sh_path()], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    seeded = os.listdir(home / ".claude" / "skills")
    assert set(seeded) == {"brain-capture", "brain-save", "brain-daily"}


def test_mcp_http_launch_inherits_auth_env():
    """The background MCP-HTTP process must not scrub the environment.

    BRAIN_AUTH_* is sourced from <brain>/.env by the entrypoint before
    setup.sh runs; the MCP-HTTP background launch must inherit it rather
    than being started under a scrubbed environment (e.g. `env -i`), or
    oauth mode would break for the MCP transport.
    """
    setup = _setup_sh_path()
    with open(setup) as f:
        contents = f.read()
    assert "BRAIN_MCP_TRANSPORT=http brain-mcp-server" in contents
    assert "env -i" not in contents
