"""Integration tests for Phase 1 of the co-dependent confabulation roadmap.

Requires:
- Docker running
- kitchencoder/second-brain image built locally (docker build -t kitchencoder/second-brain .)
  OR pulled from Docker Hub
- Docker Model Runner running with an embedding model available

Run with:
    pytest -m integration -v

Skip in unit-test-only mode:
    pytest -m "not integration"
"""
import os
import pytest
from pathlib import Path

FIXTURE_VAULT = Path(__file__).parent / "fixtures" / "vault"
IMAGE = os.environ.get("SECOND_BRAIN_IMAGE", "kitchencoder/second-brain:latest")
EMBEDDING_BASE_URL = os.environ.get(
    "EMBEDDING_BASE_URL",
    "http://model-runner.docker.internal/engines/llama.cpp/v1"
)
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "mxbai-embed-large")


@pytest.fixture(scope="session")
def vault_container():
    """Start the vault container with fixture vault mounted, run vault-index, yield container."""
    from testcontainers.core.container import DockerContainer

    container = (
        DockerContainer(IMAGE)
        .with_command("sleep infinity")
        .with_volume_mapping(str(FIXTURE_VAULT.resolve()), "/vault", "rw")
        .with_env("EMBEDDING_BASE_URL", EMBEDDING_BASE_URL)
        .with_env("EMBEDDING_MODEL", EMBEDDING_MODEL)
        .with_env("VAULT_PATH", "/vault")
    )

    with container:
        # Check embedding model is reachable before spending time indexing
        exit_code, output = container.exec(
            f"python3 -c \""
            f"from openai import OpenAI; "
            f"c = OpenAI(base_url='{EMBEDDING_BASE_URL}', api_key='local'); "
            f"c.embeddings.create(input='test', model='{EMBEDDING_MODEL}')"
            f"\""
        )
        if exit_code != 0:
            pytest.skip(
                f"Embedding model unavailable at {EMBEDDING_BASE_URL} — skipping integration tests"
            )

        # Run full index
        exit_code, output = container.exec("vault-index run")
        assert exit_code == 0, f"vault-index failed:\n{output.decode()}"

        yield container

    # Cleanup: remove the generated embeddings DB from the fixture vault
    db = FIXTURE_VAULT / ".ai" / "embeddings.db"
    if db.exists():
        db.unlink()
    ai_dir = FIXTURE_VAULT / ".ai"
    if ai_dir.exists() and not any(ai_dir.iterdir()):
        ai_dir.rmdir()


def _exec(container, cmd: str) -> str:
    """Run a command in the container and return stdout. Fails test on non-zero exit."""
    exit_code, output = container.exec(cmd)
    assert exit_code == 0, f"Command failed: {cmd}\n{output.decode()}"
    return output.decode()


@pytest.mark.integration
def test_search_returns_confabulation_note_with_frontmatter(vault_container):
    """vault_search('co-dependent confabulation') returns the context note with full frontmatter."""
    result = _exec(
        vault_container,
        "python3 -c \""
        "from vault_mcp_server import handle_vault_search; "
        "from lib.config import Config; "
        "cfg = Config(); "
        "print(handle_vault_search('co-dependent confabulation', 5, cfg.db_path))"
        "\""
    )
    assert "Co-dependent Confabulation" in result
    assert "epistemic-lens" in result
    assert "context-primer" in result
    assert "2026-03-15" in result


@pytest.mark.integration
def test_query_by_tag_returns_epistemic_lens_documents(vault_container):
    """vault_query(tag='epistemic-lens') returns all documents tagged epistemic-lens."""
    result = _exec(
        vault_container,
        "python3 -c \""
        "from vault_mcp_server import handle_vault_query; "
        "print(handle_vault_query(tag='epistemic-lens', status=None, type=None, vault_path='/vault'))"
        "\""
    )
    assert "context-co-dependent-confabulation" in result
    assert "strange-loops" in result


@pytest.mark.integration
def test_related_returns_distinct_files_not_repeated_chunks(vault_container):
    """vault_related returns the cognitive debt summary and strange loops as distinct files."""
    result = _exec(
        vault_container,
        "python3 -c \""
        "from vault_mcp_server import handle_vault_related; "
        "from lib.config import Config; "
        "cfg = Config(); "
        "filepath = '/vault/Projects/confabulation/context-co-dependent-confabulation.md'; "
        "print(handle_vault_related(filepath, 5, cfg.db_path, cfg.vault_path))"
        "\""
    )
    # Each file should appear exactly once
    assert result.count("cognitive-debt-paper-summary") == 1
    assert result.count("strange-loops") == 1


@pytest.mark.integration
def test_templates_not_indexed(vault_container):
    """Files under templates/ must not appear in the index."""
    result = _exec(
        vault_container,
        "python3 -c \""
        "import sqlite3, sqlite_vec; "
        "db = '/vault/.ai/embeddings.db'; "
        "conn = sqlite3.connect(db); "
        "conn.enable_load_extension(True); "
        "sqlite_vec.load(conn); "
        "conn.enable_load_extension(False); "
        "rows = conn.execute(\\\"SELECT COUNT(*) FROM chunks WHERE filepath LIKE '%/templates/%'\\\").fetchone(); "
        "print(rows[0])"
        "\""
    )
    assert result.strip() == "0", f"Expected 0 template chunks, got: {result.strip()}"
