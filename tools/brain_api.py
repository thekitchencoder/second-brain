#!/usr/bin/env python3
"""brain-api: FastAPI REST layer for the second-brain.

Sits between the MCP server and the filesystem, reuses the same handler
functions, and adds structured responses + surgical edit support for a
web UI with wiki-link navigation.
"""
import html as _html
import json
import os
import time
from enum import Enum
from typing import Optional
from urllib.parse import urlencode, urlsplit

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from lib.auth import resolve_principal, AuthSettings, Principal
from lib.config import Config
from lib.policy import get_policy_provider
from lib.retrieval_log import (
    check_retrieval_log_config,
    safe_log_admin,
    safe_log_reads,
    safe_log_write,
)
from lib.oauth_server import (
    AuthState,
    ClientStore,
    RefreshStore,
    RegistrationError,
    issue_auth_code,
    redeem_auth_code,
)
from lib.clean import extract_frontmatter
from lib.visibility import visible, can_write_transition
from lib.edit import (
    append_to_section,
    find_replace,
    insert_wikilink,
    prepend_to_section,
    replace_lines,
    replace_section,
    update_frontmatter,
)
from lib.brain import (
    _check_within_brain,
    _list_template_names,
    _meta_for_path,
    _paginated_visible_search,
    _principal_unrestricted,
    _principal_write_unrestricted,
    _relative_path,
    extract_wikilinks,
    find_backlinks,
    handle_brain_create,
    handle_brain_query,
    handle_brain_related,
    handle_brain_search,
    handle_brain_templates,
    handle_brain_trash,
    handle_brain_restore,
)

_cfg = Config()
_auth_settings = AuthSettings.from_env()
_policy = get_policy_provider(_cfg)
check_retrieval_log_config()
_client_store = ClientStore(os.path.join(_cfg.brain_path, ".ai", "oauth-clients.json"))
_auth_state = AuthState()
_refresh_store = RefreshStore(os.path.join(_cfg.brain_path, ".ai", "oauth-refresh.json"))


