import os
import importlib
import pytest
from lib.config import Config


def test_defaults(monkeypatch):
    monkeypatch.delenv("EMBEDDING_BASE_URL", raising=False)
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    monkeypatch.delenv("CHAT_BASE_URL", raising=False)
    monkeypatch.delenv("CHAT_MODEL", raising=False)
    monkeypatch.delenv("BRAIN_PATH", raising=False)
    cfg = Config()
    assert cfg.embedding_base_url == "http://model-runner.docker.internal/engines/llama.cpp/v1"
    assert cfg.embedding_model == "mxbai-embed-large"
    assert cfg.brain_path == "/brain"


def test_overrides_from_env(monkeypatch):
    monkeypatch.setenv("EMBEDDING_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("EMBEDDING_MODEL", "nomic-embed-text")
    monkeypatch.setenv("BRAIN_PATH", "/tmp/testbrain")
    cfg = Config()
    assert cfg.embedding_base_url == "http://localhost:11434/v1"
    assert cfg.embedding_model == "nomic-embed-text"
    assert cfg.brain_path == "/tmp/testbrain"


def test_config_cors_defaults_to_localhost(monkeypatch):
    monkeypatch.delenv("BRAIN_API_CORS_ORIGINS", raising=False)
    import lib.config
    importlib.reload(lib.config)
    cfg = lib.config.Config()
    assert cfg.cors_origins == ["http://localhost:7779", "http://127.0.0.1:7779"]


def test_config_cors_from_env(monkeypatch):
    monkeypatch.setenv("BRAIN_API_CORS_ORIGINS", "http://localhost:3000,http://localhost:8080")
    import lib.config
    importlib.reload(lib.config)
    cfg = lib.config.Config()
    assert cfg.cors_origins == ["http://localhost:3000", "http://localhost:8080"]
