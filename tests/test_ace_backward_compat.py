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


# ── Task 8: RBAC backward-compat proof. ─────────────────────────────────────
#
# Plan E (Seam 7) threads a `principal` through every content handler and
# gates every read/write on visible()/can_write(). The ace profile declares no
# visibility-mode fields and no [auth.rbac] block, and mode="none" makes
# resolve_principal() always return OWNER (read_layers=write_layers=("*",)).
# These tests prove that combination is a true no-op: visible() returns True
# for any note shape under any role, and the real handlers behave exactly as
# they did before Plan E when called the way pre-refactor callers always did
# (no principal passed — the handler default IS OWNER).


def test_visible_true_for_every_note_shape_under_ace_defaults():
    """No ace field declares visibility="allow"/"deny", so visible() can only
    ever be tripped by the coarse layer wall — and OWNER's read_layers=("*",)
    short-circuits that too. True for every plausible frontmatter shape,
    including a stray 'layer' key an ace note was never meant to carry."""
    from lib.visibility import visible
    from lib.auth import OWNER, Principal

    fields = load_profile(_ACE).fields
    note_shapes = [
        {},                                             # no frontmatter at all
        {"type": "effort", "status": "active"},
        {"type": "note", "tags": ["x", "y"], "intensity": "focus"},
        {"layer": "anything"},                          # ace never declares 'layer'
        {"known_by": ["someone"]},                       # ace never declares 'known_by'
    ]
    for meta in note_shapes:
        assert visible(meta, OWNER, fields) is True

    # Even a hypothetical restricted-role principal can't arise under ace's
    # mode="none" (resolve_principal always returns OWNER) — but confirm the
    # predicate itself stays permissive for ANY unrestricted principal, since
    # it is role-driven, not identity-driven.
    unrestricted = Principal(id="x", role="anyone", read_layers=("*",),
                             write_layers=("*",), kind="static")
    for meta in note_shapes:
        assert visible(meta, unrestricted, fields) is True


def test_resolve_principal_is_always_owner_under_ace_mode_none():
    """mode="none" short-circuits resolve_principal() before any token is even
    inspected — no bearer token, a garbage token, anything, always OWNER."""
    from lib.auth import resolve_principal, OWNER
    from lib.policy import ProfilePolicyProvider

    provider = ProfilePolicyProvider(_ACE)
    assert resolve_principal(None, provider, settings=None) == OWNER
    assert resolve_principal("garbage-token", provider, settings=None) == OWNER
    assert resolve_principal("", provider, settings=None) == OWNER


def test_read_query_unchanged_when_no_principal_is_passed(tmp_path):
    """End-to-end: the ace-shaped handlers behave exactly as pre-Plan-E when
    invoked the way every caller invoked them before Plan E existed — with no
    `principal` keyword at all. The handler default (principal=OWNER) is what
    makes this byte-for-byte backward compatible; it's not something callers
    have to opt into."""
    import sys
    from unittest.mock import MagicMock
    if "sqlite_vec" not in sys.modules:
        sys.modules["sqlite_vec"] = MagicMock()
    if "openai" not in sys.modules:
        sys.modules["openai"] = MagicMock()
    from lib.brain import handle_brain_read, handle_brain_query, handle_brain_write

    brain = tmp_path / "brain"
    (brain / "Efforts").mkdir(parents=True)
    (brain / "Efforts" / "note.md").write_text(
        "---\ntype: effort\nstatus: active\n---\nbody text")
    fields = load_profile(_ACE).fields

    # No `principal=` kwarg anywhere below.
    assert "body text" in handle_brain_read("Efforts/note.md", str(brain), fields=fields)
    out = handle_brain_query(str(brain), fields={"status": "active"}, field_specs=fields)
    assert "note.md" in out
    assert handle_brain_write(
        "Efforts/new.md", "---\ntype: note\n---\nhello", str(brain), fields=fields
    ).startswith("Written")
