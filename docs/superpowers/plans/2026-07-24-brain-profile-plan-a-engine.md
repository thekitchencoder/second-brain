# Brain Profile — Plan A: Profile-driven engine

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the second-brain engine read all brain-specific behaviour (folders, templates, skills, plugin identity, zk conventions, query fields, auth mode) from a profile directory at `<brain>/.brain/`, and prove the bundled `ace` profile reproduces today's behaviour.

**Architecture:** A new `tools/lib/profile.py` module parses `<brain>/.brain/profile.toml` into a frozen `Profile` object; `Config` exposes it as the single source of truth. `brain-init` reads folders/templates/skills/identity from the profile instead of module-level constants. zk config is composed by deep-merging the profile's convention keys over the engine's infrastructure keys. The `ace` profile is assembled in-repo at `profiles/ace/` as a local profile directory (the local-path source mode Plan B later moves to its own git repo). A backward-compat test asserts `ace` reproduces the current hardcoded values.

**Tech Stack:** Python 3.11 (stdlib `tomllib` for reading TOML — no new dependency), pytest, existing `brain-init` script and `tools/lib/` package.

## Global Constraints

- **Python floor:** `>=3.11` (spec + `pyproject.toml:4`). `tomllib` is stdlib — do NOT add `tomli`/`toml` as a dependency.
- **No new runtime dependency** for manifest reading. The zk-config writer is a small in-repo emitter, not `tomli-w`.
- **Backward compatibility is the acceptance gate:** the `ace` profile loaded must reproduce today's behaviour byte-for-byte, with exactly ONE intended correction — `brain-distil` is added to the global skill set (today's `_GLOBAL_SKILL_NAMES` lists 10; `skills/` has 11). Call this correction out in the test; do not silently preserve the drop.
- **Profile dir location:** `<brain>/.brain/` — i.e. `os.path.join(brain_path, ".brain")`.
- **Tests import via `pythonpath = ["tools"]`** (`pyproject.toml:8`) — so `from lib.profile import ...` and the test file lives under `tests/lib/`.
- **Run unit tests with:** `task test` (runs in a container). For fast local iteration on pure-Python profile logic (no sqlite-vec), `python -m pytest tests/lib/test_profile.py -v` works on host.
- **This plan does NOT change distribution/boot** — no git clone, no `setup.sh` edits, no removal of `zk/`, `skills/`, `brain-skills/` from the repo. Those are Plan B. Here the profile source is a local directory.

---

### Task 1: Profile module — parse the manifest

**Files:**
- Create: `tools/lib/profile.py`
- Test: `tests/lib/test_profile.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Field: name: str; kind: str; label: str; query_desc: str | None = None; visibility: bool = False`
  - `@dataclass(frozen=True) class Plugin: name: str; author: str; marker: str`
  - `@dataclass(frozen=True) class Auth: mode: str`
  - `@dataclass(frozen=True) class Profile: name: str; folders: list[str]; fields: list[Field]; global_skills: list[str]; vault_skills: list[str]; plugin: Plugin; zk: dict; auth: Auth; origin: dict | None`
  - `load_profile(profile_dir: str) -> Profile` — reads `<profile_dir>/profile.toml`, raises `ProfileError` (subclass of `Exception`) with a clear message if the file is missing or required keys are absent.

- [ ] **Step 1: Write the failing test**

```python
# tests/lib/test_profile.py
import textwrap
import pytest
from lib.profile import load_profile, Profile, Field, Plugin, Auth, ProfileError


def _write_profile(dir_path, toml_text):
    (dir_path / "profile.toml").write_text(textwrap.dedent(toml_text))
    return str(dir_path)


ACE_TOML = """
    name = "ace"

    [plugin]
    name = "second-brain"
    author = "kitchencoder"
    marker = "brain"

    folders = ["Atlas", "Efforts", "Cards", "Calendar", "Sources"]

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
    assert p.plugin == Plugin(name="second-brain", author="kitchencoder", marker="brain")
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
    assert by_name["intensity"].visibility is False


def test_load_profile_missing_file_raises(tmp_path):
    with pytest.raises(ProfileError, match="profile.toml not found"):
        load_profile(str(tmp_path))


def test_load_profile_missing_required_key_raises(tmp_path):
    d = _write_profile(tmp_path, 'name = "x"\n')
    with pytest.raises(ProfileError, match="missing required"):
        load_profile(d)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/lib/test_profile.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.profile'`

- [ ] **Step 3: Write minimal implementation**