def _bearer(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[len("Bearer "):].strip()
    return None


def _www_authenticate() -> str:
    issuer = os.environ.get("BRAIN_AUTH_ISSUER", "")
    meta = f"{issuer}/.well-known/oauth-protected-resource"
    return f'Bearer resource_metadata="{meta}"'


def require_principal(request: Request) -> Principal:
    principal = resolve_principal(_bearer(request), _policy, _auth_settings)
    if principal is None:
        raise HTTPException(status_code=401, detail="Unauthorized",
                            headers={"WWW-Authenticate": _www_authenticate()})
    request.state.principal = principal
    return principal


app = FastAPI(
    title="Second Brain API",
    version="0.1.0",
    description="REST API for reading, editing, and navigating a markdown brain.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cfg.cors_origins,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.middleware("http")
async def _admin_oracle_guard(request: Request, call_next):
    response = await call_next(request)
    # Oracle discipline for the admin surface: the router resolves
    # method-mismatch (405) and slash-redirects (307/308) BEFORE the
    # admin gate dependency runs, which would let an unauthenticated
    # caller map which admin routes exist. Normalize them to the same
    # 404 an absent route produces. Scoped strictly to /api/admin.
    if request.url.path.startswith("/api/admin") and response.status_code in (405, 307, 308):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return response

# The upstream authlib client uses Starlette session state for its CSRF `state`.
# Add the session middleware once, in oauth mode only. Derive a dedicated secret
# (never a raw PEM prefix — the first ~28 chars of a PKCS8 PEM are the constant
# header) and hard-fail rather than silently defaulting to a dev value.
if _policy.get_auth_mode() == "oauth":
    import hashlib
    from starlette.middleware.sessions import SessionMiddleware
    _signing = os.environ.get("BRAIN_AUTH_SIGNING_KEY")
    if not _signing:
        raise RuntimeError("BRAIN_AUTH_SIGNING_KEY is required when auth.mode = 'oauth'")
    _session_secret = os.environ.get("BRAIN_AUTH_SESSION_SECRET") \
        or hashlib.sha256(_signing.encode()).hexdigest()
    app.add_middleware(SessionMiddleware, secret_key=_session_secret)


def _oauth_enabled() -> bool:
    return _policy.get_auth_mode() == "oauth"


@app.get("/.well-known/oauth-protected-resource")
def protected_resource_metadata():
    if not _oauth_enabled():
        raise HTTPException(404, "Not found")
    issuer = os.environ.get("BRAIN_AUTH_ISSUER", "")
    return {
        "resource": os.environ.get("BRAIN_AUTH_AUDIENCE", ""),
        "authorization_servers": [issuer],
        "bearer_methods_supported": ["header"],
    }


@app.get("/.well-known/oauth-authorization-server")
def authorization_server_metadata():
    if not _oauth_enabled():
        raise HTTPException(404, "Not found")
    issuer = os.environ.get("BRAIN_AUTH_ISSUER", "")
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/authorize",
        "token_endpoint": f"{issuer}/token",
        "registration_endpoint": f"{issuer}/register",
        "jwks_uri": f"{issuer}/.well-known/jwks.json",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post"],
        "revocation_endpoint": f"{issuer}/revoke",
    }


@app.get("/.well-known/jwks.json")
def jwks():
    if not _oauth_enabled():
        raise HTTPException(404, "Not found")
    return _auth_settings.public_jwks()


def _valid_redirect(uri: str) -> bool:
    # https only, except loopback for local development.
    parts = urlsplit(uri)
    if parts.scheme == "https":
        return True
    if parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost"):
        return True
    return False


@app.post("/register", status_code=201)
async def register_client(request: Request):
    if not _oauth_enabled():
        raise HTTPException(404, "Not found")
    metadata = await request.json()
    uris = metadata.get("redirect_uris") or []
    if not uris:
        raise HTTPException(400, "redirect_uris required")
    if not all(_valid_redirect(u) for u in uris):
        raise HTTPException(400, "redirect_uris must be https (or loopback)")
    try:
        return _client_store.register(metadata)
    except RegistrationError:
        raise HTTPException(429, "client registration limit reached")


# ── OAuth 2.1 authorization-code flow (PKCE S256, upstream federation) ─


def _upstream_oauth():
    """Lazily build the authlib upstream OIDC client from env."""
    from authlib.integrations.starlette_client import OAuth
    oauth = OAuth()
    oauth.register(
        name="upstream",
        server_metadata_url=os.environ["BRAIN_AUTH_UPSTREAM_ISSUER"].rstrip("/")
            + "/.well-known/openid-configuration",
        client_id=os.environ["BRAIN_AUTH_UPSTREAM_CLIENT_ID"],
        client_secret=os.environ["BRAIN_AUTH_UPSTREAM_CLIENT_SECRET"],
        client_kwargs={"scope": "openid email"},
    )
    return oauth.create_client("upstream")


@app.get("/authorize")
async def authorize(request: Request):
    if not _oauth_enabled():
        raise HTTPException(404, "Not found")
    q = request.query_params
    client = _client_store.get(q.get("client_id", ""))
    if client is None or q.get("redirect_uri") not in client["redirect_uris"]:
        raise HTTPException(400, "invalid client or redirect_uri")
    if q.get("code_challenge_method") != "S256" or not q.get("code_challenge"):
        raise HTTPException(400, "PKCE S256 code_challenge required")
    brain_state = os.urandom(16).hex()
    try:
        _auth_state.stash_pending(brain_state, client_id=q["client_id"],
                                  redirect_uri=q["redirect_uri"],
                                  code_challenge=q["code_challenge"],
                                  client_state=q.get("state", ""))
    except RegistrationError:
        # Bounded store is at capacity even after sweeping expired entries —
        # fail the request rather than growing memory without bound.
        raise HTTPException(503, "authorization service busy, try again shortly")
    upstream = _upstream_oauth()
    callback = os.environ["BRAIN_AUTH_ISSUER"].rstrip("/") + "/callback"
    return await upstream.authorize_redirect(request, callback, state=brain_state)


def _consent_page(ticket: str, client_name: str, redirect_uri: str, subject: str) -> HTMLResponse:
    cn = _html.escape(client_name or "(unnamed client)")
    ru = _html.escape(redirect_uri)
    sub = _html.escape(subject)
    tk = _html.escape(ticket)
    body = (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<title>Authorize access</title></head><body>"
        "<h1>Authorize access to your brain</h1>"
        f"<p><strong>{cn}</strong> is requesting access to your second-brain "
        f"as <strong>{sub}</strong>.</p>"
        f"<p>If you approve, an authorization code will be sent to:<br><code>{ru}</code></p>"
        "<p>Only approve if you started this sign-in and recognise the destination above.</p>"
        "<form method=\"post\" action=\"/consent\">"
        f"<input type=\"hidden\" name=\"ticket\" value=\"{tk}\">"
        "<button name=\"decision\" value=\"approve\" type=\"submit\">Approve</button> "
        "<button name=\"decision\" value=\"deny\" type=\"submit\">Deny</button>"
        "</form></body></html>"
    )
    return HTMLResponse(body, headers={
        "X-Frame-Options": "DENY",
        "Content-Security-Policy": "frame-ancestors 'none'",
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
    })


@app.get("/callback")
async def callback(request: Request):
    if not _oauth_enabled():
        raise HTTPException(404, "Not found")
    upstream = _upstream_oauth()
    token = await upstream.authorize_access_token(request)
    userinfo = token.get("userinfo") or await upstream.userinfo(token=token)
    subject = userinfo.get("email")
    pending = _auth_state.pop_pending(request.query_params.get("state", ""))
    if not subject or pending is None:
        raise HTTPException(400, "upstream login failed")
    client = _client_store.get(pending["client_id"]) or {}
    ticket = _auth_settings.issue_consent({
        "client_id": pending["client_id"],
        "redirect_uri": pending["redirect_uri"],
        "code_challenge": pending["code_challenge"],
        "client_state": pending["client_state"],
        "subject": subject,
    })
    return _consent_page(ticket, client.get("client_name", ""),
                         pending["redirect_uri"], subject)


@app.post("/consent")
async def consent(request: Request):
    if not _oauth_enabled():
        raise HTTPException(404, "Not found")
    form = await request.form()
    ticket = _auth_settings.verify_consent(form.get("ticket", ""))
    if ticket is None:
        raise HTTPException(400, "invalid or expired consent request")
    redirect_uri = ticket["redirect_uri"]
    sep = "&" if "?" in redirect_uri else "?"
    if form.get("decision") != "approve":
        query = urlencode({"error": "access_denied", "state": ticket.get("client_state", "")})
        return RedirectResponse(f"{redirect_uri}{sep}{query}", status_code=303)
    try:
        code = issue_auth_code(_auth_state, client_id=ticket["client_id"],
                               redirect_uri=redirect_uri,
                               code_challenge=ticket["code_challenge"],
                               subject=ticket["subject"])
    except RegistrationError:
        raise HTTPException(503, "authorization service busy, try again shortly")
    query = urlencode({"code": code, "state": ticket.get("client_state", "")})
    return RedirectResponse(f"{redirect_uri}{sep}{query}", status_code=303)


@app.post("/token")
async def token(request: Request):
    if not _oauth_enabled():
        raise HTTPException(404, "Not found")
    form = await request.form()
    grant = form.get("grant_type")
    _REFRESH_TTL = 30 * 86400
    if grant == "authorization_code":
        client_id = form.get("client_id", "")
        subject = redeem_auth_code(_auth_state, code=form.get("code", ""),
                                   client_id=client_id,
                                   redirect_uri=form.get("redirect_uri", ""),
                                   code_verifier=form.get("code_verifier", ""))
        if subject is None:
            raise HTTPException(400, "invalid_grant")
        access = _auth_settings.issue_jwt(subject, {"email": subject})
        try:
            jti, _ = _refresh_store.issue(subject, client_id, ttl=_REFRESH_TTL)
        except RegistrationError:
            raise HTTPException(503, "authorization service busy, try again shortly")
        refresh = _auth_settings.issue_jwt(
            subject, {"email": subject, "typ": "refresh", "jti": jti, "client_id": client_id},
            ttl=_REFRESH_TTL)
        return {"access_token": access, "token_type": "Bearer", "expires_in": 3600,
                "refresh_token": refresh}
    if grant == "refresh_token":
        claims = _auth_settings.validate_jwt(form.get("refresh_token", ""))
        if claims is None or claims.get("typ") != "refresh":
            raise HTTPException(400, "invalid_grant")
        jti = claims.get("jti")
        token_client = claims.get("client_id")
        # client binding: the presenting client must own the token
        if not jti or not token_client or token_client != form.get("client_id", ""):
            raise HTTPException(400, "invalid_grant")
        rec = _refresh_store.get(jti)
        if rec is None or rec.get("exp", 0) < int(time.time()) or rec.get("client_id") != token_client:
            raise HTTPException(400, "invalid_grant")
        if rec.get("revoked"):
            # a retired token is being replayed → treat as theft, kill the chain
            _refresh_store.revoke_all_for(rec.get("subject"), rec.get("client_id"))
            raise HTTPException(400, "invalid_grant")
        subject = rec.get("subject")
        if not subject:
            raise HTTPException(400, "invalid_grant")
        try:
            new_jti, _ = _refresh_store.rotate(jti, subject, token_client, ttl=_REFRESH_TTL)
        except RegistrationError:
            raise HTTPException(503, "authorization service busy, try again shortly")
        access = _auth_settings.issue_jwt(subject, {"email": claims.get("email", subject)})
        new_refresh = _auth_settings.issue_jwt(
            subject, {"email": claims.get("email", subject), "typ": "refresh",
                      "jti": new_jti, "client_id": token_client}, ttl=_REFRESH_TTL)
        return {"access_token": access, "token_type": "Bearer", "expires_in": 3600,
                "refresh_token": new_refresh}
    raise HTTPException(400, "unsupported_grant_type")


@app.post("/revoke")
async def revoke_token(request: Request):
    if not _oauth_enabled():
        raise HTTPException(404, "Not found")
    form = await request.form()
    claims = _auth_settings.validate_jwt(form.get("token", ""))
    # RFC 7009: return 200 regardless of token validity (no scanning oracle);
    # only actually revoke a valid refresh token owned by the presenting client.
    if claims and claims.get("typ") == "refresh":
        jti = claims.get("jti")
        if jti and claims.get("client_id") == form.get("client_id", ""):
            _refresh_store.revoke(jti)
    return {}


# ── Helpers ──────────────────────────────────────────────────────────


def _resolve(filepath: str) -> str:
    """Resolve filepath to absolute, validated path within the brain."""
    bp = _cfg.brain_path
    full = filepath if filepath.startswith("/") else os.path.join(bp, filepath)
    if err := _check_within_brain(full, bp):
        raise HTTPException(status_code=403, detail=err)
    return full


def _read_file(full_path: str) -> str:
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail=f"File not found: {full_path}")
    with open(full_path, "r", encoding="utf-8") as f:
        return f.read()


