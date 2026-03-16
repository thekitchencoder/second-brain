import pytest
from unittest.mock import patch
from vault_search import format_result, search


@pytest.fixture
def mock_results():
    return [
        {
            "filepath": "projects/test.md",
            "content": "This is matching content.",
            "title": "Test Note",
            "type": "context-primer",
            "status": "current",
            "created": "2026-03-16",
            "tags": ["testing", "foo"],
            "scope": "test-scope",
            "distance": 0.12,
        }
    ]


def test_format_result_includes_key_fields(mock_results):
    output = format_result(mock_results[0])
    assert "Test Note" in output
    assert "projects/test.md" in output
    assert "current" in output
    assert "2026-03-16" in output
    assert "testing" in output
    assert "This is matching content." in output


def test_search_calls_db(mock_results):
    with patch("vault_search.get_embedding", return_value=[0.1] * 1024), \
         patch("vault_search.search_chunks", return_value=mock_results) as mock_db:
        results = search("test query", db_path="/tmp/fake.db", limit=3)
        mock_db.assert_called_once()
        assert len(results) == 1
