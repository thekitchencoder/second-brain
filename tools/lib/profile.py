"""Profile loading — the single source of truth for brain-specific behaviour.

A profile is a directory (default <brain>/.brain/) containing profile.toml plus
templates/, skills/, and convention fragments. The engine reads the directory;
it never shells out to git (that is the distribution layer's job).
"""
import os
import tomllib
from dataclasses import dataclass


class ProfileError(Exception):
    """Raised when a profile manifest is missing or malformed."""


# Query params that are stable across every profile (tag, where, and the date-range
# filters). A profile field sharing one of these names would shadow the built-in
# parameter in the generated MCP/REST schema.
_RESERVED_FIELD_NAMES = {"tag", "where", "created_after", "created_before"}


@dataclass(frozen=True)
class Field:
    name: str
    kind: str                       # "scalar" | "list"
    label: str
    query_desc: str | None = None
    visibility: bool = False


@dataclass(frozen=True)
class Plugin:
    name: str
    author: str
    marker: str
    mcp_server: str = ""


@dataclass(frozen=True)
class Auth:
    mode: str                       # "none" | "oauth"


@dataclass(frozen=True)
class Profile:
    name: str
    folders: list[str]
    fields: list[Field]
    global_skills: list[str]
    vault_skills: list[str]
    plugin: Plugin
    zk: dict
    auth: Auth
    origin: dict | None


def load_profile(profile_dir: str) -> Profile:
    manifest_path = os.path.join(profile_dir, "profile.toml")
    if not os.path.isfile(manifest_path):
        raise ProfileError(f"profile.toml not found in {profile_dir}")
    with open(manifest_path, "rb") as f:
        data = tomllib.load(f)

    def require(key):
        if key not in data:
            raise ProfileError(f"profile.toml missing required key: {key}")
        return data[key]

    plugin_raw = require("plugin")
    for k in ("name", "author", "marker"):
        if k not in plugin_raw:
            raise ProfileError(f"profile.toml missing required key: plugin.{k}")

    fields = []
    for name, spec in data.get("fields", {}).items():
        fields.append(Field(
            name=name,
            kind=spec.get("kind", "scalar"),
            label=spec.get("label", name),
            query_desc=spec.get("query_desc"),
            visibility=bool(spec.get("visibility", False)),
        ))

    skills = data.get("skills", {})
    auth_raw = data.get("auth", {})

    return Profile(
        name=require("name"),
        folders=require("folders"),
        fields=fields,
        global_skills=skills.get("global", []),
        vault_skills=skills.get("vault", []),
        plugin=Plugin(
            name=plugin_raw["name"],
            author=plugin_raw["author"],
            marker=plugin_raw["marker"],
            mcp_server=plugin_raw.get("mcp_server") or plugin_raw["name"],
        ),
        zk=data.get("zk", {}),
        auth=Auth(mode=auth_raw.get("mode", "none")),
        origin=data.get("origin"),
    )


def validate_profile(profile: Profile, profile_dir: str) -> list[str]:
    errors = []

    if not profile.folders:
        errors.append("profile.folders is empty — at least one folder required")

    for f in profile.fields:
        if f.name in _RESERVED_FIELD_NAMES:
            errors.append(
                f"field '{f.name}' collides with a reserved query parameter "
                f"({', '.join(sorted(_RESERVED_FIELD_NAMES))})")

    default_template = profile.zk.get("default_template")
    if default_template:
        tpath = os.path.join(profile_dir, "templates", default_template)
        if not os.path.isfile(tpath):
            errors.append(
                f"zk.default_template names '{default_template}' but "
                f"templates/{default_template} does not exist"
            )

    for skill in profile.global_skills:
        if not os.path.isdir(os.path.join(profile_dir, "skills", "global", skill)):
            errors.append(f"global skill '{skill}' not found under skills/global/")
    for skill in profile.vault_skills:
        if not os.path.isdir(os.path.join(profile_dir, "skills", "vault", skill)):
            errors.append(f"vault skill '{skill}' not found under skills/vault/")

    return errors


# Maps flat profile convention keys → (table, key) in zk config.
_ZK_CONVENTION_MAP = {
    "filename": ("note", "filename"),
    "default_template": ("note", "template"),
    "author": ("extra", "author"),
    "recents_filter": ("filter", "recents"),
}


def _deep_merge(base: dict, over: dict) -> dict:
    result = {k: (dict(v) if isinstance(v, dict) else v) for k, v in base.items()}
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def compose_zk_config(infra: dict, profile_zk: dict) -> dict:
    # Split flat convention keys from any explicit table overrides.
    conventions = {}
    table_overrides = {}
    for key, value in profile_zk.items():
        if key in _ZK_CONVENTION_MAP:
            table, tkey = _ZK_CONVENTION_MAP[key]
            conventions.setdefault(table, {})[tkey] = value
        else:
            table_overrides[key] = value  # e.g. an explicit [tool]/[note] table

    merged = _deep_merge(infra, conventions)
    merged = _deep_merge(merged, table_overrides)

    # Structural guarantee: templates/ must always be excluded so zk never
    # indexes template files as real notes.
    notebook = merged.setdefault("notebook", {})
    exclude = list(notebook.get("exclude", []))
    if "templates/" not in exclude:
        exclude.append("templates/")
    notebook["exclude"] = exclude
    return merged


def emit_toml(data: dict) -> str:
    """Serialise a one-level-nested dict to TOML. zk-config shape only."""
    def fmt(v):
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return str(v)
        if isinstance(v, str):
            return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
        if isinstance(v, list):
            return "[" + ", ".join(fmt(x) for x in v) + "]"
        raise ValueError(f"emit_toml cannot serialise value: {v!r}")

    top_scalars = {k: v for k, v in data.items() if not isinstance(v, dict)}
    tables = {k: v for k, v in data.items() if isinstance(v, dict)}

    lines = []
    for k, v in top_scalars.items():
        lines.append(f"{k} = {fmt(v)}")
    for table, kv in tables.items():
        if any(isinstance(x, dict) for x in kv.values()):
            raise ValueError(f"emit_toml supports one level of nesting; [{table}] has a sub-table")
        if lines:
            lines.append("")
        lines.append(f"[{table}]")
        for k, v in kv.items():
            lines.append(f"{k} = {fmt(v)}")
    return "\n".join(lines) + "\n"


def check_collisions(profile: Profile, installed: list) -> list:
    errors = []
    for other in installed:
        if other.name == profile.name:
            continue
        if other.plugin.name == profile.plugin.name:
            errors.append(
                f"plugin name '{profile.plugin.name}' already claimed by profile "
                f"'{other.name}'"
            )
        if other.plugin.marker == profile.plugin.marker:
            errors.append(
                f"CLAUDE.md marker '{profile.plugin.marker}' already claimed by "
                f"profile '{other.name}'"
            )
        if other.plugin.mcp_server == profile.plugin.mcp_server:
            errors.append(
                f"MCP server '{profile.plugin.mcp_server}' already claimed by "
                f"profile '{other.name}'"
            )
    return errors