def _write_file(full_path: str, content: str) -> None:
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)


def _relative(full_path: str) -> str:
    """Return path relative to brain root."""
    return _relative_path(full_path, _cfg.brain_path)


def _parse_note(filepath: str, raw: str) -> dict:
    """Parse a raw markdown file into structured note dict."""
    meta, body = extract_frontmatter(raw)
    return {
        "filepath": filepath,
        "frontmatter": meta,
        "body": body,
        "wikilinks": extract_wikilinks(raw),
    }


def _find_backlinks(filepath: str) -> list[dict]:
    """Walk the brain and find notes that contain a [[wikilink]] to filepath."""
    return find_backlinks(filepath, _cfg.brain_path)


# ── Request / Response models ────────────────────────────────────────


class NoteResponse(BaseModel):
    filepath: str
    frontmatter: dict = Field(default_factory=dict)
    body: str = ""
    wikilinks: list[dict] = Field(default_factory=list)


class SearchResult(BaseModel):
    filepath: str
    title: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = None
    created: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    content_preview: str = ""
    distance: Optional[float] = None


class CreateRequest(BaseModel):
    template: str
    title: str
    directory: Optional[str] = None


class WriteRequest(BaseModel):
    content: str


class EditOp(str, Enum):
    update_frontmatter = "update_frontmatter"
    replace_section = "replace_section"
    append_to_section = "append_to_section"
    prepend_to_section = "prepend_to_section"
    replace_lines = "replace_lines"
    find_replace = "find_replace"
    insert_wikilink = "insert_wikilink"


