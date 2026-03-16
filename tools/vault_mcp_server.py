#!/usr/bin/env python3
"""vault-mcp-server: MCP server exposing vault tools to Claude Code."""
import os
import subprocess
import sys
from typing import Optional

import numpy as np
from openai import OpenAI

from lib.config import Config
from lib.db import get_chunk_embeddings, search_chunks

_cfg = Config()
_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            base_url=_cfg.embedding_base_url,
            api_key=os.environ.get("OPENAI_API_KEY", "local")
        )
    return _client


def get_embedding(text: str) -> list[float]:
    response = _get_client().embeddings.create(
        input=text, model=_cfg.embedding_model
    )
    return response.data[0].embedding


def _format_results(results: list[dict]) -> str:
    if not results:
        return "No results found."
    lines = []
    for r in results:
        tags = ", ".join(r.get("tags") or [])
        lines += [
            f"### {r.get('title') or r['filepath']}",
            f"- **File:** {r['filepath']}",
            f"- **Type:** {r.get('type', '-')}  **Status:** {r.get('status', '-')}",
            f"- **Created:** {r.get('created', '-')}  **Tags:** {tags or '-'}",
            "",
            r.get("content", "")[:400].strip(),
            "",
            "---",
            "",
        ]
    return "\n".join(lines)


def handle_vault_search(query: str, limit: int, db_path: str) -> str:
    embedding = get_embedding(query)
    results = search_chunks(db_path, embedding, limit=limit)
    return _format_results(results)


def handle_vault_related(filepath: str, limit: int, db_path: str, vault_path: str) -> str:
    full_path = filepath if filepath.startswith("/") else f"{vault_path}/{filepath}"
    vectors = get_chunk_embeddings(db_path, full_path)
    if not vectors:
        vectors = get_chunk_embeddings(db_path, filepath)
    if not vectors:
        return f"No embeddings found for {filepath}. Has it been indexed?"
    mean_vec = list(np.mean(vectors, axis=0))
    candidates = search_chunks(db_path, mean_vec, limit=limit + 1)
    filtered = [r for r in candidates if r["filepath"] != full_path and r["filepath"] != filepath]
    return _format_results(filtered[:limit])


def handle_vault_query(
    tag: Optional[str], status: Optional[str], type: Optional[str], vault_path: str
) -> str:
    cmd = ["zk", "list", "--quiet", "--format", "{{path}}"]
    if tag:
        cmd += ["--tag", tag]
    if status:
        cmd += ["--match", f"status:{status}"]
    result = subprocess.run(cmd, cwd=vault_path, capture_output=True, text=True)
    if result.returncode != 0:
        return f"zk list failed: {result.stderr}"
    files = [f.strip() for f in result.stdout.splitlines() if f.strip()]
    if not files:
        return "No notes matched the query."
    return "\n".join(files)


def handle_vault_create(template: str, title: str, vault_path: str) -> str:
    result = subprocess.run(
        ["zk", "new", "--template", template, "--title", title],
        cwd=vault_path, capture_output=True, text=True
    )
    if result.returncode != 0:
        return f"zk new failed: {result.stderr}"
    return result.stdout.strip()


def main():
    # Import MCP server components only when starting the server
    # so handler functions remain importable without the MCP runtime
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
    import asyncio

    server = Server("vault")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="vault_search",
                description="Semantic search across vault notes. Returns matched content with full frontmatter (type, status, created, tags) for provenance.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "limit": {"type": "integer", "default": 5},
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="vault_query",
                description="Structured metadata query using zk. Filter notes by tag, status, or type.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "tag": {"type": "string"},
                        "status": {"type": "string"},
                        "type": {"type": "string"},
                    },
                },
            ),
            Tool(
                name="vault_create",
                description="Create a new note from a template.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "template": {"type": "string"},
                        "title": {"type": "string"},
                    },
                    "required": ["template", "title"],
                },
            ),
            Tool(
                name="vault_related",
                description="Find notes semantically related to a given file.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "filepath": {"type": "string"},
                        "limit": {"type": "integer", "default": 5},
                    },
                    "required": ["filepath"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        db_path = _cfg.db_path
        vault_path = _cfg.vault_path

        if name == "vault_search":
            text = handle_vault_search(
                query=arguments["query"],
                limit=arguments.get("limit", 5),
                db_path=db_path,
            )
        elif name == "vault_query":
            text = handle_vault_query(
                tag=arguments.get("tag"),
                status=arguments.get("status"),
                type=arguments.get("type"),
                vault_path=vault_path,
            )
        elif name == "vault_create":
            text = handle_vault_create(
                template=arguments["template"],
                title=arguments["title"],
                vault_path=vault_path,
            )
        elif name == "vault_related":
            text = handle_vault_related(
                filepath=arguments["filepath"],
                limit=arguments.get("limit", 5),
                db_path=db_path,
                vault_path=vault_path,
            )
        else:
            text = f"Unknown tool: {name}"

        return [TextContent(type="text", text=text)]

    async def run():
        async with stdio_server() as streams:
            await server.run(streams[0], streams[1], server.create_initialization_options())

    asyncio.run(run())


if __name__ == "__main__":
    main()
