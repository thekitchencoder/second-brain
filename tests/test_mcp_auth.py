"""Tests for bearer-auth enforcement on the MCP HTTP transport."""
import sys
from unittest.mock import MagicMock

if "sqlite_vec" not in sys.modules:
    sys.modules["sqlite_vec"] = MagicMock()
if "openai" not in sys.modules:
    sys.modules["openai"] = MagicMock()


def test_build_http_app_exposes_well_known(monkeypatch, tmp_path):
    """In oauth mode the MCP HTTP app serves protected-resource metadata unauthenticated."""
    import json, textwrap
    brain = tmp_path / "brain"
    (brain / ".ai").mkdir(parents=True)
    pdir = brain / ".brain"; pdir.mkdir()
    (pdir / "profile.toml").write_text(textwrap.dedent('''\
        name = "fenn"
        folders = ["canon"]
        [plugin]
        name = "fiction"
        author = "chris"
        marker = "fiction"
        [auth]
        mode = "oauth"
        [auth.rbac]
        [auth.rbac.roles]
        owner = { layers = ["*"] }
        [auth.rbac.principals]
        agent = "owner"
    '''))
    monkeypatch.setenv("BRAIN_PATH", str(brain))
    monkeypatch.setenv("BRAIN_AUTH_ISSUER", "https://brain.example")
    monkeypatch.setenv("BRAIN_AUTH_AUDIENCE", "https://brain.example/mcp")
    monkeypatch.setenv("BRAIN_AUTH_PRINCIPAL_TOKENS", json.dumps({"agent": "s3cret"}))
    import importlib, brain_mcp_server
    importlib.reload(brain_mcp_server)
    from starlette.testclient import TestClient
    app = brain_mcp_server._build_http_app(brain_mcp_server._build_server())
    # Use as a context manager so the app's lifespan (which starts the MCP
    # session manager's task group) actually runs — without it, any request
    # that reaches the /mcp mount raises before we even get to check status.
    with TestClient(app) as client:
        assert client.get("/.well-known/oauth-protected-resource").status_code == 200
        # /mcp without a token → 401 in oauth mode
        assert client.post("/mcp", json={}).status_code == 401
        # with the static token, auth passes the gate (the MCP body may still error,
        # but it must NOT be 401)
        r = client.post("/mcp", json={}, headers={"Authorization": "Bearer s3cret"})
        assert r.status_code != 401


def test_mcp_post_without_auth_header_is_401(monkeypatch, tmp_path):
    """FIX 6: /mcp POST with no Authorization header at all must be 401 in
    oauth mode — pinning the plain-unauthenticated-request invariant on its
    own, separate from the well-known/bypass checks above."""
    import json, textwrap
    brain = tmp_path / "brain"
    (brain / ".ai").mkdir(parents=True)
    pdir = brain / ".brain"; pdir.mkdir()
    (pdir / "profile.toml").write_text(textwrap.dedent('''\
        name = "fenn"
        folders = ["canon"]
        [plugin]
        name = "fiction"
        author = "chris"
        marker = "fiction"
        [auth]
        mode = "oauth"
        [auth.rbac]
        [auth.rbac.roles]
        owner = { layers = ["*"] }
        [auth.rbac.principals]
        agent = "owner"
    '''))
    monkeypatch.setenv("BRAIN_PATH", str(brain))
    monkeypatch.setenv("BRAIN_AUTH_ISSUER", "https://brain.example")
    monkeypatch.setenv("BRAIN_AUTH_AUDIENCE", "https://brain.example/mcp")
    monkeypatch.setenv("BRAIN_AUTH_PRINCIPAL_TOKENS", json.dumps({"agent": "s3cret"}))
    import importlib, brain_mcp_server
    importlib.reload(brain_mcp_server)
    from starlette.testclient import TestClient
    app = brain_mcp_server._build_http_app(brain_mcp_server._build_server())
    with TestClient(app) as client:
        r = client.post("/mcp", json={})
        assert r.status_code == 401


def test_call_tool_sees_current_principal(monkeypatch):
    """The dispatch boundary can read the request's principal (Plan E hook point)."""
    import importlib, brain_mcp_server
    importlib.reload(brain_mcp_server)
    from lib.auth import Principal
    captured = {}

    # Monkeypatch a tool handler to record the principal visible at dispatch.
    def fake_templates(brain_path):
        captured["principal"] = brain_mcp_server.current_principal.get()
        return "ok"

    monkeypatch.setattr(brain_mcp_server, "handle_brain_templates", fake_templates)
    server = brain_mcp_server._build_server()

    import asyncio
    p = Principal(id="agent", role="owner", read_layers=("*",), write_layers=("*",), kind="static")
    tok = brain_mcp_server.current_principal.set(p)
    try:
        result = asyncio.run(brain_mcp_server._invoke_tool("brain_templates", {}))
    finally:
        brain_mcp_server.current_principal.reset(tok)
    assert captured["principal"].id == "agent"
    assert "ok" in result


def test_well_known_prefix_bypass_is_closed(monkeypatch, tmp_path):
    """A path that only *prefixes* /.well-known must NOT bypass auth in oauth mode."""
    import json, textwrap
    brain = tmp_path / "brain"
    (brain / ".ai").mkdir(parents=True)
    pdir = brain / ".brain"; pdir.mkdir()
    (pdir / "profile.toml").write_text(textwrap.dedent('''\
        name = "fenn"
        folders = ["canon"]
        [plugin]
        name = "fiction"
        author = "chris"
        marker = "fiction"
        [auth]
        mode = "oauth"
        [auth.rbac]
        [auth.rbac.roles]
        owner = { layers = ["*"] }
        [auth.rbac.principals]
        agent = "owner"
    '''))
    monkeypatch.setenv("BRAIN_PATH", str(brain))
    monkeypatch.setenv("BRAIN_AUTH_ISSUER", "https://brain.example")
    monkeypatch.setenv("BRAIN_AUTH_AUDIENCE", "https://brain.example/mcp")
    monkeypatch.setenv("BRAIN_AUTH_PRINCIPAL_TOKENS", json.dumps({"agent": "s3cret"}))
    import importlib, brain_mcp_server
    importlib.reload(brain_mcp_server)
    from starlette.testclient import TestClient
    app = brain_mcp_server._build_http_app(brain_mcp_server._build_server())
    with TestClient(app) as client:
        # a path that only *prefixes* /.well-known must NOT bypass auth in oauth mode
        r = client.get("/.well-known-evil/mcp")
        assert r.status_code == 401
