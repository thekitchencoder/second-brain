# tests/test_query_backward_compat.py
"""Seam 5 acceptance: ace filters identically to pre-refactor; a custom profile's
promoted fields filter automatically with zero engine changes.

Two proofs:
  1. The bundled `ace` profile's fields (status, type, intensity, effort) filter via
     scalar equality — including status="unset" — exactly like the old fixed-param
     `handle_brain_query` path did.
  2. A brand-new profile that promotes `layer` (scalar) and `known_by` (list,
     visibility) filters those fields correctly purely by being handed as
     `field_specs` — nothing in lib.brain knows those names in advance.
"""
import os
import sys
from unittest.mock import MagicMock

# Stub native-only deps so importing lib.brain doesn't require sqlite_vec/openai
# to be installed (mirrors tests/test_brain_service.py).
if "sqlite_vec" not in sys.modules:
    sys.modules["sqlite_vec"] = MagicMock()
if "openai" not in sys.modules:
    sys.modules["openai"] = MagicMock()

from lib.brain import handle_brain_query
from lib.profile import load_profile

_ACE_PROFILE_DIR = os.path.join(os.path.dirname(__file__), "..", "profiles", "ace")
_ACE_FIELDS = load_profile(_ACE_PROFILE_DIR).fields


def _write_note(dirpath, name, frontmatter):
    fm = "\n".join(f"{k}: {v}" for k, v in frontmatter.items())
    (dirpath / name).write_text(f"---\n{fm}\n---\n# {name}\n")


# ── (1) ace profile fields reproduce pre-refactor filtering ────────────────


def test_ace_status_scalar_equality(tmp_path):
    _write_note(tmp_path, "a.md", {"type": "effort", "status": "active"})
    _write_note(tmp_path, "b.md", {"type": "effort", "status": "done"})
    out = handle_brain_query(str(tmp_path), fields={"status": "active"}, field_specs=_ACE_FIELDS)
    assert "a.md" in out and "b.md" not in out


def test_ace_type_scalar_equality(tmp_path):
    _write_note(tmp_path, "a.md", {"type": "effort"})
    _write_note(tmp_path, "b.md", {"type": "note"})
    out = handle_brain_query(str(tmp_path), fields={"type": "effort"}, field_specs=_ACE_FIELDS)
    assert "a.md" in out and "b.md" not in out


def test_ace_intensity_scalar_equality(tmp_path):
    _write_note(tmp_path, "a.md", {"type": "effort", "intensity": "focus"})
    _write_note(tmp_path, "b.md", {"type": "effort", "intensity": "simmering"})
    out = handle_brain_query(str(tmp_path), fields={"intensity": "focus"}, field_specs=_ACE_FIELDS)
    assert "a.md" in out and "b.md" not in out


def test_ace_effort_scalar_equality(tmp_path):
    _write_note(tmp_path, "a.md", {"type": "note", "effort": "walking-tracker"})
    _write_note(tmp_path, "b.md", {"type": "note", "effort": "homelab"})
    out = handle_brain_query(
        str(tmp_path), fields={"effort": "walking-tracker"}, field_specs=_ACE_FIELDS
    )
    assert "a.md" in out and "b.md" not in out


def test_ace_status_unset(tmp_path):
    _write_note(tmp_path, "a.md", {"type": "note"})  # no status field at all
    _write_note(tmp_path, "b.md", {"type": "note", "status": "active"})
    out = handle_brain_query(str(tmp_path), fields={"status": "unset"}, field_specs=_ACE_FIELDS)
    assert "a.md" in out and "b.md" not in out


def test_ace_combined_filters_match_pre_refactor(tmp_path):
    # The old code filtered type/status/intensity/effort together as independent
    # AND'd scalar-equality checks — reproduce that with a multi-field query.
    _write_note(tmp_path, "a.md", {"type": "effort", "status": "active", "intensity": "focus"})
    _write_note(tmp_path, "b.md", {"type": "effort", "status": "active", "intensity": "simmering"})
    _write_note(tmp_path, "c.md", {"type": "note", "status": "active", "intensity": "focus"})
    out = handle_brain_query(
        str(tmp_path),
        fields={"type": "effort", "status": "active", "intensity": "focus"},
        field_specs=_ACE_FIELDS,
    )
    assert "a.md" in out
    assert "b.md" not in out and "c.md" not in out


# ── (2) a custom profile's promoted fields filter with zero engine changes ─

_CUSTOM_PROFILE_TOML = """\
name = "custom"
folders = ["Notes"]

[plugin]
name = "custom-brain"
author = "test"
marker = "custom"

[fields.layer]
kind = "scalar"
label = "Layer"

[fields.known_by]
kind = "list"
label = "Known by"
visibility = true
"""


def _load_custom_fields(tmp_path):
    """Write and load a real, self-contained profile.toml promoting layer/known_by."""
    profile_dir = tmp_path / "_profile"
    profile_dir.mkdir()
    (profile_dir / "profile.toml").write_text(_CUSTOM_PROFILE_TOML)
    return load_profile(str(profile_dir)).fields


def test_custom_profile_promotes_scalar_field(tmp_path):
    fields = _load_custom_fields(tmp_path)
    _write_note(tmp_path, "a.md", {"layer": "deep-canon"})
    _write_note(tmp_path, "b.md", {"layer": "surface"})
    out = handle_brain_query(str(tmp_path), fields={"layer": "deep-canon"}, field_specs=fields)
    assert "a.md" in out and "b.md" not in out


def test_custom_profile_promotes_list_field(tmp_path):
    fields = _load_custom_fields(tmp_path)
    _write_note(tmp_path, "c.md", {"known_by": "[fenn, alba]"})
    _write_note(tmp_path, "d.md", {"known_by": "[alba]"})
    out = handle_brain_query(str(tmp_path), fields={"known_by": "fenn"}, field_specs=fields)
    assert "c.md" in out and "d.md" not in out


def test_custom_profile_combined_scalar_and_list(tmp_path):
    fields = _load_custom_fields(tmp_path)
    _write_note(tmp_path, "e.md", {"layer": "deep-canon", "known_by": "[fenn, alba]"})
    _write_note(tmp_path, "f.md", {"layer": "deep-canon", "known_by": "[alba]"})
    _write_note(tmp_path, "g.md", {"layer": "surface", "known_by": "[fenn]"})
    out = handle_brain_query(
        str(tmp_path),
        fields={"layer": "deep-canon", "known_by": "fenn"},
        field_specs=fields,
    )
    assert "e.md" in out
    assert "f.md" not in out and "g.md" not in out
