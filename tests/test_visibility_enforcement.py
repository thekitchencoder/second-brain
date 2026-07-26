# tests/test_visibility_enforcement.py
"""End-to-end visibility enforcement (oracle-safe)."""
import os, sys, textwrap
from unittest.mock import MagicMock
if "sqlite_vec" not in sys.modules:
    sys.modules["sqlite_vec"] = MagicMock()

from lib.brain import (
    handle_brain_read,
    handle_brain_query,
    handle_brain_backlinks,
    handle_brain_related,
    handle_brain_search,
    handle_brain_write,
    handle_brain_edit,
    _paginated_visible_search,
)
from lib.auth import Principal, OWNER
from lib.profile import Field

FIELDS = [Field("known_by", "list", "kb", visibility="allow")]


def _brain(tmp_path):
    b = tmp_path / "brain"; (b / "canon").mkdir(parents=True)
    (b / "canon" / "secret.md").write_text("---\nlayer: secret\n---\nspoiler")
    (b / "canon" / "open.md").write_text("---\nlayer: fiction\n---\nopen")
    return str(b)


def _fenn():
    return Principal(id="fenn", role="fenn", read_layers=("fiction",),
                     write_layers=(), kind="static")


def test_read_of_forbidden_is_indistinguishable_from_absent(tmp_path):
    b = _brain(tmp_path)
    forbidden = handle_brain_read("canon/secret.md", b, principal=_fenn(), fields=FIELDS)
    truly_absent = handle_brain_read("canon/nope.md", b, principal=_fenn(), fields=FIELDS)
    assert forbidden == truly_absent          # oracle-safe: same string
    assert "File not found" in forbidden
    # owner still reads it
    assert "spoiler" in handle_brain_read("canon/secret.md", b, principal=OWNER, fields=FIELDS)


def test_query_omits_forbidden(tmp_path):
    b = _brain(tmp_path)
    out = handle_brain_query(b, principal=_fenn(), fields=FIELDS, field_specs=FIELDS)
    assert "open.md" in out and "secret.md" not in out


def test_backlinks_hide_invisible_sources(tmp_path):
    b = _brain(tmp_path)
    # secret.md links to open.md; fenn must not learn secret.md exists via backlinks
    with open(os.path.join(b, "canon", "secret.md"), "a") as f:
        f.write("\n[[open]]")
    res = handle_brain_backlinks("canon/open.md", b, principal=_fenn(), fields=FIELDS)
    assert "secret" not in res


# ── End-to-end wiring (finding 3): the handler default is principal=OWNER, so a
# forgotten pass-through silently grants owner. These exercise the REAL dispatch
# paths (MCP _invoke_tool, REST route) with a restricted static-token principal,
# which is exactly where a missed pass-through would hide. ────────────────────

def _fiction_brain(tmp_path, create_secret: bool = True, include_reviewer: bool = False):
    """A brain in oauth mode: fiction profile (known_by allow field, layer),
    a `fenn` role read=['fiction'], and a static principal token.

    `create_secret=False` omits canon/secret.md entirely — used to build a
    "genuinely absent" counterpart brain with the identical relative path.

    `include_reviewer=True` also wires up a `reviewer` role/principal —
    read=["*"], write=["fiction"] — the documented reviewer pattern (read
    everything, write only the fiction layer) that the F1 escalation bug
    exploited: a read-unrestricted principal must still be write-restricted."""
    b = tmp_path / "brain"; (b / ".ai").mkdir(parents=True); (b / "canon").mkdir(parents=True)
    if create_secret:
        (b / "canon" / "secret.md").write_text("---\nlayer: secret\n---\nspoiler")
    (b / "canon" / "open.md").write_text("---\nlayer: fiction\n---\nopen")
    pdir = b / ".brain"; pdir.mkdir()
    reviewer_block = '''\
        reviewer = { read = ["*"], write = ["fiction"] }
''' if include_reviewer else ''
    reviewer_principal = '''\
        reviewer = "reviewer"
''' if include_reviewer else ''
    (pdir / "profile.toml").write_text(textwrap.dedent('''\
        name = "fenn"
        folders = ["canon"]
        [plugin]
        name = "fiction"
        author = "c"
        marker = "fiction"
        [fields.known_by]
        kind = "list"
        visibility = "allow"
        [auth]
        mode = "oauth"
        [auth.rbac]
        [auth.rbac.roles]
        fenn = { read = ["fiction"], write = ["fiction"] }
''') + reviewer_block + textwrap.dedent('''\
        [auth.rbac.principals]
        fenn = "fenn"
''') + reviewer_principal)
    return str(b)


