#!/usr/bin/env python3
"""brain-mcp-server: MCP server exposing brain tools to Claude Code."""
import os
import subprocess
from typing import Optional

import numpy as np

from lib.config import Config
from lib.db import get_chunk_embeddings, search_chunks
from lib.embeddings import get_embedding

_cfg = Config()

_PREVIEW_LENGTH = 400      # chars of content shown per result in MCP responses
_CANDIDATE_MULTIPLIER = 10  # how many raw candidates to fetch before deduping by file in brain_related


def _check_within_brain(path: str, brain_path: str, label: str = "path") -> Optional[str]:
    """Return an error string if path is outside brain_path, else None."""
    brain_real = os.path.realpath(brain_path)
    try:
        target_real = os.path.realpath(os.path.abspath(path))
    except Exception:
        return f"Invalid {label}: {path}"
    if not (target_real == brain_real or target_real.startswith(brain_real + "/")):
        return f"Error: {label} is outside the brain: {path}"
    return None


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
            r.get("content", "")[:_PREVIEW_LENGTH].strip(),
            "",
            "---",
            "",
        ]
    return "\n".join(lines)


def handle_brain_search(query: str, limit: int, db_path: str) -> str:
    embedding = get_embedding(query)
    results = search_chunks(db_path, embedding, limit=limit)
    return _format_results(results)


def handle_brain_related(filepath: str, limit: int, db_path: str, brain_path: str) -> str:
    full_path = filepath if filepath.startswith("/") else f"{brain_path}/{filepath}"
    vectors = get_chunk_embeddings(db_path, full_path)
    if not vectors:
        vectors = get_chunk_embeddings(db_path, filepath)
    if not vectors:
        return f"No embeddings found for {filepath}. Has it been indexed?"
    mean_vec = list(np.mean(vectors, axis=0))
    # Fetch more candidates than needed so deduplication by file still yields `limit` results
    candidates = search_chunks(db_path, mean_vec, limit=limit * _CANDIDATE_MULTIPLIER)
    seen = set()
    deduped = []
    for r in candidates:
        fp = r["filepath"]
        if fp in (full_path, filepath) or fp in seen:
            continue
        seen.add(fp)
        deduped.append(r)
        if len(deduped) == limit:
            break
    return _format_results(deduped)


def handle_brain_query(
    tag: Optional[str], status: Optional[str], note_type: Optional[str], brain_path: str
) -> str:
    cmd = ["zk", "list", "--quiet", "--format", "{{path}}"]
    if tag:
        cmd += ["--tag", tag]
    if status:
        cmd += ["--match", f"status:{status}"]
    if note_type:
        cmd += ["--match", f"type:{note_type}"]
    try:
        result = subprocess.run(cmd, cwd=brain_path, capture_output=True, text=True)
    except FileNotFoundError:
        return "zk is not installed or not on PATH. Is the container running?"
    if result.returncode != 0:
        return f"zk list failed: {result.stderr}"
    files = [f.strip() for f in result.stdout.splitlines() if f.strip()]
    if not files:
        return "No notes matched the query."
    return "\n".join(files)


def handle_brain_write(filepath: str, content: str, brain_path: str) -> str:
    """Write content to a file inside the brain."""
    full_path = filepath if filepath.startswith("/") else os.path.join(brain_path, filepath)
    if err := _check_within_brain(full_path, brain_path):
        return err
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    try:
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Written: {full_path}"
    except Exception as e:
        return f"Error writing {filepath}: {e}"


def handle_brain_templates(brain_path: str) -> str:
    """List available zk templates."""
    templates_dir = os.path.join(brain_path, ".zk", "templates")
    if not os.path.isdir(templates_dir):
        return "No templates directory found. Has the brain been initialised with brain-init?"
    names = sorted(
        os.path.splitext(f)[0]
        for f in os.listdir(templates_dir)
        if f.endswith(".md")
    )
    if not names:
        return "No templates found."
    return "Available templates (use these exact names with brain_create):\n" + "\n".join(f"  {n}" for n in names)


