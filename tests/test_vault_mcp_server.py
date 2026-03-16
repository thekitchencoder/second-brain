# tests/test_vault_mcp_server.py
import pytest
from unittest.mock import patch, MagicMock
from vault_mcp_server import handle_vault_search, handle_vault_query, handle_vault_related


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


def test_handle_vault_search_returns_text(mock_search_results):
    with patch("vault_mcp_server.get_embedding", return_value=[0.1] * 1024), \
         patch("vault_mcp_server.search_chunks", return_value=mock_search_results):
        result = handle_vault_search(query="test", limit=5, db_path="/tmp/fake.db")
    assert "Test" in result
    assert "atlas/test.md" in result
    assert "current" in result


def test_handle_vault_search_no_results():
    with patch("vault_mcp_server.get_embedding", return_value=[0.1] * 1024), \
         patch("vault_mcp_server.search_chunks", return_value=[]):
        result = handle_vault_search(query="nothing", limit=5, db_path="/tmp/fake.db")
    assert "No results" in result


def test_handle_vault_related_returns_text(mock_search_results):
    with patch("vault_mcp_server.get_chunk_embeddings", return_value=[[0.1] * 1024]), \
         patch("vault_mcp_server.search_chunks", return_value=mock_search_results):
        result = handle_vault_related(
            filepath="notes/other.md", limit=5,
            db_path="/tmp/fake.db", vault_path="/vault"
        )
    assert "Test" in result


def test_handle_vault_related_no_embeddings():
    with patch("vault_mcp_server.get_chunk_embeddings", return_value=[]):
        result = handle_vault_related(
            filepath="notes/missing.md", limit=5,
            db_path="/tmp/fake.db", vault_path="/vault"
        )
    assert "not indexed" in result.lower() or "no embeddings" in result.lower()


def test_handle_vault_query_runs_zk(tmp_path):
    with patch("vault_mcp_server.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            stdout="notes/foo.md\nnotes/bar.md\n",
            returncode=0
        )
        result = handle_vault_query(tag="testing", status=None, type=None, vault_path=str(tmp_path))
    assert "foo.md" in result
    assert "bar.md" in result
