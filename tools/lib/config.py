import os


class Config:
    def __init__(self):
        self.embedding_base_url = os.environ.get(
            "EMBEDDING_BASE_URL",
            "http://model-runner.docker.internal/engines/llama.cpp/v1"
        )
        self.embedding_model = os.environ.get("EMBEDDING_MODEL", "mxbai-embed-large")
        self.chat_base_url = os.environ.get(
            "CHAT_BASE_URL",
            "http://model-runner.docker.internal/engines/llama.cpp/v1"
        )
        self.chat_model = os.environ.get("CHAT_MODEL", "llama3.2")
        self.brain_path = os.environ.get("BRAIN_PATH", "/brain")

    @property
    def db_path(self):
        return f"{self.brain_path}/.ai/embeddings.db"