def handle_brain_read(filepath: str, brain_path: str) -> str:
    """Read a file from the brain and return its full content."""
    full_path = filepath if filepath.startswith("/") else os.path.join(brain_path, filepath)
    if err := _check_within_brain(full_path, brain_path):
        return err
    if not os.path.isfile(full_path):
        return f"File not found: {filepath}"
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error reading {filepath}: {e}"


def handle_brain_create(template: str, title: str, brain_path: str, directory: Optional[str] = None) -> str:
    # zk requires the .md extension on template names
    if not template.endswith(".md"):
        template = template + ".md"
    # Resolve target directory — default to brain root
    if directory:
        target_dir = directory if directory.startswith("/") else os.path.join(brain_path, directory)
        if err := _check_within_brain(target_dir, brain_path, label="directory"):
            return err
        os.makedirs(target_dir, exist_ok=True)
    else:
        target_dir = brain_path
    try:
        result = subprocess.run(
            ["zk", "new", "--working-dir", target_dir, "--template", template, "--title", title, "--print-path"],
            cwd=brain_path, capture_output=True, text=True
        )
    except FileNotFoundError:
        return "zk is not installed or not on PATH. Is the container running?"
    if result.returncode != 0:
        available = handle_brain_templates(brain_path)
        return f"zk new failed: {result.stderr.strip()}\n\n{available}"
    return result.stdout.strip()


def main():
    # Import MCP server components only when starting the server
    # so handler functions remain importable without the MCP runtime
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
    import asyncio

    server = Server("brain-mcp-server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="brain_search",
                description="Semantic search across brain notes. Returns matched content with full frontmatter (type, status, created, tags) for provenance.",
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
                name="brain_query",
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
                name="brain_create",
                description="Create a new note from a template. Returns the filepath — then use brain_write to populate it. Use brain_query first to find the right directory.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "template": {"type": "string", "description": "Template name from brain_templates"},
                        "title": {"type": "string"},
                        "directory": {"type": "string", "description": "Optional subdirectory within the brain (e.g. 'Projects/my-project/context'). Created if it doesn't exist."},
                    },
                    "required": ["template", "title"],
                },
            ),
            Tool(
                name="brain_related",
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
            Tool(
                name="brain_write",
                description="Write content to a note inside the brain. Use after brain_create to populate the note, or to update an existing note.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "filepath": {"type": "string", "description": "Path as returned by brain_create or brain_search"},
                        "content": {"type": "string", "description": "Full file content to write (overwrites existing content)"},
                    },
                    "required": ["filepath", "content"],
                },
            ),
            Tool(
                name="brain_templates",
                description="List available note templates. Call this before brain_create to know which template names are valid.",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="brain_read",
                description="Read the full content of a note by filepath. Use when you need the complete document after finding it via brain_search or brain_query.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "filepath": {"type": "string", "description": "Path as returned by brain_search or brain_query (e.g. /brain/Projects/...)"},
                    },
                    "required": ["filepath"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        db_path = _cfg.db_path
        brain_path = _cfg.brain_path

        if name == "brain_search":
            text = handle_brain_search(
                query=arguments["query"],
                limit=arguments.get("limit", 5),
                db_path=db_path,
            )
        elif name == "brain_query":
            text = handle_brain_query(
                tag=arguments.get("tag"),
                status=arguments.get("status"),
                note_type=arguments.get("type"),
                brain_path=brain_path,
            )
        elif name == "brain_create":
            text = handle_brain_create(
                template=arguments["template"],
                title=arguments["title"],
                brain_path=brain_path,
                directory=arguments.get("directory"),
            )
        elif name == "brain_related":
            text = handle_brain_related(
                filepath=arguments["filepath"],
                limit=arguments.get("limit", 5),
                db_path=db_path,
                brain_path=brain_path,
            )
        elif name == "brain_write":
            text = handle_brain_write(
                filepath=arguments["filepath"],
                content=arguments["content"],
                brain_path=brain_path,
            )
        elif name == "brain_templates":
            text = handle_brain_templates(brain_path=brain_path)
        elif name == "brain_read":
            text = handle_brain_read(
                filepath=arguments["filepath"],
                brain_path=brain_path,
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