class EditRequest(BaseModel):
    op: EditOp
    # update_frontmatter
    frontmatter: Optional[dict] = None
    # section operations
    heading: Optional[str] = None
    body: Optional[str] = None
    # replace_lines
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    replacement: Optional[str] = None
    # find_replace
    find: Optional[str] = None
    replace: Optional[str] = None
    regex: bool = False
    count: int = 0  # 0 = all
    # insert_wikilink
    target: Optional[str] = None
    context_heading: Optional[str] = None


class EditResponse(BaseModel):
    filepath: str
    success: bool
    detail: str


class BacklinkEntry(BaseModel):
    filepath: str
    title: str


# ── Endpoints ────────────────────────────────────────────────────────


@app.get("/api/search", response_model=list[SearchResult])
def search_notes(
    q: str = Query(..., description="Semantic search query"),
    limit: int = Query(5, ge=1, le=50),
    principal: Principal = Depends(require_principal),
):
    """Semantic vector search across all brain notes."""
    from lib.embeddings import get_embedding, EmbeddingError
    from lib.vectorstore import get_store

    try:
        embedding = get_embedding(q)
    except EmbeddingError as e:
        raise HTTPException(503, f"Embedding service unavailable: {e}")
    store = get_store(_cfg.db_path)
    if _principal_unrestricted(principal):
        results = store.search(embedding, k=limit)
    else:
        fields = _cfg.load_profile().fields
        results = _paginated_visible_search(store, embedding, limit, principal, fields)
    safe_log_reads(principal, "brain_search", q,
                   list(dict.fromkeys(r["filepath"] for r in results)))
    return [
        SearchResult(
            filepath=r["filepath"],
            title=r.get("title"),
            type=r.get("type"),
            status=r.get("status"),
            created=r.get("created"),
            tags=r.get("tags") or [],
            content_preview=r.get("content", "")[:400],
            distance=r.get("distance"),
        )
        for r in results
    ]


_STABLE_QUERY_PARAMS = {"tag", "created_after", "created_before", "where"}