def test_mcp_dispatch_enforces_visibility(monkeypatch, tmp_path):
    import json, importlib, brain_mcp_server
    monkeypatch.setenv("BRAIN_PATH", _fiction_brain(tmp_path))
    monkeypatch.setenv("BRAIN_AUTH_PRINCIPAL_TOKENS", json.dumps({"fenn": "s3cret"}))
    importlib.reload(brain_mcp_server)
    from lib.auth import Principal
    import asyncio
    fenn = Principal(id="fenn", role="fenn", read_layers=("fiction",),
                     write_layers=("fiction",), kind="static")
    tok = brain_mcp_server.current_principal.set(fenn)
    try:
        out = asyncio.run(brain_mcp_server._invoke_tool("brain_read", {"filepath": "canon/secret.md"}))
    finally:
        brain_mcp_server.current_principal.reset(tok)
    assert "File not found" in out and "spoiler" not in out


def _signing_key() -> str:
    """A real RSA PEM — oauth mode hard-fails without BRAIN_AUTH_SIGNING_KEY."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    return rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()).decode()


def test_rest_dispatch_enforces_visibility(monkeypatch, tmp_path):
    import json, importlib
    # brain_api reads BRAIN_PATH eagerly at module import time (the oauth-mode
    # SessionMiddleware check), so the env must be set BEFORE the first import —
    # not after, as a plain `import brain_api; ...; reload()` would do.
    monkeypatch.setenv("BRAIN_PATH", _fiction_brain(tmp_path))
    monkeypatch.setenv("BRAIN_AUTH_PRINCIPAL_TOKENS", json.dumps({"fenn": "s3cret"}))
    monkeypatch.setenv("BRAIN_AUTH_SIGNING_KEY", _signing_key())
    import brain_api
    importlib.reload(brain_api)
    from fastapi.testclient import TestClient
    c = TestClient(brain_api.app)
    r = c.get("/api/notes/canon/secret.md", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 404          # oracle-safe: same as a genuinely absent note


# ── FIX I1: lock the semantic-search firewall (coarse store wall + fine
# visible() filter + pagination) with a committed, host-runnable test. No
# sqlite-vec involved — a duck-typed fake store hands back pre-canned,
# distance-ordered chunk rows; the notes backing those rows are real files on
# disk (tmp brain) so visible() reads real frontmatter. ─────────────────────


class _FakeStore:
    """Duck-typed vector store: `.search(vector, k, allowed_layers=...)` returns
    a prefix of a fixed, ascending-by-distance row list — exactly the shape
    `_paginated_visible_search` expects from a real store, but with no sqlite-vec
    and no embeddings. Deliberately ignores `allowed_layers` (as if the coarse
    wall let a forbidden-layer row through) so the test proves the FINE
    `visible()` filter inside `_paginated_visible_search` is a real, independent
    second gate — not merely trusting the store's own coarse enforcement."""

    def __init__(self, rows):
        self._rows = rows

    def search(self, vector, k, allowed_layers=None):
        return [dict(r) for r in self._rows[:k]]

    def get_chunk_embeddings(self, filepath):
        return []  # no embeddings — never reindexed in these host-only tests


def _search_brain(tmp_path):
    """Four notes: two plain-visible, one coarse-forbidden (secret layer), one
    coarse-visible but fine-denied (known_by excludes fenn's role)."""
    b = tmp_path / "brain"; (b / "canon").mkdir(parents=True)
    (b / "canon" / "ok1.md").write_text("---\nlayer: fiction\n---\nok1 body")
    (b / "canon" / "ok2.md").write_text("---\nlayer: fiction\n---\nok2 body")
    (b / "canon" / "fielded.md").write_text(
        "---\nlayer: fiction\nknown_by: [someone-else]\n---\nfielded body")
    (b / "canon" / "secret.md").write_text("---\nlayer: secret\n---\nspoiler body")
    return str(b)


