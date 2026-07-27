import os
from lib.profile import load_profile, validate_profile

_ACE_DIR = os.path.join(os.path.dirname(__file__), "..", "fixtures", "profile-ace")


def test_ace_profile_loads_and_validates():
    p = load_profile(_ACE_DIR)
    assert validate_profile(p, _ACE_DIR) == []


def test_ace_profile_ships_all_11_global_skills():
    # brain-distil included — the intended fix for today's 10-skill drop.
    p = load_profile(_ACE_DIR)
    assert "brain-distil" in p.global_skills
    assert len(p.global_skills) == 11
    assert len(p.vault_skills) == 5