@app.get("/api/notes", response_model=list[str])
def list_notes(request: Request, tag: Optional[str] = None,
               created_after: Optional[str] = None, created_before: Optional[str] = None,
               where: Optional[str] = None,
               principal: Principal = Depends(require_principal)):
    """List notes filtered by metadata (delegates to zk)."""
    profile = _cfg.load_profile()
    field_names = {f.name for f in profile.fields}
    allowed = _STABLE_QUERY_PARAMS | field_names
    unknown = [k for k in request.query_params if k not in allowed]
    if unknown:
        raise HTTPException(400, f"Unknown filter field(s): {', '.join(sorted(unknown))}. "
                                 f"Allowed: {', '.join(sorted(allowed))}")
    fields = {k: v for k, v in request.query_params.items() if k in field_names}
    try:
        where_dict = json.loads(where) if where else None
    except json.JSONDecodeError:
        raise HTTPException(400, "where must be a JSON object")
    if where_dict is not None:
        if not isinstance(where_dict, dict) or not all(isinstance(v, str) for v in where_dict.values()):
            raise HTTPException(400, "where must be a JSON object of string values")
    result = handle_brain_query(_cfg.brain_path, tag=tag, fields=fields, where=where_dict,
                                created_after=created_after, created_before=created_before,
                                field_specs=profile.fields, principal=principal)
    if result.startswith("Invalid"):
        raise HTTPException(400, result)
    if result.startswith("No notes") or result.startswith("zk"):
        return []
    return [f.strip() for f in result.splitlines() if f.strip()]


@app.get("/api/notes/{filepath:path}/related", response_model=list[SearchResult])
def related_notes(filepath: str, limit: int = Query(5, ge=1, le=50),
                   principal: Principal = Depends(require_principal)):
    """Find semantically related notes."""
    from lib.vectorstore import get_store
    import numpy as np

    store = get_store(_cfg.db_path)
    full = _resolve(filepath)
    unrestricted = _principal_unrestricted(principal)
    fields = None if unrestricted else _cfg.load_profile().fields
    if not unrestricted and os.path.isfile(full):
        # Oracle-safety on the TARGET: mirrors the handle_brain_related guard —
        # a forbidden-but-indexed note must 404 identically to an absent one.
        if not visible(_meta_for_path(full), principal, fields):
            raise HTTPException(404, f"No embeddings found for {filepath}")
    vectors = store.get_chunk_embeddings(full)
    if not vectors:
        vectors = store.get_chunk_embeddings(filepath)
    if not vectors:
        raise HTTPException(404, f"No embeddings found for {filepath}")

    mean_vec = list(np.mean(vectors, axis=0))
    exclude = {full, filepath}
    if unrestricted:
        candidates = store.search(mean_vec, k=limit * 10)
        seen: set[str] = set()
        raw_results = []
        for r in candidates:
            fp = r["filepath"]
            if fp in exclude or fp in seen:
                continue
            seen.add(fp)
            raw_results.append(r)
            if len(raw_results) == limit:
                break
    else:
        raw_results = _paginated_visible_search(store, mean_vec, limit,
                                                principal, fields,
                                                exclude=exclude, initial_k=limit * 10)
    safe_log_reads(principal, "brain_related", filepath, [r["filepath"] for r in raw_results])
    return [
        SearchResult(
            filepath=r["filepath"],
            title=r.get("title"),
            type=r.get("type"),
            status=r.get("status"),
            created=r.get("created"),
            tags=r.get("tags") or [],
            content_preview=r.get("content", "")[:400],
            distance=r.get("distance"),
        )
        for r in raw_results
    ]


@app.get("/api/notes/{filepath:path}/backlinks", response_model=list[BacklinkEntry])
def get_backlinks(filepath: str, principal: Principal = Depends(require_principal)):
    """Find all notes that contain a [[wikilink]] to this note."""
    full = _resolve(filepath)
    results = _find_backlinks(full)
    if not _principal_unrestricted(principal):
        fields = _cfg.load_profile().fields
        results = [
            r for r in results
            if visible(_meta_for_path(os.path.join(_cfg.brain_path, r["filepath"])),
                      principal, fields)
        ]
    safe_log_reads(principal, "brain_backlinks", filepath, [r["filepath"] for r in results])
    return results


@app.get("/api/notes/{filepath:path}", response_model=NoteResponse)
def read_note(filepath: str, principal: Principal = Depends(require_principal)):
    """Read a note with parsed frontmatter and extracted wikilinks."""
    full = _resolve(filepath)
    raw = _read_file(full)
    if not _principal_unrestricted(principal):
        meta, _ = extract_frontmatter(raw)
        fields = _cfg.load_profile().fields
        if not visible(meta, principal, fields):
            # Oracle-safe: identical detail format to the genuinely-absent case
            # in _read_file above — a forbidden note is indistinguishable from
            # a missing one.
            raise HTTPException(status_code=404, detail=f"File not found: {full}")
    rel = _relative(full)
    safe_log_reads(principal, "brain_read", rel, [rel])
    return _parse_note(rel, raw)