```python
# tools/lib/profile.py
"""Profile loading — the single source of truth for brain-specific behaviour.

A profile is a directory (default <brain>/.brain/) containing profile.toml plus
templates/, skills/, and convention fragments. The engine reads the directory;
it never shells out to git (that is the distribution layer's job).
"""
import os
import tomllib
from dataclasses import dataclass, field as _dc_field


class ProfileError(Exception):
    """Raised when a profile manifest is missing or malformed."""


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


@dataclass(frozen=True)
class Auth:
    mode: str                       # "none" | "oauth"


@dataclass(frozen=True)
class Profile:
    name: str
    folders: list
    fields: list
    global_skills: list
    vault_skills: list
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
        plugin=Plugin(name=plugin_raw["name"], author=plugin_raw["author"],
                      marker=plugin_raw["marker"]),
        zk=data.get("zk", {}),
        auth=Auth(mode=auth_raw.get("mode", "none")),
        origin=data.get("origin"),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/lib/test_profile.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add tools/lib/profile.py tests/lib/test_profile.py
git commit -m "feat: add profile manifest loader"
```

---

### Task 2: Profile validation

**Files:**
- Modify: `tools/lib/profile.py`
- Test: `tests/lib/test_profile.py`

**Interfaces:**
- Produces: `validate_profile(profile: Profile, profile_dir: str) -> list[str]` — returns a list of human-readable error strings; empty list means valid. Checks: `zk["default_template"]` names a file in `<profile_dir>/templates/`; every global skill resolves under `<profile_dir>/skills/global/` and every vault skill under `<profile_dir>/skills/vault/`; `folders` is non-empty.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/lib/test_profile.py
from lib.profile import validate_profile


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/lib/test_profile.py -k validate -v`
Expected: FAIL — `ImportError: cannot import name 'validate_profile'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to tools/lib/profile.py
def validate_profile(profile: Profile, profile_dir: str) -> list:
    errors = []

    if not profile.folders:
        errors.append("profile.folders is empty — at least one folder required")

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/lib/test_profile.py -k validate -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add tools/lib/profile.py tests/lib/test_profile.py
git commit -m "feat: add profile validation"
```

---

### Task 3: zk config composition (deep merge, profile over infra, templates/ guaranteed)

**Files:**
- Modify: `tools/lib/profile.py`
- Test: `tests/lib/test_profile.py`

**Interfaces:**
- Produces:
  - `compose_zk_config(infra: dict, profile_zk: dict) -> dict` — deep-merges `profile_zk` over `infra`; then unions `"templates/"` into `result["notebook"]["exclude"]` unconditionally.
  - `emit_toml(data: dict) -> str` — serialises a one-level-nested dict (top-level scalars/lists, plus sub-tables of scalars/lists) to TOML text. Handles the shape zk config uses; raises `ValueError` on deeper nesting.
- Consumes: nothing from earlier tasks.

Note: `profile_zk` uses flat convention keys (`filename`, `default_template`, `author`, `recents_filter`); `compose_zk_config` maps them onto zk's table structure: `filename`→`[note].filename`, `default_template`→`[note].template`, `author`→`[extra].author`, `recents_filter`→`[filter].recents`. The engine `infra` dict supplies `[note]` defaults (extension, id-charset, id-length), `[tool]`, and `[notebook].exclude`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/lib/test_profile.py
from lib.profile import compose_zk_config, emit_toml

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/lib/test_profile.py -k "compose or emit" -v`
Expected: FAIL — `ImportError: cannot import name 'compose_zk_config'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to tools/lib/profile.py

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/lib/test_profile.py -k "compose or emit" -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add tools/lib/profile.py tests/lib/test_profile.py
git commit -m "feat: compose zk config from profile conventions over infra"
```

---

### Task 4: Collision detection across installed profiles

**Files:**
- Modify: `tools/lib/profile.py`
- Test: `tests/lib/test_profile.py`

**Interfaces:**
- Produces: `check_collisions(profile: Profile, installed: list[Profile]) -> list[str]` — returns error strings if `profile.plugin.name` or `profile.plugin.marker` clashes with any profile in `installed` (compared case-sensitively; a profile never collides with itself by `name`). Used at init when more than one brain is present on a host.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/lib/test_profile.py
from lib.profile import check_collisions