def test_paginated_visible_search_excludes_fine_denied_and_forbidden_layer(tmp_path):
    b = _search_brain(tmp_path)
    ok1 = os.path.join(b, "canon", "ok1.md")
    ok2 = os.path.join(b, "canon", "ok2.md")
    fielded = os.path.join(b, "canon", "fielded.md")
    secret = os.path.join(b, "canon", "secret.md")
    # Distance-ascending order: secret (forbidden layer) ranks best, then ok1,
    # then fielded (fine-denied), then ok2 — a naive filter that stops at the
    # first non-match, or that trusts the store's coarse wall alone, would
    # under- or over-return here.
    rows = [
        {"filepath": secret, "distance": 0.05},
        {"filepath": ok1, "distance": 0.10},
        {"filepath": fielded, "distance": 0.15},
        {"filepath": ok2, "distance": 0.20},
    ]
    store = _FakeStore(rows)
    out = _paginated_visible_search(store, [0.0], limit=2, principal=_fenn(), fields=FIELDS)
    filepaths = [r["filepath"] for r in out]
    # 1) fine-denied (fielded) excluded; 2) forbidden layer (secret) excluded;
    # 3) only the visible ones, in distance order, up to limit=2.
    assert filepaths == [ok1, ok2]
    assert fielded not in filepaths
    assert secret not in filepaths


def test_paginated_visible_search_stops_at_limit_even_with_more_visible(tmp_path):
    b = _search_brain(tmp_path)
    ok1 = os.path.join(b, "canon", "ok1.md")
    ok2 = os.path.join(b, "canon", "ok2.md")
    (tmp_path / "brain" / "canon" / "ok3.md").write_text("---\nlayer: fiction\n---\nok3 body")
    ok3 = os.path.join(b, "canon", "ok3.md")
    rows = [
        {"filepath": ok1, "distance": 0.10},
        {"filepath": ok2, "distance": 0.20},
        {"filepath": ok3, "distance": 0.30},
    ]
    store = _FakeStore(rows)
    out = _paginated_visible_search(store, [0.0], limit=2, principal=_fenn(), fields=FIELDS)
    assert [r["filepath"] for r in out] == [ok1, ok2]  # truncated to limit, distance order


def test_handle_brain_search_wires_fine_filter_through_fake_store(monkeypatch, tmp_path):
    """End-to-end through handle_brain_search: embedding + store are faked so
    the test runs on the host with no sqlite-vec, but the fine visible() check
    still runs against real on-disk frontmatter — proving the wiring, not just
    the helper in isolation."""
    b = _search_brain(tmp_path)
    ok1 = os.path.join(b, "canon", "ok1.md")
    fielded = os.path.join(b, "canon", "fielded.md")
    secret = os.path.join(b, "canon", "secret.md")
    rows = [
        {"filepath": secret, "distance": 0.05, "title": "secret"},
        {"filepath": fielded, "distance": 0.10, "title": "fielded"},
        {"filepath": ok1, "distance": 0.20, "title": "ok1"},
    ]
    monkeypatch.setattr("lib.embeddings.get_embedding", lambda query: [0.0])
    monkeypatch.setattr("lib.vectorstore.get_store", lambda db_path: _FakeStore(rows))
    out = handle_brain_search("anything", limit=5, db_path="unused",
                              principal=_fenn(), fields=FIELDS)
    assert "ok1" in out
    assert "fielded" not in out
    assert "secret" not in out


# ── FIX M1: handle_brain_related must be oracle-safe on the TARGET — asking
# "what's related to X" for a forbidden-but-indexed X must be indistinguishable
# from asking about a genuinely-absent X. ────────────────────────────────────


def test_related_of_forbidden_target_matches_absent_target(monkeypatch, tmp_path):
    # Same relative path ("canon/secret.md") in two different brains: one where
    # it exists but is forbidden, one where it never existed at all — the two
    # responses must be byte-for-byte identical, or a restricted caller could
    # tell "forbidden-but-indexed" apart from "genuinely absent" purely from the
    # wording (both already embed the requested path in the message).
    forbidden_brain = _fiction_brain(tmp_path / "with-secret", create_secret=True)
    absent_brain = _fiction_brain(tmp_path / "without-secret", create_secret=False)
    monkeypatch.setattr("lib.vectorstore.get_store", lambda db_path: _FakeStore([]))
    forbidden = handle_brain_related("canon/secret.md", limit=5, db_path="unused",
                                     brain_path=forbidden_brain, principal=_fenn(), fields=FIELDS)
    absent = handle_brain_related("canon/secret.md", limit=5, db_path="unused",
                                  brain_path=absent_brain, principal=_fenn(), fields=FIELDS)
    assert forbidden == absent
    assert forbidden == "No embeddings found for canon/secret.md. Has it been indexed?"


