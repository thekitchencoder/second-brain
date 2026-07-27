import textwrap
import pytest
from lib.profile import load_profile, validate_profile, Profile, Field, Plugin, Auth, ProfileError, compose_zk_config, emit_toml, check_collisions


def _write_profile(dir_path, toml_text):
    (dir_path / "profile.toml").write_text(textwrap.dedent(toml_text))
    return str(dir_path)


ACE_TOML = """
    name = "ace"
    folders = ["Atlas", "Efforts", "Cards", "Calendar", "Sources"]

    [plugin]
    name = "second-brain"
    author = "kitchencoder"
    marker = "brain"

    [fields.status]
    kind = "scalar"
    label = "Note status"

    [fields.intensity]
    kind = "scalar"
    label = "Effort intensity"
    query_desc = "Filter by intensity: focus, ongoing, simmering"

    [skills]
    global = ["brain-capture", "brain-save"]
    vault = ["brain-daily", "brain-hygiene"]

    [zk]
    filename = "{{slug title}}"
    default_template = "default.md"
    author = "Chris"

    [auth]
    mode = "none"
"""


def test_load_profile_parses_core_fields(tmp_path):
    p = load_profile(_write_profile(tmp_path, ACE_TOML))
    assert isinstance(p, Profile)
    assert p.name == "ace"
    assert p.folders == ["Atlas", "Efforts", "Cards", "Calendar", "Sources"]
    assert p.plugin == Plugin(name="second-brain", author="kitchencoder", marker="brain",
                               mcp_server="second-brain")
    assert p.global_skills == ["brain-capture", "brain-save"]
    assert p.vault_skills == ["brain-daily", "brain-hygiene"]
    assert p.auth == Auth(mode="none")
    assert p.zk["default_template"] == "default.md"
    assert p.origin is None


def test_load_profile_parses_fields_with_query_desc(tmp_path):
    p = load_profile(_write_profile(tmp_path, ACE_TOML))
    by_name = {f.name: f for f in p.fields}
    assert by_name["status"] == Field(name="status", kind="scalar", label="Note status")
    assert by_name["intensity"].query_desc == "Filter by intensity: focus, ongoing, simmering"
    assert by_name["intensity"].visibility == ""


def test_load_profile_mcp_server_explicit(tmp_path):
    toml = ACE_TOML.replace('marker = "brain"', 'marker = "brain"\n    mcp_server = "brain"')
    p = load_profile(_write_profile(tmp_path, toml))
    assert p.plugin.mcp_server == "brain"


def test_load_profile_mcp_server_defaults_to_plugin_name(tmp_path):
    p = load_profile(_write_profile(tmp_path, ACE_TOML))  # ACE_TOML has no mcp_server
    assert p.plugin.mcp_server == p.plugin.name


def test_load_profile_missing_file_raises(tmp_path):
    with pytest.raises(ProfileError, match="profile.toml not found"):
        load_profile(str(tmp_path))


def test_load_profile_missing_required_key_raises(tmp_path):
    d = _write_profile(tmp_path, 'name = "x"\n')
    with pytest.raises(ProfileError, match="missing required"):
        load_profile(d)


def test_schema_missing_defaults_to_one(tmp_path):
    # ACE_TOML has no schema key — pre-schema profiles keep loading.
    p = load_profile(_write_profile(tmp_path, ACE_TOML))
    assert p.name == "ace"


def test_schema_current_is_accepted(tmp_path):
    p = load_profile(_write_profile(tmp_path, "schema = 1\n" + ACE_TOML))
    assert p.name == "ace"


def test_schema_newer_than_engine_fails_loud(tmp_path):
    with pytest.raises(ProfileError, match="schema 2.*update the second-brain image"):
        load_profile(_write_profile(tmp_path, "schema = 2\n" + ACE_TOML))


def test_schema_non_integer_raises(tmp_path):
    with pytest.raises(ProfileError, match="schema must be an integer"):
        load_profile(_write_profile(tmp_path, 'schema = "1"\n' + ACE_TOML))


def _build_profile_tree(tmp_path, toml_text, templates=(), global_skills=(), vault_skills=()):
    _write_profile(tmp_path, toml_text)
    for t in templates:
        (tmp_path / "templates").mkdir(exist_ok=True)
        (tmp_path / "templates" / t).write_text("# template\n")
    for s in global_skills:
        d = tmp_path / "skills" / "global" / s
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text("# skill\n")
    for s in vault_skills:
        d = tmp_path / "skills" / "vault" / s
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text("# skill\n")
    return str(tmp_path)


def test_validate_profile_ok(tmp_path):
    d = _build_profile_tree(
        tmp_path, ACE_TOML,
        templates=["default.md"],
        global_skills=["brain-capture", "brain-save"],
        vault_skills=["brain-daily", "brain-hygiene"],
    )
    assert validate_profile(load_profile(d), d) == []


