# tests/test_ace_backward_compat.py
"""Acceptance gate: the ace profile reproduces pre-refactor behaviour.

The ONE intended deviation from git history is brain-distil, which the old
_GLOBAL_SKILL_NAMES dropped (10 of 11 skills). See the spec's backward-compat note.
"""
import os
from lib.profile import load_profile, compose_zk_config

_ACE = os.path.join(os.path.dirname(__file__), "..", "profiles", "ace")

# Values hardcoded in the pre-refactor codebase.
_OLD_ACE_FOLDERS = ["Atlas", "Efforts", "Cards", "Calendar", "Sources"]
_OLD_VAULT_SKILLS = {"brain-daily", "brain-extract", "brain-hygiene",
                     "brain-rename", "brain-reorganise"}
_OLD_GLOBAL_SKILLS = {"brain-capture", "brain-connect", "brain-context",
                      "brain-create-effort", "brain-effort", "brain-project",
                      "brain-save", "brain-setup", "brain-surface", "brain-triage"}
_OLD_QUERY_FIELDS = {"status", "type", "intensity", "effort"}
_ZK_INFRA = {
    "notebook": {"exclude": ["templates/"]},
    "note": {"extension": "md", "id-charset": "alphanum", "id-length": 0},
    "tool": {"pager": "cat",
             "fzf-preview": "bat --color=always --style=plain --theme=TwoDark /brain/{}"},
}


def test_folders_unchanged():
    assert load_profile(_ACE).folders == _OLD_ACE_FOLDERS


def test_query_fields_unchanged():
    assert {f.name for f in load_profile(_ACE).fields} == _OLD_QUERY_FIELDS


def test_vault_skills_unchanged():
    assert set(load_profile(_ACE).vault_skills) == _OLD_VAULT_SKILLS


def test_global_skills_are_old_set_plus_brain_distil():
    got = set(load_profile(_ACE).global_skills)
    assert got == _OLD_GLOBAL_SKILLS | {"brain-distil"}


def test_zk_config_matches_old_values():
    p = load_profile(_ACE)
    cfg = compose_zk_config(_ZK_INFRA, p.zk)
    assert cfg["note"]["filename"] == "{{slug title}}"
    assert cfg["note"]["extension"] == "md"
    assert cfg["note"]["id-charset"] == "alphanum"
    assert cfg["extra"]["author"] == "Chris"
    assert cfg["filter"]["recents"] == "--sort created- --created-after '2 weeks ago'"
    assert cfg["tool"]["fzf-preview"] == \
        "bat --color=always --style=plain --theme=TwoDark /brain/{}"
    assert "templates/" in cfg["notebook"]["exclude"]


def test_plugin_identity_unchanged():
    # name/author from the old stage_brain_plugin() manifest; marker "brain"
    # from the old hooks/session-start.sh <!-- brain --> block.
    plugin = load_profile(_ACE).plugin
    assert (plugin.name, plugin.author, plugin.marker) == \
        ("second-brain", "kitchencoder", "brain")


def test_mcp_server_name_unchanged():
    assert load_profile(_ACE).plugin.mcp_server == "brain"


def test_ace_profile_is_auth_none():
    # Proves the gate is inert for the bundled ace profile: mode=none, no rbac.
    prof = load_profile(_ACE)
    assert prof.auth.mode == "none"
    assert prof.auth.rbac is None
