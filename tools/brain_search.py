#!/usr/bin/env python3
"""brain-search: semantic search across the brain."""
import json

from lib.config import Config
from lib.db import search_chunks
from lib.embeddings import get_embedding

_cfg = Config()


def format_result(result: dict) -> str:
    tags = ", ".join(result.get("tags") or [])
    lines = [
        f"## {result.get('title') or result['filepath']}",
        f"  File:    {result['filepath']}",
        f"  Type:    {result.get('type', '-')}",
        f"  Status:  {result.get('status', '-')}",
        f"  Created: {result.get('created', '-')}",
        f"  Tags:    {tags or '-'}",
        f"  Score:   {result.get('distance', 0.0):.4f}",
        "",
        f"  {result['content'][:300].strip()}",
        "",
    ]
    return "\n".join(lines)


def search(query: str, db_path: str, limit: int = 5) -> list[dict]:
    embedding = get_embedding(query)
    return search_chunks(db_path, embedding, limit=limit)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Semantic search across brain")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--limit", type=int, default=5, help="Number of results")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    results = search(args.query, db_path=_cfg.db_path, limit=args.limit)

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        if not results:
            print("No results found.")
        for r in results:
            print(format_result(r))


if __name__ == "__main__":
    main()
