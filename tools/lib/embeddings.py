import os
import sys

from openai import OpenAI, APIConnectionError, InternalServerError, NotFoundError

from lib.config import Config

_cfg = Config()
_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            base_url=_cfg.embedding_base_url,
            api_key=os.environ.get("OPENAI_API_KEY", "local"),
        )
    return _client


def get_embedding(text: str, max_chars: int = 1500) -> list[float]:
    """Get embedding for text, halving input on token-limit errors until it fits."""
    try:
        response = _get_client().embeddings.create(
            input=text[:max_chars],
            model=_cfg.embedding_model,
        )
        return response.data[0].embedding
    except InternalServerError as e:
        if "too large" in str(e) and max_chars > 100:
            print(f"Warning: input too large, retrying with {max_chars // 2} chars", file=sys.stderr)
            return get_embedding(text, max_chars // 2)
        raise
    except NotFoundError:
        print(f"\nError: embedding model '{_cfg.embedding_model}' not found.", file=sys.stderr)
        print(f"  Endpoint: {_cfg.embedding_base_url}", file=sys.stderr)
        print(f"  Check that the model is loaded and EMBEDDING_MODEL is set correctly.", file=sys.stderr)
        sys.exit(1)
    except APIConnectionError:
        print(f"\nError: cannot connect to embedding endpoint.", file=sys.stderr)
        print(f"  Endpoint: {_cfg.embedding_base_url}", file=sys.stderr)
        print(f"  Is Docker Model Runner (or your configured LLM server) running?", file=sys.stderr)
        sys.exit(1)