@app.put("/api/notes/{filepath:path}", response_model=EditResponse)
def write_note(filepath: str, req: WriteRequest, principal: Principal = Depends(require_principal)):
    """Full file write (replace entire content)."""
    full = _resolve(filepath)
    fields = _cfg.load_profile().fields
    new_meta, _ = extract_frontmatter(req.content)
    if os.path.isfile(full):
        old_meta, _ = extract_frontmatter(_read_file(full))
        # read gate — can the caller even see the target? (oracle-safe)
        if not _principal_unrestricted(principal) and not visible(old_meta, principal, fields):
            # Oracle-safe: identical to read_note's forbidden-target 404.
            raise HTTPException(status_code=404, detail=f"File not found: {full}")
    else:
        old_meta = new_meta  # brand-new path — only the incoming layer gates
    # write gate — INDEPENDENT of the read dimension above; a principal can be
    # read-unrestricted (read=["*"]) while still being write-restricted.
    if not _principal_write_unrestricted(principal) and not can_write_transition(old_meta, new_meta, principal):
        raise HTTPException(status_code=403, detail=f"Not authorized to write {filepath}")
    _write_file(full, req.content)
    safe_log_write(principal, "write", _relative(full))
    return EditResponse(filepath=_relative(full), success=True, detail="File written")


@app.patch("/api/notes/{filepath:path}", response_model=EditResponse)
def edit_note(filepath: str, req: EditRequest, principal: Principal = Depends(require_principal)):
    """Surgical edit: modify a note without full-file replacement."""
    full = _resolve(filepath)
    text = _read_file(full)
    op = req.op

    old_meta, _ = extract_frontmatter(text)
    unrestricted = _principal_unrestricted(principal)
    if not unrestricted:
        fields = _cfg.load_profile().fields
        if not visible(old_meta, principal, fields):
            # Oracle-safe: identical to read_note's forbidden-target 404.
            raise HTTPException(status_code=404, detail=f"File not found: {full}")

    # Apply the edit op to produce the candidate text IN MEMORY first — never
    # persist before authorizing. The post-edit frontmatter is authoritative
    # for every op (including update_frontmatter): a raw-text op like
    # find_replace/replace_lines can rewrite the `layer:` line just as surely
    # as update_frontmatter can, so gating on a stale `new_meta = old_meta`
    # would let those ops smuggle a layer escalation past the check.
    if op == EditOp.update_frontmatter:
        if not req.frontmatter:
            raise HTTPException(400, "'frontmatter' dict required for update_frontmatter")
        candidate = update_frontmatter(text, req.frontmatter)
        detail = f"Updated frontmatter keys: {', '.join(req.frontmatter.keys())}"

    elif op in (EditOp.replace_section, EditOp.append_to_section, EditOp.prepend_to_section):
        if not req.heading:
            raise HTTPException(400, f"'heading' required for {op.value}")
        body = req.body or ""
        if op == EditOp.replace_section:
            candidate, found = replace_section(text, req.heading, body)
        elif op == EditOp.append_to_section:
            candidate, found = append_to_section(text, req.heading, body)
        else:
            candidate, found = prepend_to_section(text, req.heading, body)
        if not found:
            raise HTTPException(404, f"Section not found: {req.heading}")
        detail = f"{op.value}: {req.heading}"

    elif op == EditOp.replace_lines:
        if req.start_line is None or req.end_line is None:
            raise HTTPException(400, "'start_line' and 'end_line' required")
        candidate, err = replace_lines(text, req.start_line, req.end_line, req.replacement or "")
        if err:
            raise HTTPException(400, err)
        detail = f"Replaced lines [{req.start_line}, {req.end_line})"

    elif op == EditOp.find_replace:
        if req.find is None:
            raise HTTPException(400, "'find' required for find_replace")
        candidate, n = find_replace(
            text, req.find, req.replace or "", regex=req.regex, count=req.count
        )
        if n == -1:
            raise HTTPException(400, candidate)  # candidate is the error message
        detail = f"Replaced {n} occurrence(s)"

    elif op == EditOp.insert_wikilink:
        if not req.target:
            raise HTTPException(400, "'target' required for insert_wikilink")
        candidate, inserted = insert_wikilink(text, req.target, context_heading=req.context_heading)
        if not inserted:
            return EditResponse(filepath=_relative(full), success=True, detail="Link already present")
        detail = f"Inserted [[{req.target}]]"

    else:
        raise HTTPException(400, f"Unknown edit operation: {op}")

    # write gate — INDEPENDENT of the read fast-path above; a principal can be
    # read-unrestricted (read=["*"]) while still being write-restricted, so this
    # must never be skipped just because `unrestricted` (read-keyed) is True.
    new_meta, _ = extract_frontmatter(candidate)
    if not _principal_write_unrestricted(principal) and not can_write_transition(old_meta, new_meta, principal):
        raise HTTPException(status_code=403, detail=f"Not authorized to write {filepath}")

    _write_file(full, candidate)
    safe_log_write(principal, "edit", _relative(full), subject=detail)
    return EditResponse(filepath=_relative(full), success=True, detail=detail)


