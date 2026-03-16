# tests/test_brain_mcp_server.py
import pytest
from unittest.mock import patch, MagicMock
from brain_mcp_server import handle_brain_search, handle_brain_query, handle_brain_related


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
    with patch("brain_mcp_server.get_embedding", return_value=[0.1] * 1024), \
         patch("brain_mcp_server.search_chunks", return_value=mock_search_results):
        result = handle_brain_search(query="test", limit=5, db_path="/tmp/fake.db")
    assert "Test" in result
    assert "atlas/test.md" in result
    assert "current" in result


def test_handle_brain_search_no_results():
    with patch("brain_mcp_server.get_embedding", return_value=[0.1] * 1024), \
         patch("brain_mcp_server.search_chunks", return_value=[]):
        result = handle_brain_search(query="nothing", limit=5, db_path="/tmp/fake.db")
    assert "No results" in result


def test_handle_brain_related_returns_text(mock_search_results):
    with patch("brain_mcp_server.get_chunk_embeddings", return_value=[[0.1] * 1024]), \
         patch("brain_mcp_server.search_chunks", return_value=mock_search_results):
        result = handle_brain_related(
            filepath="notes/other.md", limit=5,
            db_path="/tmp/fake.db", brain_path="/brain"
        )
    assert "Test" in result


def test_handle_brain_related_no_embeddings():
    with patch("brain_mcp_server.get_chunk_embeddings", return_value=[]):
        result = handle_brain_related(
            filepath="notes/missing.md", limit=5,
            db_path="/tmp/fake.db", brain_path="/brain"
        )
    assert "not indexed" in result.lower() or "no embeddings" in result.lower()


def test_handle_brain_query_runs_zk(tmp_path):
    with patch("brain_mcp_server.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            stdout="notes/foo.md\nnotes/bar.md\n",
            returncode=0
        )
        result = handle_brain_query(tag="testing", status=None, type=None, brain_path=str(tmp_path))
    assert "foo.md" in result
    assert "bar.md" in result