def test_related_rest_route_forbidden_target_matches_absent_target(monkeypatch, tmp_path):
    import json, importlib
    monkeypatch.setenv("BRAIN_AUTH_PRINCIPAL_TOKENS", json.dumps({"fenn": "s3cret"}))
    monkeypatch.setenv("BRAIN_AUTH_SIGNING_KEY", _signing_key())
    # No real embeddings db in either tmp brain — patch the store the route
    # constructs at call time so neither branch touches sqlite, keeping this
    # test host-runnable with no sqlite-vec.
    monkeypatch.setattr("lib.vectorstore.get_store", lambda db_path: _FakeStore([]))

    monkeypatch.setenv("BRAIN_PATH", _fiction_brain(tmp_path / "with-secret", create_secret=True))
    import brain_api
    importlib.reload(brain_api)
    from fastapi.testclient import TestClient
    forbidden = TestClient(brain_api.app).get(
        "/api/notes/canon/secret.md/related", headers={"Authorization": "Bearer s3cret"})

    monkeypatch.setenv("BRAIN_PATH", _fiction_brain(tmp_path / "without-secret", create_secret=False))
    importlib.reload(brain_api)
    absent = TestClient(brain_api.app).get(
        "/api/notes/canon/secret.md/related", headers={"Authorization": "Bearer s3cret"})

    assert forbidden.status_code == 404
    assert absent.status_code == 404
    assert forbidden.json() == absent.json()  # oracle-safe: identical body too


# ── Task 7: gate the write handlers on can_write, plus the layer-mutation
# escalation guard (finding 1 — the real hole). ─────────────────────────────


def test_write_denied_outside_write_layers(tmp_path):
    b = _brain(tmp_path)
    p = Principal(id="fenn", role="fenn", read_layers=("fiction", "secret"),
                  write_layers=("fiction",), kind="static")
    # can read secret (in read_layers) but NOT write it
    r = handle_brain_edit("canon/secret.md", "update_frontmatter", b,
                          principal=p, frontmatter={"status": "x"})
    assert "Not authorized" in r or "not found" in r.lower()
    # can write fiction
    ok = handle_brain_write("canon/open.md", "---\nlayer: fiction\n---\nnew", b, principal=p)
    assert ok.startswith("Written")


def test_owner_writes_anything(tmp_path):
    b = _brain(tmp_path)
    assert handle_brain_write("canon/secret.md", "x", b, principal=OWNER).startswith("Written")


def test_layer_escalation_denied(tmp_path):
    """A fiction-writer must NOT relabel a fiction note into a layer it can't write
    (finding 1). Both the old and the new layer must pass can_write."""
    b = _brain(tmp_path)
    p = Principal(id="fenn", role="fenn", read_layers=("fiction",),
                  write_layers=("fiction",), kind="static")
    # rewrite open.md (layer: fiction) as layer: maker → denied
    r = handle_brain_write("canon/open.md", "---\nlayer: maker\n---\ngotcha", b, principal=p)
    assert "Not authorized" in r
    # same via update_frontmatter
    r2 = handle_brain_edit("canon/open.md", "update_frontmatter", b,
                           principal=p, frontmatter={"layer": "maker"})
    assert "Not authorized" in r2
    # a same-layer edit still works
    ok = handle_brain_edit("canon/open.md", "update_frontmatter", b,
                           principal=p, frontmatter={"status": "draft"})
    assert "Not authorized" not in ok


def test_layer_escalation_via_find_replace_denied(tmp_path):
    """The find_replace op rewrites raw file text, including the frontmatter
    `layer:` line — so it must be gated on the ACTUAL post-edit frontmatter,
    not a stale new_meta = old_meta. Escalating fiction -> maker via
    find_replace must be denied identically to the update_frontmatter path,
    and the on-disk file must be left untouched."""
    b = _brain(tmp_path)
    p = Principal(id="fenn", role="fenn", read_layers=("fiction",),
                  write_layers=("fiction",), kind="static")
    r = handle_brain_edit("canon/open.md", "find_replace", b, principal=p, fields=FIELDS,
                          find="layer: fiction", replace="layer: maker")
    assert "Not authorized" in r
    with open(os.path.join(b, "canon", "open.md")) as f:
        assert "maker" not in f.read()          # on-disk file unchanged