@app.post("/api/notes", response_model=EditResponse)
def create_note(req: CreateRequest, principal: Principal = Depends(require_principal)):
    """Create a new note from a template."""
    result = handle_brain_create(
        template=req.template,
        title=req.title,
        brain_path=_cfg.brain_path,
        directory=req.directory,
        principal=principal,
        fields=_cfg.load_profile().fields,
    )
    if result.startswith("Not authorized"):
        raise HTTPException(403, result)
    if not result.endswith(".md"):
        raise HTTPException(400, result)
    return EditResponse(filepath=_relative(result), success=True, detail=f"Created: {result}")


@app.post("/api/notes/{filepath:path}/trash", response_model=EditResponse)
def trash_note(filepath: str, principal: Principal = Depends(require_principal)):
    """Move a note to .trash/ and remove from the search index."""
    full = _resolve(filepath)
    if not os.path.isfile(full):
        raise HTTPException(status_code=404, detail=f"File not found: {filepath}")
    result = handle_brain_trash(
        filepath=_relative(full),
        brain_path=_cfg.brain_path,
        db_path=_cfg.db_path,
        principal=principal,
        fields=_cfg.load_profile().fields,
    )
    if result.startswith("File not found"):
        raise HTTPException(status_code=404, detail=result)
    if result.startswith("Not authorized"):
        raise HTTPException(status_code=403, detail=result)
    if result.startswith("Error"):
        raise HTTPException(status_code=400, detail=result)
    return EditResponse(filepath=filepath, success=True, detail=result)


@app.post("/api/notes/{filepath:path}/restore", response_model=EditResponse)
def restore_note(filepath: str, principal: Principal = Depends(require_principal)):
    """Restore a note from .trash/ back to its original location."""
    result = handle_brain_restore(
        trash_path=filepath,
        brain_path=_cfg.brain_path,
        principal=principal,
        fields=_cfg.load_profile().fields,
    )
    if result.startswith("Not authorized"):
        raise HTTPException(status_code=403, detail=result)
    if result.startswith("Error"):
        raise HTTPException(status_code=400, detail=result)
    return EditResponse(filepath=filepath, success=True, detail=result)


@app.get("/api/templates", response_model=list[str])
def list_templates(principal: Principal = Depends(require_principal)):
    """List available note templates."""
    return _list_template_names(brain_path=_cfg.brain_path)


# ── Admin plane (slice 2, audit-logged in slice 3) ────────────────────
# Policy truth is the profile repo: every mutation below delegates to
# PolicyEditor (a git commit) or PgCredentialStore (credentials only).
# safe_log_admin fires post-success in _admin_edit and the token routes below.


def _is_admin(principal: Principal) -> bool:
    rbac = _policy.get_rbac()
    if rbac is None or principal is None:
        return False
    spec = (rbac.roles or {}).get(getattr(principal, "role", None) or "") or {}
    if not isinstance(spec, dict):
        return False
    return spec.get("admin") is True


def _require_admin(request: Request) -> Principal:
    # Oracle discipline: everything short of an authenticated admin gets
    # the same 404 the route would produce if it didn't exist.
    if _policy.get_auth_mode() != "oauth":
        raise HTTPException(404, "Not Found")
    principal = resolve_principal(_bearer(request), _policy, _auth_settings)
    if principal is None or not _is_admin(principal):
        raise HTTPException(404, "Not Found")
    return principal


def _editor():
    from lib.policy_edit import PolicyEditor
    return PolicyEditor(_cfg.profile_dir)


def _credentials():
    if os.environ.get("BRAIN_POLICY_CREDENTIALS", "env") != "postgres":
        raise HTTPException(503, "Token minting requires BRAIN_POLICY_CREDENTIALS=postgres")
    from lib.credentials import get_credential_store
    return get_credential_store(_cfg.database_url)


def _admin_edit(principal: Principal, description: str, op):
    from lib.policy_edit import PolicyEditError
    try:
        sha = op(_editor())
    except PolicyEditError as e:
        raise HTTPException(400, str(e))
    _policy.invalidate()
    safe_log_admin(principal, "policy_edit", f"{description} ({sha[:7]})")
    return {"commit": sha}


class RoleSpec(BaseModel):
    read: list[str]
    write: list[str]
    admin: bool = False


