#!/usr/bin/env python3
"""brain-mcp-server: MCP server exposing brain tools to Claude Code.

Supports two transports selected via BRAIN_MCP_TRANSPORT env var:
  - stdio  (default) — standard MCP stdio transport
  - http   — Streamable HTTP transport on BRAIN_MCP_HOST:BRAIN_MCP_PORT
"""
import os
from contextvars import ContextVar

from lib.config import Config
from lib.auth import resolve_principal, AuthSettings, OWNER, ANONYMOUS
from lib.policy import get_policy_provider
from lib.brain import (
    _check_within_brain,
    _format_results,
    handle_brain_search,
    handle_brain_related,
    handle_brain_query,
    handle_brain_write,
    handle_brain_read,
    handle_brain_templates,
    handle_brain_create,
    handle_brain_edit,
    handle_brain_backlinks,
    handle_brain_trash,
    handle_brain_restore,
)

_cfg = Config()

# Fail closed: default to the deny sentinel, NOT OWNER. OWNER is granted only by
# an explicit decision — the HTTP middleware (per validated request) or the stdio
# operator channel (below). Plan E reads this var; a fail-open default here would
# silently grant full visibility on any path the middleware didn't cover.
current_principal: ContextVar = ContextVar("current_principal", default=ANONYMOUS)
_auth_settings = AuthSettings.from_env()
_policy = get_policy_provider(_cfg)


def _brain_query_schema(profile):
    """Build the brain_query tool description + inputSchema from profile.fields."""
    props = {
        "tag": {"type": "string"},
        "created_after": {"type": "string", "description": "Include notes created on or after this date (YYYY-MM-DD)."},
        "created_before": {"type": "string", "description": "Include notes created on or before this date (YYYY-MM-DD)."},
        "where": {"type": "object", "description": "Filter any frontmatter key: {field: value}. Values must be slug-like (letters, digits, -, _)."},
    }
    for f in profile.fields:
        props[f.name] = {"type": "string", "description": f.query_desc or f.label}
    labels = ", ".join(f.label for f in profile.fields)
    desc = (
        f"Structured metadata query. Filter notes by tag, {labels}, or date range, "
        f"or any frontmatter key via 'where'. Use '<field>=unset' to find notes missing a field."
    )
    return desc, {"type": "object", "properties": props}


async def _invoke_tool(name: str, arguments: dict) -> str:
    """Dispatch a tool call by name and return its text result.

    Extracted from call_tool so it's unit-testable without the MCP protocol
    machinery, and so Plan E has a single, well-defined hook point.
    """
    principal = current_principal.get()   # Plan E consumes this; Plan D does not filter.
    db_path = _cfg.db_path
    brain_path = _cfg.brain_path

    if name == "brain_search":
        text = handle_brain_search(
            query=arguments["query"],
            limit=arguments.get("limit", 5),
            db_path=db_path,
            principal=principal,
            fields=_cfg.load_profile().fields,
        )
    elif name == "brain_query":
        profile = _cfg.load_profile()
        field_names = {f.name for f in profile.fields}
        field_values = {k: v for k, v in arguments.items() if k in field_names}
        where = {k: str(v) for k, v in (arguments.get("where") or {}).items()}
        text = handle_brain_query(
            brain_path,
            tag=arguments.get("tag"),
            fields=field_values,
            where=where,
            created_after=arguments.get("created_after"),
            created_before=arguments.get("created_before"),
            field_specs=profile.fields,
            principal=principal,
        )
    elif name == "brain_create":
        text = handle_brain_create(
            template=arguments["template"],
            title=arguments["title"],
            brain_path=brain_path,
            directory=arguments.get("directory"),
            principal=principal,
            fields=_cfg.load_profile().fields,
        )
    elif name == "brain_related":
        text = handle_brain_related(
            filepath=arguments["filepath"],
            limit=arguments.get("limit", 5),
            db_path=db_path,
            brain_path=brain_path,
            principal=principal,
            fields=_cfg.load_profile().fields,
        )
    elif name == "brain_write":
        text = handle_brain_write(
            filepath=arguments["filepath"],
            content=arguments["content"],
            brain_path=brain_path,
            principal=principal,
            fields=_cfg.load_profile().fields,
        )
    elif name == "brain_templates":
        text = handle_brain_templates(brain_path=brain_path)
    elif name == "brain_read":
        text = handle_brain_read(
            filepath=arguments["filepath"],
            brain_path=brain_path,
            principal=principal,
            fields=_cfg.load_profile().fields,
        )
    elif name == "brain_edit":
        text = handle_brain_edit(
            filepath=arguments["filepath"],
            op=arguments["op"],
            brain_path=brain_path,
            principal=principal,
            fields=_cfg.load_profile().fields,
            **{k: v for k, v in arguments.items() if k not in ("filepath", "op")},
        )
    elif name == "brain_backlinks":
        text = handle_brain_backlinks(
            filepath=arguments["filepath"],
            brain_path=brain_path,
            principal=principal,
            fields=_cfg.load_profile().fields,
        )
    elif name == "brain_trash":
        text = handle_brain_trash(
            filepath=arguments["filepath"],
            brain_path=brain_path,
            db_path=db_path,
            principal=principal,
            fields=_cfg.load_profile().fields,
        )
    elif name == "brain_restore":
        text = handle_brain_restore(
            trash_path=arguments["trash_path"],
            brain_path=brain_path,
            principal=principal,
            fields=_cfg.load_profile().fields,
        )
    else:
        text = f"Unknown tool: {name}"

    return text