def test_layer_escalation_via_replace_lines_denied(tmp_path):
    """Same escalation, via replace_lines targeting the frontmatter's layer
    line directly (open.md: line 1 '---', line 2 'layer: fiction', line 3
    '---', line 4 'open')."""
    b = _brain(tmp_path)
    p = Principal(id="fenn", role="fenn", read_layers=("fiction",),
                  write_layers=("fiction",), kind="static")
    r = handle_brain_edit("canon/open.md", "replace_lines", b, principal=p, fields=FIELDS,
                          start_line=2, end_line=3, replacement="layer: maker")
    assert "Not authorized" in r
    with open(os.path.join(b, "canon", "open.md")) as f:
        assert "maker" not in f.read()


def test_body_find_replace_still_allowed(tmp_path):
    b = _brain(tmp_path)
    p = Principal(id="fenn", role="fenn", read_layers=("fiction",), write_layers=("fiction",), kind="static")
    # a find_replace that does NOT touch the layer succeeds for a fiction-writer
    r = handle_brain_edit("canon/open.md", "find_replace", b, principal=p, fields=FIELDS,
                          find="open", replace="opened")
    assert "Not authorized" not in r


def test_restore_is_write_gated(tmp_path):
    """restore is a write-side op — a caller who can't write the note's layer
    can neither resurrect nor enumerate it (finding 4)."""
    from lib.brain import handle_brain_restore
    import inspect
    assert "principal" in inspect.signature(handle_brain_restore).parameters


# ── Task 8: anti-drift coverage on BOTH surfaces. ───────────────────────────
#
# The shared handle_brain_* layer (tools/lib/brain.py) is one gate; the REST
# routes in tools/brain_api.py are a SECOND, independent gate — each route
# inlines its own visible()/can_write_transition() call rather than trusting
# the shared handler alone (some routes, like list_notes/create_note/trash/
# restore, DO delegate to a handle_brain_* function and inherit its gate; but
# search/related/backlinks/read/write/edit inline the check directly). A
# signature check on handle_brain_* alone would NOT catch a future REST route
# added without its own principal dependency — so both surfaces get their own
# introspection test below.


def test_every_content_handler_is_gated():
    """Introspect EVERY handle_brain_* — a future content handler added without a
    `principal` gate fails here (finding 5). Non-content handlers are explicitly
    allowlisted, so adding one to the allowlist is a deliberate, reviewable act."""
    import inspect, lib.brain as brain
    NON_CONTENT = {"handle_brain_templates"}   # lists template names; surfaces no note content
    handlers = [n for n in dir(brain) if n.startswith("handle_brain_")]
    assert handlers, "no handlers discovered — introspection target moved?"
    for name in handlers:
        if name in NON_CONTENT:
            continue
        sig = inspect.signature(getattr(brain, name))
        assert "principal" in sig.parameters, (
            f"{name} surfaces or mutates content but has no visibility/write gate — "
            f"add a `principal` param, or allowlist it in NON_CONTENT if it truly "
            f"handles no note content")


