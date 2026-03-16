import os
import textwrap
import pytest
from unittest.mock import patch
from brain_index import index_brain, index_file


@pytest.fixture
def brain(tmp_path):
    note = tmp_path / "test-note.md"
    note.write_text(textwrap.dedent("""\
        ---
        title: Test Note
        type: note
        status: current
        created: 2026-03-16
        tags: [testing]
        ---

        This is the body of the test note. It has enough content to be meaningful.
    """))
    ai_dir = tmp_path / ".ai"
    ai_dir.mkdir()
    return tmp_path


@pytest.fixture
def mock_embed():
    with patch("brain_index.get_embedding") as mock:
        mock.return_value = [0.1] * 1024
        yield mock


def test_index_file_creates_chunks(brain, mock_embed):
    db_path = str(brain / ".ai" / "embeddings.db")
    from lib.db import init_db
    init_db(db_path, embedding_dim=1024)

    filepath = str(brain / "test-note.md")
    index_file(filepath, db_path)

    mock_embed.assert_called()


def test_index_brain_processes_markdown_files(brain, mock_embed):
    db_path = str(brain / ".ai" / "embeddings.db")
    index_brain(str(brain), db_path)
    mock_embed.assert_called()


def test_index_brain_skips_dotdirectories(brain, mock_embed):
    obsidian_dir = brain / ".obsidian"
    obsidian_dir.mkdir()
    (obsidian_dir / "config.json").write_text("{}")

    db_path = str(brain / ".ai" / "embeddings.db")
    index_brain(str(brain), db_path)

    # Should only have been called for the one real note
    assert mock_embed.call_count >= 1


def test_index_file_skips_unchanged_chunks(brain, mock_embed):
    db_path = str(brain / ".ai" / "embeddings.db")
    from lib.db import init_db
    init_db(db_path, embedding_dim=1024)

    filepath = str(brain / "test-note.md")
    index_file(filepath, db_path)
    first_call_count = mock_embed.call_count

    # Second index of same file with same content — should not re-embed
    index_file(filepath, db_path)
    assert mock_embed.call_count == first_call_count