def _profile(name, plugin_name, marker):
    return Profile(name=name, folders=["X"], fields=[], global_skills=[],
                   vault_skills=[], plugin=Plugin(plugin_name, "a", marker),
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/lib/test_profile.py -k collision -v`
Expected: FAIL — `ImportError: cannot import name 'check_collisions'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to tools/lib/profile.py
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
    return errors
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/lib/test_profile.py -k collision -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add tools/lib/profile.py tests/lib/test_profile.py
git commit -m "feat: detect plugin/marker collisions across profiles"
```

---

### Task 5: Config exposes the profile

**Files:**
- Modify: `tools/lib/config.py`
- Test: `tests/lib/test_config_profile.py` (create)

**Interfaces:**
- Consumes: `load_profile` from Task 1.
- Produces:
  - `Config.profile_dir` property → `os.path.join(self.brain_path, ".brain")`.
  - `Config.load_profile()` method → returns a `Profile` (cached on first call), delegating to `lib.profile.load_profile(self.profile_dir)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/lib/test_config_profile.py
import textwrap
from lib.config import Config


def _seed_profile(brain_dir):
    bd = brain_dir / ".brain"
    bd.mkdir()
    (bd / "profile.toml").write_text(textwrap.dedent("""
        name = "ace"
        [plugin]
        name = "second-brain"
        author = "kitchencoder"
        marker = "brain"
        folders = ["Atlas"]
        [skills]
        global = []
        vault = []
        [zk]
        default_template = "default.md"
        [auth]
        mode = "none"
    """))


def test_config_profile_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAIN_PATH", str(tmp_path))
    cfg = Config()
    assert cfg.profile_dir == str(tmp_path / ".brain")


def test_config_load_profile(tmp_path, monkeypatch):
    _seed_profile(tmp_path)
    monkeypatch.setenv("BRAIN_PATH", str(tmp_path))
    cfg = Config()
    p = cfg.load_profile()
    assert p.name == "ace"
    assert p.folders == ["Atlas"]
    # cached — same object on second call
    assert cfg.load_profile() is p
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/lib/test_config_profile.py -v`
Expected: FAIL — `AttributeError: 'Config' object has no attribute 'profile_dir'`

- [ ] **Step 3: Write minimal implementation**

```python
# tools/lib/config.py — add import at top and members to Config
import os

from lib.profile import load_profile as _load_profile


class Config:
    def __init__(self):
        self.embedding_base_url = os.environ.get(
            "EMBEDDING_BASE_URL",
            "http://model-runner.docker.internal/engines/llama.cpp/v1"
        )
        self.embedding_model = os.environ.get("EMBEDDING_MODEL", "mxbai-embed-large")
        self.brain_path = os.environ.get("BRAIN_PATH", "/brain")
        self._profile = None

    @property
    def db_path(self):
        return f"{self.brain_path}/.ai/embeddings.db"

    @property
    def profile_dir(self):
        return os.path.join(self.brain_path, ".brain")

    def load_profile(self):
        if self._profile is None:
            self._profile = _load_profile(self.profile_dir)
        return self._profile

    @property
    def cors_origins(self) -> list:
        raw = os.environ.get("BRAIN_API_CORS_ORIGINS", "")
        if raw:
            return [o.strip() for o in raw.split(",") if o.strip()]
        return ["http://localhost:7779", "http://127.0.0.1:7779"]
```

Note: `config.py` is imported as `lib.config`; the sibling import `from lib.profile import ...` matches the existing package layout (`pythonpath = ["tools"]`, package `lib`).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/lib/test_config_profile.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add tools/lib/config.py tests/lib/test_config_profile.py
git commit -m "feat: expose profile through Config"
```

---

### Task 6: Assemble the `ace` profile from current repo content

**Files:**
- Create: `profiles/ace/profile.toml`
- Create (by copy): `profiles/ace/templates/` ← `zk/templates/`
- Create (by copy): `profiles/ace/skills/global/` ← `skills/` (11 skills), `profiles/ace/skills/vault/` ← `brain-skills/` (5 skills)
- Create (by copy): `profiles/ace/hooks/` ← `hooks/`
- Create (by copy): `profiles/ace/claude/vault-claude.md` ← `claude/vault-claude.md`, `profiles/ace/prompts/setup.md` ← `prompts/setup.md`
- Test: `tests/lib/test_ace_profile.py` (create)

**Interfaces:**
- Consumes: `load_profile`, `validate_profile` (Tasks 1–2).
- Produces: a valid local profile directory at `profiles/ace/` used as the test/dev profile source. (Plan B extracts this to its own repo.)

Note: `profiles/ace/` is a *copy*, not a move — `zk/`, `skills/`, `brain-skills/` stay in place this plan so nothing else breaks. Plan B removes the originals.

- [ ] **Step 1: Copy current content into the profile tree**

```bash
mkdir -p profiles/ace/skills/global profiles/ace/skills/vault profiles/ace/claude profiles/ace/prompts
cp -r zk/templates profiles/ace/templates
cp -r skills/brain-capture skills/brain-connect skills/brain-context skills/brain-create-effort \
      skills/brain-distil skills/brain-effort skills/brain-project skills/brain-save \
      skills/brain-setup skills/brain-surface skills/brain-triage profiles/ace/skills/global/
cp -r brain-skills/brain-daily brain-skills/brain-extract brain-skills/brain-hygiene \
      brain-skills/brain-rename brain-skills/brain-reorganise profiles/ace/skills/vault/
cp -r hooks profiles/ace/hooks
cp claude/vault-claude.md profiles/ace/claude/vault-claude.md
cp prompts/setup.md profiles/ace/prompts/setup.md
```

- [ ] **Step 2: Write the `ace` manifest**

Create `profiles/ace/profile.toml`:

```toml
name = "ace"

[plugin]
name   = "second-brain"
author = "kitchencoder"
marker = "brain"

folders = ["Atlas", "Efforts", "Cards", "Calendar", "Sources"]

[fields.status]
kind  = "scalar"
label = "Note status"

[fields.type]
kind  = "scalar"
label = "Note type"

[fields.intensity]
kind       = "scalar"
label      = "Effort intensity"
query_desc = "Filter by effort intensity (focus, ongoing, simmering)."

[fields.effort]
kind       = "scalar"
label      = "Effort"
query_desc = "Filter by effort field in frontmatter."

[skills]
global = ["brain-capture", "brain-connect", "brain-context", "brain-create-effort",
          "brain-distil", "brain-effort", "brain-project", "brain-save", "brain-setup",
          "brain-surface", "brain-triage"]
vault  = ["brain-daily", "brain-extract", "brain-hygiene", "brain-rename", "brain-reorganise"]

[zk]
filename = "{{slug title}}"
default_template = "default.md"
author = "Chris"
recents_filter = "--sort created- --created-after '2 weeks ago'"

[auth]
mode = "none"
```

- [ ] **Step 3: Write the test that the ace profile loads and validates**

```python
# tests/lib/test_ace_profile.py
import os
from lib.profile import load_profile, validate_profile

_ACE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "profiles", "ace")


def test_ace_profile_loads_and_validates():
    p = load_profile(_ACE_DIR)
    assert validate_profile(p, _ACE_DIR) == []


def test_ace_profile_ships_all_11_global_skills():
    # brain-distil included — the intended fix for today's 10-skill drop.
    p = load_profile(_ACE_DIR)
    assert "brain-distil" in p.global_skills
    assert len(p.global_skills) == 11
    assert len(p.vault_skills) == 5
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/lib/test_ace_profile.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add profiles/ace tests/lib/test_ace_profile.py
git commit -m "feat: assemble ace profile from current repo content"
```

---

### Task 7: brain-init resolves a profile (source path + validation)

**Files:**
- Modify: `tools/brain-init` (source resolution near lines 32–70; add profile resolution)
- Test: `tests/test_brain_init_profile.py` (create)

**Interfaces:**
- Consumes: `load_profile`, `validate_profile`, `check_collisions` (Tasks 1–4), `Config.profile_dir` (Task 5).
- Produces: in `brain-init`, a helper `resolve_profile(brain_path) -> (Profile, profile_dir)`:
  - If `<brain>/.brain/profile.toml` exists, load and validate it; on validation errors, print them and `sys.exit(1)`.
  - If `<brain>/.brain/` is absent, seed it by copying the in-repo `profiles/ace/` (found via source candidates, mirroring `_ZK_SOURCE_CANDIDATES`) into `<brain>/.brain/`, then load. (Plan B replaces this copy-seed with a git clone; the local-copy behaviour is the Plan-A stand-in.)

`brain-init` is a script, not a module. Test it by invoking `run_auto` semantics through a subprocess or by importing the script via `importlib`. Use subprocess for reliability.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_brain_init_profile.py
import os
import subprocess
import sys

_TOOLS = os.path.join(os.path.dirname(__file__), "..", "tools")
_BRAIN_INIT = os.path.join(_TOOLS, "brain-init")


def _run_init(brain_path):
    env = dict(os.environ, BRAIN_PATH=str(brain_path))
    return subprocess.run(
        [sys.executable, _BRAIN_INIT, "--auto", str(brain_path)],
        capture_output=True, text=True, env=env,
    )


def test_init_seeds_brain_dir_from_ace(tmp_path):
    r = _run_init(tmp_path)
    assert r.returncode == 0, r.stderr
    assert os.path.isfile(tmp_path / ".brain" / "profile.toml")
    assert os.path.isdir(tmp_path / ".brain" / "templates")


def test_init_second_run_is_idempotent(tmp_path):
    _run_init(tmp_path)
    r = _run_init(tmp_path)
    assert r.returncode == 0, r.stderr
    assert os.path.isfile(tmp_path / ".brain" / "profile.toml")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_brain_init_profile.py -v`
Expected: FAIL — no `.brain/` seeded (current brain-init doesn't create it)

- [ ] **Step 3: Write minimal implementation**

Add near the top of `tools/brain-init` (after existing source candidates, ~line 55):

```python
sys.path.insert(0, os.path.join(_SCRIPT_DIR, "lib"))
sys.path.insert(0, _SCRIPT_DIR)
from lib.profile import load_profile, validate_profile, check_collisions  # noqa: E402

_PROFILE_SOURCE_CANDIDATES = [
    "/usr/local/lib/brain-tools/profiles/ace",       # inside container
    os.path.join(_REPO_ROOT, "profiles", "ace"),     # local dev
]


def resolve_profile(brain_path):
    """Load <brain>/.brain profile, seeding from the bundled ace profile if absent."""
    profile_dir = os.path.join(brain_path, ".brain")
    if not os.path.isfile(os.path.join(profile_dir, "profile.toml")):
        source = _find_source(_PROFILE_SOURCE_CANDIDATES)
        if source is None:
            print("Error: no profile at <brain>/.brain and no bundled ace profile found.",
                  file=sys.stderr)
            sys.exit(1)
        shutil.copytree(source, profile_dir, dirs_exist_ok=True)
        print(f"  Seeded .brain/ from ace profile")
    profile = load_profile(profile_dir)
    errors = validate_profile(profile, profile_dir)
    if errors:
        print("Error: profile is invalid:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)
    return profile, profile_dir
```

Then call it at the start of `run_auto` and `run_wizard` (store on a module global or pass through). Minimal wiring for this task: call `resolve_profile(brain_path)` as the first line of `run_auto` (line 842) and assign to module-level `_PROFILE`, `_PROFILE_DIR`:

```python
def run_auto(brain_path):
    """Non-interactive init: profile resolve + core setup + vault skills + stage global skills."""
    global _PROFILE, _PROFILE_DIR
    _PROFILE, _PROFILE_DIR = resolve_profile(brain_path)
    print("brain-init: auto-initialising vault...")
    init_core(brain_path)
    init_vault_skills(brain_path)
    stage_brain_plugin(brain_path)
    print("brain-init: done.")
```

Declare `_PROFILE = None` and `_PROFILE_DIR = None` at module level near the other constants.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_brain_init_profile.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add tools/brain-init tests/test_brain_init_profile.py
git commit -m "feat: brain-init resolves and validates the brain profile"
```

---

### Task 8: Folders + templates + zk config from the profile (Seams 2, 3, zk)

**Files:**
- Modify: `tools/brain-init` — `init_ace_folders` (507) → `init_profile_folders`; `init_core` (318) template + zk-config source; the wizard folder step (642–658)
- Test: `tests/test_brain_init_profile.py`

**Interfaces:**
- Consumes: `_PROFILE`, `_PROFILE_DIR` (Task 7), `compose_zk_config`, `emit_toml` (Task 3).
- Produces: `init_profile_folders(brain_path, profile)`; `init_core` writes `<brain>/.zk/config.toml` composed from infra + profile, and copies templates from `<profile_dir>/templates/`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_brain_init_profile.py
import tomllib


def test_init_creates_profile_folders(tmp_path):
    _run_init(tmp_path)
    for folder in ["Atlas", "Efforts", "Cards", "Calendar", "Sources"]:
        assert os.path.isdir(tmp_path / folder), f"missing {folder}"


def test_init_composes_zk_config_with_templates_excluded(tmp_path):
    _run_init(tmp_path)
    cfg_path = tmp_path / ".zk" / "config.toml"
    assert cfg_path.is_file()
    data = tomllib.loads(cfg_path.read_text())
    assert "templates/" in data["notebook"]["exclude"]
    assert data["note"]["filename"] == "{{slug title}}"
    assert data["extra"]["author"] == "Chris"


def test_init_copies_templates_from_profile(tmp_path):
    _run_init(tmp_path)
    assert os.path.isfile(tmp_path / ".zk" / "templates" / "default.md")
```

Note: `run_auto` currently does not create folders (that is a wizard step). Add folder creation to `run_auto` too so `--auto` produces them — matching the container's non-interactive first-run.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_brain_init_profile.py -k "folders or zk_config or templates" -v`
Expected: FAIL — folders not created in `--auto`; `.zk/config.toml` not composed

- [ ] **Step 3: Write minimal implementation**

Define the engine's zk infra dict and rewrite `init_core`'s zk handling. Add near source candidates:

```python
# Engine-owned zk infrastructure (container paths + structural excludes).
# Convention keys (filename, template, author, filter) come from the profile.
_ZK_INFRA = {
    "notebook": {"exclude": ["templates/"]},
    "note": {"extension": "md", "id-charset": "alphanum", "id-length": 0},
    "tool": {"pager": "cat",
             "fzf-preview": "bat --color=always --style=plain --theme=TwoDark /brain/{}"},
}
```

Replace the template/zk-config portion of `init_core` (the `zk_source`/copytree logic, lines 320–348) with profile-sourced templates + composed config:

```python
def init_core(brain_path):
    """Create .zk (composed config + profile templates), .ai, and .vscode."""
    from lib.profile import compose_zk_config, emit_toml

    zk_dest = os.path.join(brain_path, ".zk")
    templates_dest = os.path.join(zk_dest, "templates")
    os.makedirs(templates_dest, exist_ok=True)

    # Compose and write .zk/config.toml (infra + profile conventions).
    config = compose_zk_config(_ZK_INFRA, _PROFILE.zk)
    with open(os.path.join(zk_dest, "config.toml"), "w") as f:
        f.write(emit_toml(config))
    print("  Wrote .zk/config.toml (infra + profile conventions)")

    # Copy templates from the profile, adding any not already present.
    src_templates = os.path.join(_PROFILE_DIR, "templates")
    new_templates = []
    for name in sorted(os.listdir(src_templates)):
        src_file = os.path.join(src_templates, name)
        dst_file = os.path.join(templates_dest, name)
        if os.path.isfile(src_file) and not os.path.exists(dst_file):
            shutil.copy2(src_file, dst_file)
            new_templates.append(name)
    if new_templates:
        print(f"  Added {len(new_templates)} template(s): {', '.join(new_templates)}")
    else:
        print("  Templates up to date")

    ai_dest = os.path.join(brain_path, ".ai")
    os.makedirs(ai_dest, exist_ok=True)
    print("  Ensured .ai/ exists")

    vscode_source = _find_source(_VSCODE_SOURCE_CANDIDATES)
    if vscode_source is not None:
        vscode_dest = os.path.join(brain_path, ".vscode")
        if not os.path.isdir(vscode_dest):
            shutil.copytree(vscode_source, vscode_dest)
            print("  Created .vscode/ (workspace config)")
```

Rename and reparametrise the folders function:

```python
def init_profile_folders(brain_path, profile):
    """Create the profile's folder structure."""
    for folder in profile.folders:
        os.makedirs(os.path.join(brain_path, folder), exist_ok=True)
    print(f"  Ensured folders: {', '.join(profile.folders)}")
```

Add folder creation to `run_auto` (after `init_core`):

```python
    init_profile_folders(brain_path, _PROFILE)
```

Update the wizard folder step (642–658) to use `_PROFILE.folders` instead of `ACE_FOLDERS` and call `init_profile_folders(brain_path, _PROFILE)`. Remove the now-unused `ACE_FOLDERS` constant and old `init_ace_folders`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_brain_init_profile.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add tools/brain-init tests/test_brain_init_profile.py
git commit -m "feat: source folders, templates, and zk config from the profile"
```

---

### Task 9: Skills + plugin identity from the profile (Seam 4)

**Files:**
- Modify: `tools/brain-init` — `init_vault_skills` (363), `stage_brain_plugin` (400); remove `_VAULT_SKILL_NAMES`/`_GLOBAL_SKILL_NAMES` (59–68)
- Test: `tests/test_brain_init_profile.py`

**Interfaces:**
- Consumes: `_PROFILE`, `_PROFILE_DIR`.
- Produces: vault skills copied from `<profile_dir>/skills/vault/`, global skills + plugin/marketplace/.mcp.json identity from `_PROFILE.skills`/`_PROFILE.plugin`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_brain_init_profile.py
import json


def test_init_stages_all_11_global_skills(tmp_path):
    _run_init(tmp_path)
    staged = os.listdir(tmp_path / ".ai" / "brain-plugin" / "skills")
    assert "brain-distil" in staged  # the fix
    assert len(staged) == 11


def test_init_stages_vault_skills_from_profile(tmp_path):
    _run_init(tmp_path)
    vault = os.listdir(tmp_path / ".claude" / "skills")
    assert set(vault) >= {"brain-daily", "brain-extract", "brain-hygiene",
                          "brain-rename", "brain-reorganise"}


def test_plugin_manifest_uses_profile_identity(tmp_path):
    _run_init(tmp_path)
    manifest = json.loads(
        (tmp_path / ".ai" / "brain-plugin" / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["name"] == "second-brain"
    assert manifest["author"]["name"] == "kitchencoder"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_brain_init_profile.py -k "global_skills or vault_skills or plugin_manifest" -v`
Expected: FAIL — today only 10 global skills stage; vault skills come from image source, not profile

- [ ] **Step 3: Write minimal implementation**

In `init_vault_skills` (363), source from the profile and iterate `_PROFILE.vault_skills`:

```python
def init_vault_skills(brain_path):
    """Copy the profile's vault skills into <vault>/.claude/skills/."""
    skills_source = os.path.join(_PROFILE_DIR, "skills", "vault")
    dest_dir = os.path.join(brain_path, ".claude", "skills")
    os.makedirs(dest_dir, exist_ok=True)
    updated = []
    for name in _PROFILE.vault_skills:
        src = os.path.join(skills_source, name)
        dst = os.path.join(dest_dir, name)
        if not os.path.isdir(src):
            continue
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        elif os.path.islink(dst):
            os.remove(dst)
        shutil.copytree(src, dst)
        updated.append(name)
    if updated:
        print(f"  Updated {len(updated)} vault skills in .claude/skills/")

    # Seed vault-level CLAUDE.md from the profile.
    vault_claude_src = os.path.join(_PROFILE_DIR, "claude", "vault-claude.md")
    vault_claude_dst = os.path.join(brain_path, ".claude", "CLAUDE.md")
    if os.path.isfile(vault_claude_src) and not os.path.isfile(vault_claude_dst):
        shutil.copy2(vault_claude_src, vault_claude_dst)
        print("  Seeded .claude/CLAUDE.md")
```

In `stage_brain_plugin` (400), replace the hardcoded identity and skill source:

```python
def stage_brain_plugin(brain_path):
    """Stage a Claude Code plugin at <vault>/.ai/brain-plugin/ using profile identity."""
    skills_source = os.path.join(_PROFILE_DIR, "skills", "global")
    plugin = _PROFILE.plugin

    ai_dir = os.path.join(brain_path, ".ai")
    plugin_dir = os.path.join(ai_dir, "brain-plugin")
    manifest_dir = os.path.join(plugin_dir, ".claude-plugin")
    skills_dir = os.path.join(plugin_dir, "skills")
    os.makedirs(manifest_dir, exist_ok=True)
    os.makedirs(skills_dir, exist_ok=True)

    manifest = {
        "name": plugin.name,
        "version": "1.0.0",
        "description": f"Global brain skills and MCP server for {plugin.name}",
        "author": {"name": plugin.author},
    }
    with open(os.path.join(manifest_dir, "plugin.json"), "w") as f:
        json.dump(manifest, f, indent=2); f.write("\n")

    marketplace = {
        "name": plugin.name,
        "owner": {"name": plugin.author},
        "plugins": [{
            "name": plugin.name,
            "source": "./brain-plugin",
            "description": f"Global brain skills and MCP server for {plugin.name}",
            "author": {"name": plugin.author},
        }],
    }
    marketplace_manifest_dir = os.path.join(ai_dir, ".claude-plugin")
    os.makedirs(marketplace_manifest_dir, exist_ok=True)
    with open(os.path.join(marketplace_manifest_dir, "marketplace.json"), "w") as f:
        json.dump(marketplace, f, indent=2); f.write("\n")

    mcp_config = {"mcpServers": {plugin.name: {"type": "http",
                  "url": "http://127.0.0.1:7780/mcp/"}}}
    with open(os.path.join(plugin_dir, ".mcp.json"), "w") as f:
        json.dump(mcp_config, f, indent=2); f.write("\n")

    staged = []
    for name in _PROFILE.global_skills:
        src = os.path.join(skills_source, name)
        dst = os.path.join(skills_dir, name)
        if not os.path.isdir(src):
            continue
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        staged.append(name)

    # plugin-level CLAUDE.md + hooks from the profile
    plugin_claude_src = os.path.join(_PROFILE_DIR, "claude", "plugin-claude.md")
    if os.path.isfile(plugin_claude_src):
        shutil.copy2(plugin_claude_src, os.path.join(plugin_dir, "CLAUDE.md"))

    hooks_source = os.path.join(_PROFILE_DIR, "hooks")
    if os.path.isdir(hooks_source):
        hooks_dst = os.path.join(plugin_dir, "hooks")
        if os.path.isdir(hooks_dst):
            shutil.rmtree(hooks_dst)
        shutil.copytree(hooks_source, hooks_dst)
        for name in os.listdir(hooks_dst):
            fpath = os.path.join(hooks_dst, name)
            if os.path.isfile(fpath) and (name.endswith(".sh") or name.endswith(".cmd")):
                os.chmod(fpath, 0o755)

    if staged:
        print(f"  Staged brain plugin to .ai/brain-plugin/ ({len(staged)} skills + MCP + hooks)")
```

Add `plugin-claude.md` to the ace profile so the plugin CLAUDE.md still seeds:

```bash
cp claude/plugin-claude.md profiles/ace/claude/plugin-claude.md
```

Delete the now-unused `_VAULT_SKILL_NAMES`, `_GLOBAL_SKILL_NAMES` constants and the `_SKILLS_SOURCE_CANDIDATES`, `_GLOBAL_SKILLS_SOURCE_CANDIDATES`, `_CLAUDE_TEMPLATES_CANDIDATES`, `_HOOKS_SOURCE_CANDIDATES` lists (now sourced from the profile).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_brain_init_profile.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add tools/brain-init profiles/ace/claude/plugin-claude.md tests/test_brain_init_profile.py
git commit -m "feat: stage skills and plugin identity from the profile (fixes brain-distil drop)"
```

---

### Task 10: Profile-aware session-start hook (fixes unconditional primer)

**Files:**
- Modify: `profiles/ace/hooks/session-start.sh`
- Test: `tests/test_session_start_hook.py` (create)

**Interfaces:**
- Produces: the hook greps for its profile's marker and only emits the "brain connected" primer when the marker is present OR when explicitly the brain's own project. The unconditional primer branch (today's `else` at line 75–83 that fires in every project) is gated behind an env/marker check so unrelated projects stay silent.

Design: the profile's hook hardcodes its own marker (`brain` for ace) at the top: `MARKER="brain"`. The primer only fires when a `CLAUDE.md` with `<!-- $MARKER -->` is found on the walk-up; otherwise the hook emits empty context (`additionalContext: ""`) and exits 0.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_session_start_hook.py
import json
import os
import subprocess

_HOOK = os.path.join(os.path.dirname(__file__), "..", "profiles", "ace", "hooks",
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_session_start_hook.py -v`
Expected: FAIL — `test_hook_silent_when_no_marker` fails because the current hook always emits the generic primer

- [ ] **Step 3: Write minimal implementation**

Edit `profiles/ace/hooks/session-start.sh`: add `MARKER="brain"` near the top, replace the hardcoded `<!-- brain -->`/`<!-- /brain -->` sed patterns with `<!-- $MARKER -->`/`<!-- /$MARKER -->`, and replace the `else` branch (75–83) so that when no marked block is found the hook emits empty context:

```bash
# --- Build context ---
if [ -n "$effort" ]; then
    context="This project is linked to a brain effort: ${effort}"
    if [ -n "$summary" ]; then
        context="${context}\nSummary: ${summary}"
    fi
    context="${context}\n\nThe brain-context skill can load full project context from the brain."
    if [ -n "$claude_md_path" ]; then
        context="${context}\nCLAUDE.md with brain block: ${claude_md_path}"
    fi
else
    # No brain-marked project here — stay silent so unrelated projects and
    # other installed brains are unaffected.
    context=""
fi
```

Keep the JSON emission as-is (an empty `additionalContext` is valid).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_session_start_hook.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add profiles/ace/hooks/session-start.sh tests/test_session_start_hook.py
git commit -m "fix: session-start hook stays silent outside brain-marked projects"
```

---

### Task 11: Backward-compatibility proof — `ace` reproduces today

**Files:**
- Test: `tests/test_ace_backward_compat.py` (create)

**Interfaces:**
- Consumes: everything above.
- Produces: a single acceptance test asserting the values the engine now reads from the `ace` profile equal the values previously hardcoded — the "ace == today" gate, with the `brain-distil` correction explicit.

- [ ] **Step 1: Write the test**

```python
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
    plugin = load_profile(_ACE).plugin
    assert (plugin.name, plugin.author, plugin.marker) == \
        ("second-brain", "kitchencoder", "brain")
```

- [ ] **Step 2: Run the full suite**

Run: `task test`
Expected: PASS — all profile, brain-init, hook, and backward-compat tests green, and the pre-existing suite (`test_brain_service.py` etc.) still passes.

- [ ] **Step 3: Commit**

```bash
git add tests/test_ace_backward_compat.py
git commit -m "test: assert ace profile reproduces pre-refactor behaviour"
```

---

## Self-Review

**Spec coverage (Plan A's slice — Seams 1–4 + zk split + hook fix):**
- Seam 1 (Config loader) → Tasks 1, 5. ✓
- Seam 2 (folders) → Task 8. ✓
- Seam 3 (templates) → Task 8. ✓
- Seam 4 (skills + plugin identity + vocabulary) → Task 9; collision check → Task 4 (wired into `resolve_profile` is deferred to Plan B's multi-brain path — noted below). ✓ with caveat.
- zk config split → Tasks 3, 8. ✓
- Init-time validation → Tasks 2, 7. ✓
- brain-distil fix → Tasks 6, 9, 11. ✓
- Hook fix (unconditional primer + marker) → Task 10. ✓
- Backward-compat proof → Task 11. ✓

**Deferred to Plan B (correctly out of scope here):** git clone / `--profile-repo` / `brain-profile update`; `setup.sh` boot rewire and image-skill-seed removal; removing `zk/`, `skills/`, `brain-skills/` from the repo; extracting `ace` to its own repo; excluding `.brain/.git` from sync. `check_collisions` (Task 4) is built and unit-tested here but only *invoked* at init in Plan B, where a second installed profile can actually exist — Plan A has no multi-profile install path, so wiring it into `resolve_profile` now would be untestable. This is intentional.

**Deferred to Plan C:** Seam 5 (generic query, dynamic MCP/REST schema, `where`). None of Plan A changes `handle_brain_query` or the MCP/REST schemas.

**Deferred to phase 3:** Seams 6–7 (auth, visibility).

**Placeholder scan:** none — every step carries real code or exact commands.

**Type consistency:** `Profile`, `Field`, `Plugin`, `Auth` shapes defined in Task 1 are used unchanged in Tasks 2–11. `load_profile`/`validate_profile`/`check_collisions`/`compose_zk_config`/`emit_toml` signatures match across definition and use. `_PROFILE`/`_PROFILE_DIR` module globals introduced in Task 7 are consumed in Tasks 8–9. `init_profile_folders(brain_path, profile)` signature consistent between Task 8 definition and `run_auto`/wizard call sites.

**One known integration risk to watch during execution:** `brain-init` currently seeds vault skills and the plugin CLAUDE.md from image source dirs that Task 9 removes. `setup.sh` also independently reseeds `~/.claude/skills` from the image on every start (`setup.sh:21`). Plan A leaves `setup.sh` untouched, so container behaviour is unchanged there; the switch of that seed to the profile is Plan B, Task (setup.sh rewire). If executing Plan A against a live container, the host `~/.claude/skills` still comes from the image seed until Plan B — expected, not a regression.
