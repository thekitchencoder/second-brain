# tests/test_brain_mcp_server.py
import sys
import textwrap
import pytest
from unittest.mock import patch, MagicMock

# Stub out native-only deps
if "sqlite_vec" not in sys.modules:
    sys.modules["sqlite_vec"] = MagicMock()
if "openai" not in sys.modules:
    sys.modules["openai"] = MagicMock()

from lib.brain import handle_brain_search, handle_brain_query, handle_brain_related


@pytest.fixture
def mock_search_results():
    return [
        {
            "filepath": "atlas/test.md",
            "content": "Some content.",
            "title": "Test",
            "type": "note",
            "status": "current",
            "created": "2026-03-16",
            "tags": ["foo"],
            "scope": None,
            "distance": 0.1,
        }
    ]


def test_handle_brain_search_returns_text(mock_search_results):
    with patch("lib.embeddings.get_embedding", return_value=[0.1] * 1024), \
         patch("lib.db.search_chunks", return_value=mock_search_results):
        result = handle_brain_search(query="test", limit=5, db_path="/tmp/fake.db")
    assert "Test" in result
    assert "atlas/test.md" in result
    assert "current" in result


def test_handle_brain_search_no_results():
    with patch("lib.embeddings.get_embedding", return_value=[0.1] * 1024), \
         patch("lib.db.search_chunks", return_value=[]):
        result = handle_brain_search(query="nothing", limit=5, db_path="/tmp/fake.db")
    assert "No results" in result


def test_handle_brain_related_returns_text(mock_search_results):
    with patch("lib.db.get_chunk_embeddings", return_value=[[0.1] * 1024]), \
         patch("lib.db.search_chunks", return_value=mock_search_results):
        result = handle_brain_related(
            filepath="notes/other.md", limit=5,
            db_path="/tmp/fake.db", brain_path="/brain"
        )
    assert "Test" in result


def test_handle_brain_related_no_embeddings():
    with patch("lib.db.get_chunk_embeddings", return_value=[]):
        result = handle_brain_related(
            filepath="notes/missing.md", limit=5,
            db_path="/tmp/fake.db", brain_path="/brain"
        )
    assert "not indexed" in result.lower() or "no embeddings" in result.lower()


def test_handle_brain_query_runs_zk(tmp_path):
    with patch("lib.brain.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            stdout="notes/foo.md\nnotes/bar.md\n",
            returncode=0
        )
        result = handle_brain_query(str(tmp_path), tag="testing")
    assert "foo.md" in result
    assert "bar.md" in result


def _make_brain_with_custom_field_profile(tmp_path):
    """A brain whose .brain/profile.toml promotes a custom 'layer' field."""
    brain_dir = tmp_path / "brain"
    (brain_dir / ".brain").mkdir(parents=True)
    (brain_dir / ".brain" / "profile.toml").write_text(textwrap.dedent('''
        name = "custom"
        folders = ["Zone"]
        [plugin]
        name = "custom-brain"
        author = "kitchencoder"
        marker = "custom"
        [fields.layer]
        kind = "scalar"
        label = "layer"
        query_desc = "Filter by layer (deep-canon, surface)."
        [skills]
        global = []
        vault = []
        [auth]
        mode = "none"
    '''))
    return brain_dir


@pytest.fixture
def mcp_module_with_profile(monkeypatch, tmp_path):
    """Import brain_mcp_server with BRAIN_PATH pointed at a brain whose profile
    promotes a custom 'layer' field, re-loading modules so the module-level
    Config() picks up the patched env var."""
    import importlib
    import sys as _sys

    brain_dir = _make_brain_with_custom_field_profile(tmp_path)
    monkeypatch.setenv("BRAIN_PATH", str(brain_dir))

    import lib.config
    importlib.reload(lib.config)

    if "brain_mcp_server" in _sys.modules:
        importlib.reload(_sys.modules["brain_mcp_server"])
        mod = _sys.modules["brain_mcp_server"]
    else:
        import brain_mcp_server as mod

    mod._cfg = lib.config.Config()
    return mod


def _list_tools(server):
    """Invoke the registered ListToolsRequest handler and return list[Tool]."""
    import asyncio
    import mcp.types as types

    handler = server.request_handlers[types.ListToolsRequest]
    result = asyncio.run(handler(types.ListToolsRequest(method="tools/list")))
    return result.root.tools


def test_brain_query_schema_has_profile_fields(mcp_module_with_profile):
    server = mcp_module_with_profile._build_server()
    tools = _list_tools(server)
    brain_query_tool = next(t for t in tools if t.name == "brain_query")
    props = brain_query_tool.inputSchema["properties"]

    assert "layer" in props
    assert "where" in props
    assert props["where"]["type"] == "object"
    # Stable params still present
    assert "tag" in props and "created_after" in props and "created_before" in props
    # Old hardcoded ACE fields not baked in unless the profile declares them
    assert "intensity" not in props


def test_brain_query_schema_description_from_labels(mcp_module_with_profile):
    server = mcp_module_with_profile._build_server()
    tools = _list_tools(server)
    brain_query_tool = next(t for t in tools if t.name == "brain_query")

    assert "layer" in brain_query_tool.description
    assert "intensity" not in brain_query_tool.description