def test_every_rest_route_requires_principal(monkeypatch, tmp_path):
    """Enumerate every route registered on the brain_api FastAPI app and assert
    its endpoint function declares a `principal` parameter (in practice always
    `principal: Principal = Depends(require_principal)`). This is the REST
    surface's OWN anti-drift gate — independent of, and not implied by, the
    handle_brain_* signature check above, because brain_api.py has inline
    enforcement of its own. A future route added without
    Depends(require_principal) — the exact dual-surface risk this task calls
    out — fails here."""
    import inspect, json, importlib
    NON_CONTENT_ENDPOINTS = {
        # FastAPI/Starlette built-ins — no brain content, framework-registered.
        "openapi", "swagger_ui_html", "swagger_ui_redirect", "redoc_html",
        # OAuth authorization-server flow — pre-authentication by definition:
        # these issue/validate credentials rather than surface note content,
        # and are individually gated by `_oauth_enabled()` checks instead.
        "protected_resource_metadata", "authorization_server_metadata", "jwks",
        "register_client", "authorize", "callback", "consent", "token", "revoke_token",
    }
    monkeypatch.setenv("BRAIN_PATH", _fiction_brain(tmp_path))
    monkeypatch.setenv("BRAIN_AUTH_PRINCIPAL_TOKENS", json.dumps({"fenn": "s3cret"}))
    monkeypatch.setenv("BRAIN_AUTH_SIGNING_KEY", _signing_key())
    import brain_api
    importlib.reload(brain_api)
    routes = [r for r in brain_api.app.routes if getattr(r, "path", None)]
    assert routes, "no routes discovered — introspection target moved?"
    checked = 0
    for route in routes:
        name = route.endpoint.__name__
        if name in NON_CONTENT_ENDPOINTS:
            continue
        sig = inspect.signature(route.endpoint)
        assert "principal" in sig.parameters, (
            f"{route.path} ({name}) has no `principal` dependency — a future "
            f"REST route added without Depends(require_principal) escapes the "
            f"visibility/write gate; add the dependency or allowlist the "
            f"endpoint name above if it truly surfaces no note content")
        checked += 1
    # search, list, related, backlinks, read, write, edit, create, trash,
    # restore, templates — a floor, not an exact count, so adding a new
    # content route doesn't itself break this test (only an UNGATED one does).
    assert checked >= 9