def _build_server():
    """Create and configure the MCP Server with all tool definitions."""
    from mcp.server import Server
    from mcp.types import Tool, TextContent

    server = Server("brain-mcp-server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        profile = _cfg.load_profile()
        brain_query_desc, brain_query_schema = _brain_query_schema(profile)
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
                description=brain_query_desc,
                inputSchema=brain_query_schema,
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
            Tool(
                name="brain_edit",
                description=(
                    "Surgical edit on a note without full-file replacement. "
                    "Supported ops: update_frontmatter, replace_section, append_to_section, "
                    "prepend_to_section, replace_lines, find_replace, insert_wikilink."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "filepath": {"type": "string", "description": "Path to the note to edit"},
                        "op": {
                            "type": "string",
                            "enum": [
                                "update_frontmatter", "replace_section",
                                "append_to_section", "prepend_to_section",
                                "replace_lines", "find_replace", "insert_wikilink",
                            ],
                            "description": "The edit operation to perform",
                        },
                        "frontmatter": {"type": "object", "description": "Key-value pairs to merge (update_frontmatter)"},
                        "heading": {"type": "string", "description": "Section heading (replace/append/prepend_to_section)"},
                        "body": {"type": "string", "description": "New body content for section ops"},
                        "start_line": {"type": "integer", "description": "Start line, 1-indexed inclusive (replace_lines)"},
                        "end_line": {"type": "integer", "description": "End line, exclusive (replace_lines)"},
                        "replacement": {"type": "string", "description": "Replacement text (replace_lines)"},
                        "find": {"type": "string", "description": "Text to find (find_replace)"},
                        "replace": {"type": "string", "description": "Replacement text (find_replace)"},
                        "regex": {"type": "boolean", "default": False, "description": "Use regex (find_replace)"},
                        "count": {"type": "integer", "default": 0, "description": "Max replacements, 0=all (find_replace)"},
                        "target": {"type": "string", "description": "Wikilink target (insert_wikilink)"},
                        "context_heading": {"type": "string", "description": "Section to insert link in (insert_wikilink)"},
                    },
                    "required": ["filepath", "op"],
                },
            ),
            Tool(
                name="brain_backlinks",
                description="Find all notes that contain a [[wikilink]] to the given note.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "filepath": {"type": "string", "description": "Path to the note to find backlinks for"},
                    },
                    "required": ["filepath"],
                },
            ),
            Tool(
                name="brain_trash",
                description=(
                    "Move a note to .trash/ and remove it from the search index immediately. "
                    "Reports any backlinks that will become orphaned. "
                    "Use brain_restore to undo."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "filepath": {
                            "type": "string",
                            "description": "Relative path to the .md file to trash (e.g. 'Cards/foo.md')",
                        },
                    },
                    "required": ["filepath"],
                },
            ),
            Tool(
                name="brain_restore",
                description=(
                    "Restore a note from .trash/ back to its original location. "
                    "The file watcher will re-index it automatically."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "trash_path": {
                            "type": "string",
                            "description": "Path as returned by brain_trash (e.g. '.trash/Cards/foo.md')",
                        },
                    },
                    "required": ["trash_path"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        from mcp.types import TextContent
        text = await _invoke_tool(name, arguments)
        return [TextContent(type="text", text=text)]

    return server


def _run_stdio(server):
    """Run MCP server over stdio — the local operator channel (docker exec).

    Unauthenticated by design (local exec ≈ root). Granted OWNER explicitly.
    A quarantined in-character agent must NEVER be given stdio access — it
    connects only over authenticated HTTP with its principal token.
    """
    import asyncio
    from mcp.server.stdio import stdio_server

    current_principal.set(OWNER)   # explicit operator grant, not a fail-open default

    async def run():
        async with stdio_server() as streams:
            await server.run(streams[0], streams[1], server.create_initialization_options())

    asyncio.run(run())


def _bearer(headers) -> str | None:
    h = headers.get("authorization", "")
    return h[7:].strip() if h.lower().startswith("bearer ") else None


def _build_http_app(server):
    import contextlib
    from collections.abc import AsyncIterator

    from starlette.applications import Starlette
    from starlette.routing import Mount, Route
    from starlette.responses import JSONResponse
    from starlette.middleware.base import BaseHTTPMiddleware
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

    session_manager = StreamableHTTPSessionManager(app=server)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            yield

    def _issuer():
        return os.environ.get("BRAIN_AUTH_ISSUER", "")

    async def protected_resource(request):
        if _policy.get_auth_mode() != "oauth":
            return JSONResponse({"error": "not_found"}, status_code=404)
        return JSONResponse({"resource": os.environ.get("BRAIN_AUTH_AUDIENCE", ""),
                             "authorization_servers": [_issuer()],
                             "bearer_methods_supported": ["header"]})

    async def as_metadata(request):
        if _policy.get_auth_mode() != "oauth":
            return JSONResponse({"error": "not_found"}, status_code=404)
        i = _issuer()
        return JSONResponse({"issuer": i, "authorization_endpoint": f"{i}/authorize",
                             "token_endpoint": f"{i}/token", "registration_endpoint": f"{i}/register",
                             "jwks_uri": f"{i}/.well-known/jwks.json",
                             "code_challenge_methods_supported": ["S256"]})

    class AuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            if request.url.path.startswith("/.well-known/"):
                return await call_next(request)
            principal = resolve_principal(_bearer(request.headers), _policy, _auth_settings)
            if principal is None:
                meta = f"{_issuer()}/.well-known/oauth-protected-resource"
                return JSONResponse({"error": "unauthorized"}, status_code=401,
                                    headers={"WWW-Authenticate": f'Bearer resource_metadata="{meta}"'})
            token = current_principal.set(principal)
            try:
                return await call_next(request)
            finally:
                current_principal.reset(token)

    app = Starlette(
        lifespan=lifespan,
        routes=[
            Route("/.well-known/oauth-protected-resource", protected_resource),
            Route("/.well-known/oauth-authorization-server", as_metadata),
            Mount("/mcp", app=session_manager.handle_request),
        ],
    )
    app.add_middleware(AuthMiddleware)
    return app


def _run_http(server):
    """Run MCP server over Streamable HTTP transport."""
    import uvicorn
    app = _build_http_app(server)
    host = os.environ.get("BRAIN_MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("BRAIN_MCP_PORT", "7780"))
    uvicorn.run(app, host=host, port=port)


def main():
    server = _build_server()
    transport = os.environ.get("BRAIN_MCP_TRANSPORT", "stdio").lower()
    if transport == "http":
        _run_http(server)
    else:
        _run_stdio(server)


if __name__ == "__main__":
    main()
