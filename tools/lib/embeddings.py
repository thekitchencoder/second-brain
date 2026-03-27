import os
import sys

from openai import OpenAI, APIConnectionError, InternalServerError, NotFoundError

from lib.config import Config

_cfg = None
_client = None


class EmbeddingError(RuntimeError):
    """Raised when the embedding service is unavailable or misconfigured."""
    pass


def _get_cfg() -> "Config":
    global _cfg
    if _cfg is None:
        _cfg = Config()
    return _cfg


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            base_url=_get_cfg().embedding_base_url,
            api_key=os.environ.get("OPENAI_API_KEY", "local"),
        )
    return _client


def get_embedding(text: str, max_chars: int = 1500) -> list[float]:
    """Get embedding for text, halving input on token-limit errors until it fits."""
    try:
        response = _get_client().embeddings.create(
            input=text[:max_chars],
            model=_get_cfg().embedding_model,
        )
        return response.data[0].embedding
    except InternalServerError as e:
        if "too large" in str(e) and max_chars > 100:
            print(f"Warning: input too large, retrying with {max_chars // 2} chars", file=sys.stderr)
            return get_embedding(text, max_chars // 2)
        raise
    except NotFoundError:
        raise EmbeddingError(
            f"Embedding model '{_get_cfg().embedding_model}' not found at {_get_cfg().embedding_base_url}. "
            f"Check that the model is loaded and EMBEDDING_MODEL is set correctly."
        )
    except APIConnectionError:
        raise EmbeddingError(
            f"Cannot connect to embedding endpoint {_get_cfg().embedding_base_url}. "
            f"Is Docker Model Runner (or your configured LLM server) running?"
        )