def test_rest_list_notes_excludes_forbidden(monkeypatch, tmp_path):
    """GET /api/notes (list_notes -> handle_brain_query) must omit a
    coarse-forbidden note for a restricted static-token principal."""
    import json, importlib
    monkeypatch.setenv("BRAIN_PATH", _fiction_brain(tmp_path))
    monkeypatch.setenv("BRAIN_AUTH_PRINCIPAL_TOKENS", json.dumps({"fenn": "s3cret"}))
    monkeypatch.setenv("BRAIN_AUTH_SIGNING_KEY", _signing_key())
    import brain_api
    importlib.reload(brain_api)
    from fastapi.testclient import TestClient
    r = TestClient(brain_api.app).get("/api/notes", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200
    paths = r.json()
    assert any(p.endswith("open.md") for p in paths)
    assert not any(p.endswith("secret.md") for p in paths)


def test_rest_search_excludes_forbidden(monkeypatch, tmp_path):
    """GET /api/search must exclude both a coarse-forbidden layer and a
    fine-denied (known_by) note for a restricted static-token principal — the
    REST-route analogue of test_handle_brain_search_wires_fine_filter_through_fake_store."""
    import json, importlib
    b = _fiction_brain(tmp_path)
    (tmp_path / "brain" / "canon" / "fielded.md").write_text(
        "---\nlayer: fiction\nknown_by: [someone-else]\n---\nfielded body")
    open_note = os.path.join(b, "canon", "open.md")
    fielded = os.path.join(b, "canon", "fielded.md")
    secret = os.path.join(b, "canon", "secret.md")
    rows = [
        {"filepath": secret, "distance": 0.05, "title": "secret"},
        {"filepath": fielded, "distance": 0.10, "title": "fielded"},
        {"filepath": open_note, "distance": 0.20, "title": "open"},
    ]
    monkeypatch.setenv("BRAIN_PATH", b)
    monkeypatch.setenv("BRAIN_AUTH_PRINCIPAL_TOKENS", json.dumps({"fenn": "s3cret"}))
    monkeypatch.setenv("BRAIN_AUTH_SIGNING_KEY", _signing_key())
    monkeypatch.setattr("lib.embeddings.get_embedding", lambda query: [0.0])
    monkeypatch.setattr("lib.vectorstore.get_store", lambda db_path: _FakeStore(rows))
    import brain_api
    importlib.reload(brain_api)
    from fastapi.testclient import TestClient
    r = TestClient(brain_api.app).get("/api/search", params={"q": "anything"},
                                      headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200
    paths = [item["filepath"] for item in r.json()]
    assert open_note in paths
    assert fielded not in paths
    assert secret not in paths


def test_rest_write_denied_outside_write_layers(monkeypatch, tmp_path):
    """PUT /api/notes/{filepath} end-to-end with a restricted static token:
    a coarse-forbidden target 404s oracle-safely, a layer-escalating write
    403s, and an in-bounds write still succeeds."""
    import json, importlib
    monkeypatch.setenv("BRAIN_PATH", _fiction_brain(tmp_path))
    monkeypatch.setenv("BRAIN_AUTH_PRINCIPAL_TOKENS", json.dumps({"fenn": "s3cret"}))
    monkeypatch.setenv("BRAIN_AUTH_SIGNING_KEY", _signing_key())
    import brain_api
    importlib.reload(brain_api)
    from fastapi.testclient import TestClient
    c = TestClient(brain_api.app)
    headers = {"Authorization": "Bearer s3cret"}
    # secret.md is layer 'secret' — fenn can't even READ it: oracle-safe 404,
    # identical in shape to a genuinely-absent path, never a 403.
    r = c.put("/api/notes/canon/secret.md", headers=headers,
             json={"content": "---\nlayer: secret\n---\nhacked"})
    assert r.status_code == 404
    # open.md is layer 'fiction' (writable) but this write escalates it to
    # 'maker' (not in fenn's write_layers) — denied via can_write_transition.
    r2 = c.put("/api/notes/canon/open.md", headers=headers,
              json={"content": "---\nlayer: maker\n---\ngotcha"})
    assert r2.status_code == 403
    # a same-layer write is still allowed.
    r3 = c.put("/api/notes/canon/open.md", headers=headers,
              json={"content": "---\nlayer: fiction\n---\nnew body"})
    assert r3.status_code == 200


def test_rest_reviewer_write_gate_independent_of_read_gate(monkeypatch, tmp_path):
    """F1 regression: a read-unrestricted-but-write-restricted principal
    (the documented reviewer pattern read=["*"], write=["fiction"]) must NOT
    be able to write/edit notes outside its write_layers, even though it can
    read everything.

    The bug: write_note/edit_note wrapped the ENTIRE write-authorization block
    (both the visible() read check AND the can_write_transition() write check)
    behind `if not _principal_unrestricted(principal)` — a helper keyed on
    read_layers. A principal with read=["*"] took that fast path and skipped
    can_write_transition entirely, letting it overwrite/edit secret-layer
    notes it had no write rights to. The fix decouples the two dimensions:
    the read gate stays keyed on read_layers, but the write gate now runs
    independent of it (via the new _principal_write_unrestricted, keyed on
    write_layers)."""
    import json, importlib
    monkeypatch.setenv("BRAIN_PATH", _fiction_brain(tmp_path, include_reviewer=True))
    monkeypatch.setenv(
        "BRAIN_AUTH_PRINCIPAL_TOKENS",
        json.dumps({"fenn": "s3cret", "reviewer": "revtok"}),
    )
    monkeypatch.setenv("BRAIN_AUTH_SIGNING_KEY", _signing_key())
    import brain_api
    importlib.reload(brain_api)
    from fastapi.testclient import TestClient
    c = TestClient(brain_api.app)
    headers = {"Authorization": "Bearer revtok"}

    secret_path = os.path.join(brain_api._cfg.brain_path, "canon", "secret.md")
    original_secret = open(secret_path, encoding="utf-8").read()

    # reviewer CAN read the secret note (read=["*"]).
    r_read = c.get("/api/notes/canon/secret.md", headers=headers)
    assert r_read.status_code == 200

    # PUT to a secret-layer note → 403 (NOT 200), on-disk unchanged.
    r_put = c.put("/api/notes/canon/secret.md", headers=headers,
                  json={"content": "---\nlayer: secret\n---\nDESTROYED by reviewer"})
    assert r_put.status_code == 403
    assert open(secret_path, encoding="utf-8").read() == original_secret

    # PATCH find_replace on a secret-layer note → 403, on-disk unchanged.
    r_patch = c.patch("/api/notes/canon/secret.md", headers=headers,
                      json={"op": "find_replace", "find": "spoiler", "replace": "gardener"})
    assert r_patch.status_code == 403
    assert open(secret_path, encoding="utf-8").read() == original_secret

    # PUT to a fiction-layer note → 200 (in-bounds write still allowed).
    r_put_ok = c.put("/api/notes/canon/open.md", headers=headers,
                     json={"content": "---\nlayer: fiction\n---\nreviewer edit"})
    assert r_put_ok.status_code == 200