def test_validate_profile_missing_default_template(tmp_path):
    d = _build_profile_tree(
        tmp_path, ACE_TOML,
        templates=[],  # no default.md
        global_skills=["brain-capture", "brain-save"],
        vault_skills=["brain-daily", "brain-hygiene"],
    )
    errors = validate_profile(load_profile(d), d)
    assert any("default_template" in e and "default.md" in e for e in errors)


def test_validate_profile_missing_skill(tmp_path):
    d = _build_profile_tree(
        tmp_path, ACE_TOML,
        templates=["default.md"],
        global_skills=["brain-capture"],  # brain-save missing on disk
        vault_skills=["brain-daily", "brain-hygiene"],
    )
    errors = validate_profile(load_profile(d), d)
    assert any("brain-save" in e for e in errors)


RESERVED_FIELD_TOML = ACE_TOML + """
    [fields.tag]
    kind = "scalar"
    label = "Reserved collision"
"""


def test_validate_profile_rejects_reserved_field_name(tmp_path):
    """A profile field named 'tag' would shadow the stable 'tag' query param in the
    generated MCP/REST schema — must be rejected."""
    d = _build_profile_tree(
        tmp_path, RESERVED_FIELD_TOML,
        templates=["default.md"],
        global_skills=["brain-capture", "brain-save"],
        vault_skills=["brain-daily", "brain-hygiene"],
    )
    errors = validate_profile(load_profile(d), d)
    assert any("tag" in e and "reserved" in e.lower() for e in errors)


INFRA_ZK = {
    "notebook": {"exclude": ["templates/"]},
    "note": {"extension": "md", "id-charset": "alphanum", "id-length": 0,
             "filename": "OVERRIDE_ME", "template": "OVERRIDE_ME"},
    "tool": {"pager": "cat", "fzf-preview": "bat /brain/{}"},
}


def test_compose_maps_profile_conventions_onto_tables():
    profile_zk = {"filename": "{{slug title}}", "default_template": "default.md",
                  "author": "Chris", "recents_filter": "--sort created-"}
    result = compose_zk_config(INFRA_ZK, profile_zk)
    assert result["note"]["filename"] == "{{slug title}}"
    assert result["note"]["template"] == "default.md"
    assert result["extra"]["author"] == "Chris"
    assert result["filter"]["recents"] == "--sort created-"
    # infra note defaults survive
    assert result["note"]["extension"] == "md"


def test_compose_templates_exclusion_is_guaranteed_even_if_profile_drops_it():
    # A profile that maliciously/accidentally overrides notebook.exclude
    profile_zk = {"notebook": {"exclude": ["nothing/"]}}
    result = compose_zk_config(INFRA_ZK, profile_zk)
    assert "templates/" in result["notebook"]["exclude"]


def test_compose_profile_wins_on_tool_override():
    profile_zk = {"tool": {"pager": "less"}}
    result = compose_zk_config(INFRA_ZK, profile_zk)
    assert result["tool"]["pager"] == "less"
    assert result["tool"]["fzf-preview"] == "bat /brain/{}"  # untouched infra key survives


def test_emit_toml_roundtrips_zk_shape():
    import tomllib
    data = {"note": {"filename": "x", "id-length": 0},
            "tool": {"pager": "cat"},
            "notebook": {"exclude": ["templates/"]}}
    text = emit_toml(data)
    assert tomllib.loads(text) == data


def _profile(name, plugin_name, marker):
    return Profile(name=name, folders=["X"], fields=[], global_skills=[],
                   vault_skills=[], plugin=Plugin(plugin_name, "a", marker, plugin_name),
                   zk={}, auth=Auth("none"), origin=None)


def test_check_collisions_none():
    a = _profile("ace", "second-brain", "brain")
    b = _profile("fiction", "fiction", "fiction")
    assert check_collisions(a, [b]) == []


def test_check_collisions_plugin_name():
    a = _profile("ace", "second-brain", "brain")
    dup = _profile("other", "second-brain", "other")
    errors = check_collisions(a, [dup])
    assert any("plugin name 'second-brain'" in e for e in errors)


def test_check_collisions_marker():
    a = _profile("ace", "second-brain", "brain")
    dup = _profile("other", "other-plugin", "brain")
    errors = check_collisions(a, [dup])
    assert any("marker 'brain'" in e for e in errors)


def test_check_collisions_mcp_server():
    # Two profiles whose mcp_server names clash (but plugin name/marker differ).
    a = Profile(name="ace", folders=["X"], fields=[], global_skills=[], vault_skills=[],
                plugin=Plugin("second-brain", "a", "brain", "brain"), zk={}, auth=Auth("none"), origin=None)
    dup = Profile(name="other", folders=["X"], fields=[], global_skills=[], vault_skills=[],
                  plugin=Plugin("other-plugin", "a", "other", "brain"), zk={}, auth=Auth("none"), origin=None)
    errors = check_collisions(a, [dup])
    assert any("mcp server 'brain'" in e.lower() for e in errors)