class MappingSpec(BaseModel):
    role: str


@app.get("/api/admin/policy")
def admin_policy(principal: Principal = Depends(_require_admin)):
    rbac = _policy.get_rbac()
    return {
        "auth_mode": _policy.get_auth_mode(),
        "credential_backend": os.environ.get("BRAIN_POLICY_CREDENTIALS", "env"),
        "rbac": {
            "default_role": rbac.default_role,
            "roles": rbac.roles, "identities": rbac.identities,
            "principals": rbac.principals,
        } if rbac else None,
    }


@app.put("/api/admin/roles/{name}")
def admin_role_set(name: str, spec: RoleSpec,
                   principal: Principal = Depends(_require_admin)):
    return _admin_edit(principal, f"role_set {name}",
                       lambda ed: ed.role_set(name, spec.read, spec.write, spec.admin))


@app.delete("/api/admin/roles/{name}")
def admin_role_rm(name: str, principal: Principal = Depends(_require_admin)):
    return _admin_edit(principal, f"role_rm {name}", lambda ed: ed.role_rm(name))


@app.put("/api/admin/identities/{subject}")
def admin_identity_map(subject: str, spec: MappingSpec,
                       principal: Principal = Depends(_require_admin)):
    return _admin_edit(principal, f"identity_map {subject} -> {spec.role}",
                       lambda ed: ed.identity_map(subject, spec.role))


@app.delete("/api/admin/identities/{subject}")
def admin_identity_unmap(subject: str,
                         principal: Principal = Depends(_require_admin)):
    return _admin_edit(principal, f"identity_unmap {subject}", lambda ed: ed.identity_unmap(subject))


@app.put("/api/admin/principals/{pid}")
def admin_principal_set(pid: str, spec: MappingSpec,
                        principal: Principal = Depends(_require_admin)):
    return _admin_edit(principal, f"principal_set {pid} -> {spec.role}",
                       lambda ed: ed.principal_set(pid, spec.role))


@app.delete("/api/admin/principals/{pid}")
def admin_principal_rm(pid: str,
                       principal: Principal = Depends(_require_admin)):
    return _admin_edit(principal, f"principal_rm {pid}", lambda ed: ed.principal_rm(pid))


@app.post("/api/admin/principals/{pid}/token")
def admin_token_mint(pid: str, principal: Principal = Depends(_require_admin)):
    rbac = _policy.get_rbac()
    if pid not in ((rbac.principals or {}) if rbac else {}):
        raise HTTPException(400, f"unknown principal: {pid} — add it first "
                                 f"(PUT /api/admin/principals/{pid})")
    token = _credentials().mint(pid)
    safe_log_admin(principal, "token_mint", pid)
    return {"principal_id": pid, "token": token}


@app.delete("/api/admin/principals/{pid}/token")
def admin_token_revoke(pid: str, principal: Principal = Depends(_require_admin)):
    revoked = _credentials().revoke(pid)
    safe_log_admin(principal, "token_revoke", pid)
    return {"principal_id": pid, "revoked": revoked}


@app.get("/api/admin/tokens")
def admin_token_list(principal: Principal = Depends(_require_admin)):
    tokens = _credentials().list_tokens()
    safe_log_admin(principal, "token_list", f"{len(tokens)} tokens")
    return {"tokens": tokens}


@app.put("/api/admin/default-role")
def admin_default_role_set(spec: MappingSpec,
                           principal: Principal = Depends(_require_admin)):
    return _admin_edit(principal, f"default_role_set {spec.role}",
                       lambda ed: ed.default_role_set(spec.role))


@app.get("/api/admin/retrievals")
def admin_retrievals(principal: Principal = Depends(_require_admin),
                     principal_id: Optional[str] = Query(None, alias="principal"),
                     kind: Optional[str] = None, tool: Optional[str] = None,
                     since: Optional[str] = None, until: Optional[str] = None,
                     path: Optional[str] = None,
                     limit: int = Query(100, ge=1, le=1000)):
    # Deliberate choice: querying the log is NOT itself logged as an admin
    # event (no safe_log_admin call here) — reading history isn't a policy
    # mutation, and logging every read of the log would make it grow
    # under its own inspection.
    from lib.retrieval_log import enabled, get_retrieval_log
    if not enabled():
        raise HTTPException(503, "Retrieval log requires BRAIN_RETRIEVAL_LOG=postgres")
    log = get_retrieval_log(_cfg.database_url)
    return {"entries": log.query(principal=principal_id, kind=kind, tool=tool,
                                 since=since, until=until, path=path, limit=limit)}


def main():
    import uvicorn

    host = os.environ.get("BRAIN_API_HOST", "0.0.0.0")
    port = int(os.environ.get("BRAIN_API_PORT", "7779"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
