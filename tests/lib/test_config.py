import os
import pytest
from lib.config import Config


def test_defaults():
    cfg = Config()
    assert cfg.embedding_base_url == "http://model-runner.docker.internal/engines/llama.cpp/v1"
    assert cfg.embedding_model == "mxbai-embed-large"
    assert cfg.embedding_dim == 1024
    assert cfg.vault_path == "/vault"


def test_overrides_from_env(monkeypatch):
    monkeypatch.setenv("EMBEDDING_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("EMBEDDING_MODEL", "nomic-embed-text")
    monkeypatch.setenv("EMBEDDING_DIM", "768")
    monkeypatch.setenv("VAULT_PATH", "/tmp/testvault")
    cfg = Config()
    assert cfg.embedding_base_url == "http://localhost:11434/v1"
    assert cfg.embedding_model == "nomic-embed-text"
    assert cfg.embedding_dim == 768
    assert cfg.vault_path == "/tmp/testvault"
