import os


class Config:
    def __init__(self):
        self.embedding_base_url = os.environ.get(
            "EMBEDDING_BASE_URL",
            "http://model-runner.docker.internal/engines/llama.cpp/v1"
        )
        self.embedding_model = os.environ.get("EMBEDDING_MODEL", "mxbai-embed-large")
        self.brain_path = os.environ.get("BRAIN_PATH", "/brain")

    @property
    def db_path(self):
        return f"{self.brain_path}/.ai/embeddings.db"

    @property
    def cors_origins(self) -> list:
        raw = os.environ.get("BRAIN_API_CORS_ORIGINS", "")
        if raw:
            return [o.strip() for o in raw.split(",") if o.strip()]
        return ["http://localhost:7779", "http://127.0.0.1:7779"]
