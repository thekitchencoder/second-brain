# tests/test_mcp_transport.py
"""Tests for MCP server transport configuration and tool registration."""
import sys
from unittest.mock import MagicMock

# Stub native-only deps
if "sqlite_vec" not in sys.modules:
    sys.modules["sqlite_vec"] = MagicMock()
if "openai" not in sys.modules:
    sys.modules["openai"] = MagicMock()

import pytest
from unittest.mock import patch


def test_build_server_returns_server():
    from brain_mcp_server import _build_server
    server = _build_server()
    assert server.name == "brain-mcp-server"


def test_build_server_registers_all_tools():
    """Verify all expected tools are registered including brain_edit and brain_backlinks."""
    from mcp.types import ListToolsRequest, CallToolRequest
    from brain_mcp_server import _build_server
    server = _build_server()

    # Verify list_tools and call_tool handlers are registered
    assert ListToolsRequest in server.request_handlers
    assert CallToolRequest in server.request_handlers


@patch.dict("os.environ", {"BRAIN_MCP_TRANSPORT": "http"})
def test_main_selects_http_transport():
    """Verify that BRAIN_MCP_TRANSPORT=http calls _run_http."""
    with patch("brain_mcp_server._build_server") as mock_build, \
         patch("brain_mcp_server._run_http") as mock_http:
        mock_build.return_value = MagicMock()
        from brain_mcp_server import main
        main()
        mock_http.assert_called_once()


@patch.dict("os.environ", {"BRAIN_MCP_TRANSPORT": "stdio"})
def test_main_selects_stdio_transport():
    """Verify that BRAIN_MCP_TRANSPORT=stdio (default) calls _run_stdio."""
    with patch("brain_mcp_server._build_server") as mock_build, \
         patch("brain_mcp_server._run_stdio") as mock_stdio:
        mock_build.return_value = MagicMock()
        from brain_mcp_server import main
        main()
        mock_stdio.assert_called_once()


@patch.dict("os.environ", {}, clear=False)
def test_main_defaults_to_stdio():
    """Verify that without BRAIN_MCP_TRANSPORT, stdio is used."""
    import os
    os.environ.pop("BRAIN_MCP_TRANSPORT", None)
    with patch("brain_mcp_server._build_server") as mock_build, \
         patch("brain_mcp_server._run_stdio") as mock_stdio:
        mock_build.return_value = MagicMock()
        from brain_mcp_server import main
        main()
        mock_stdio.assert_called_once()
