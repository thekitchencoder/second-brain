# RBAC (content visibility, Seam 7)

This page is the deploy guide for the **role-based content-visibility layer**
built on top of the [auth gate](auth.md). Auth (Seam 6) answers "who is this
caller?" — resolving a bearer token to a `Principal`. RBAC (Seam 7, this page)
answers "which notes may that `Principal` read, and which may it write?"

Like auth, this is a **profile dimension**: declared in `[auth.rbac]`,
resolved once per request, enforced at a single choke point
(`lib.visibility.visible()` / `can_write()`), not a separate service. A brain
that never sets `[auth.rbac]` — the bundled `ace` profile among them — pays
nothing: `mode = "none"` resolves every request to the synthetic `OWNER`
principal, and `OWNER`'s layers are the wildcard `("*",)`, which short-circuits
every check in this document to "allowed." See
[Backward compatibility](#backward-compatibility) for the proof.

## The model: layers, roles, fields

RBAC has two independent dimensions, checked in order — **coarse, then fine**:

1. **Coarse: layers.** Every note optionally carries a frontmatter `layer:`
   value (e.g. `fiction`, `secret`, `maker`). Every role declares which layers
   it may **read** and which it may **write**:

   ```toml
   [auth.rbac.roles]
   fenn = { read = ["fiction"], write = ["fiction"] }
   owner = { read = ["*"], write = ["*"] }
   ```

   `read`/`write` are independent lists — a role can read layers it can't
   write (e.g. a reviewer role), or vice versa. `"*"` in either list means
   unrestricted for that action. A legacy `layers = [...]` key is still
   accepted and satisfies both `read` and `write` identically, for roles that
   don't need the split.

2. **Fine: fields.** Independently of layer, a profile can declare a `list`-kind
   field with a `visibility` mode, matched against the caller's **role**:

   ```toml
   [fields.known_by]
   kind = "list"
   visibility = "allow"   # or "deny"
   ```

   - `visibility = "allow"`: if the field is present and non-empty on a note,
     the caller's role must appear in it, or the note is denied. An absent or
     empty field imposes no restriction (nothing to allow-list against).
   - `visibility = "deny"`: if the caller's role appears in the field's
     values, the note is denied — an explicit blocklist layered on top of an
     otherwise-visible note.

   A note can carry several visibility fields; all of them must pass.

Both dimensions matter for **reads** (`visible()`); only the layer dimension
applies to **writes** (`can_write()` — see [Writes](#writes-and-the-layer-mutation-guard)).
Visibility fields are a read-time refinement, not a write control.

## Deny-by-default

- A note with **no `layer:`** frontmatter is denied to every non-unrestricted
  role. There is no implicit "unlabelled = public" tier — layer is opt-in
  visibility, not opt-out.
- A malformed principal (e.g. `read_layers` that isn't a list/tuple/set) is
  denied, never treated as unrestricted. Fail closed, not open.
- The wildcard `"*"` is only honoured inside a real collection
  (`("*",)`) — a stray string is never treated as a wildcard by accident.

Concretely, in `lib/visibility.py`:

```python
def visible(meta, principal, fields) -> bool:
    ...
    if _unrestricted(principal.read_layers):
        return True                 # owner / "*" short-circuit
    if not _layer_ok(meta.get("layer"), principal.read_layers):
        return False                # coarse wall: deny-by-default
    for f in fields or []:
        ...                         # fine allow/deny fields
    return True
```

## The oracle-safety guarantee

A forbidden note must be **indistinguishable** from a note that doesn't
exist. Every read-egress path — `brain_read`, `brain_query`, `brain_search`,
`brain_related`, `brain_backlinks`, and their REST equivalents — returns the
*exact same* response for "exists but forbidden" as for "genuinely absent":

- MCP/CLI handlers: the literal string `"File not found"` (read),
  `"No embeddings found for <path>. Has it been indexed?"` (related), or
  silent omission from a list (query/search/backlinks) — never a distinct
  "forbidden" message, never a different string shape that leaks path-specific
  detail.
- REST routes: HTTP `404`, with a `detail` string byte-for-byte identical to
  the corresponding genuinely-absent-path 404.

This matters because a distinguishable "forbidden" response (a `403`, or a
message that names the layer) is itself a leak: a restricted caller could
enumerate the corpus by noting which paths get the "special" forbidden
response versus a plain 404. Denying and "not found" must be the same event
from the caller's point of view. `tests/test_visibility_enforcement.py`
locks this for every read path, including a semantic-search variant with a
faked vector store (`_FakeStore`) so the fine `visible()` filter is proven as
a second, independent gate — not merely trusting the coarse store-side wall.

## Writes and the layer-mutation guard

`can_write(meta, principal)` gates every write handler (`brain_write`,
`brain_edit`, `brain_trash`, `brain_restore`, and their REST equivalents) the
same way `visible()` gates reads: coarse layer wall, deny-by-default, `"*"`
short-circuit for unrestricted principals.

Writes have one extra rule beyond read: **a write may not move a note into a
layer the caller can't write, and may not move a note *out of* a layer the
caller can't write either.** Both the note's layer *before* the edit and its
layer *after* the edit must independently pass `can_write`:

```python
def can_write_transition(old_meta, new_meta, principal) -> bool:
    return can_write(old_meta, principal) and can_write(new_meta, principal)
```

Without the "after" check, a writer restricted to the `fiction` layer could
take a note it's allowed to write, relabel its `layer:` frontmatter to
something it doesn't have write access to (say, `maker`), and thereby smuggle
content into — or effectively exfiltrate visibility away from — a layer it
was never granted. This is checked against the **actual post-edit
frontmatter**, not a stale copy of the pre-edit metadata: a raw-text edit op
(`find_replace`, `replace_lines`) can rewrite a `layer:` line just as surely
as a structured `update_frontmatter` call can, so the candidate text is always
re-parsed for frontmatter *after* the edit is applied in memory and *before*
it is persisted to disk. See `test_layer_escalation_via_find_replace_denied`
and `test_layer_escalation_via_replace_lines_denied` in
`tests/test_visibility_enforcement.py`.

## Re-indexing: populating `layer`

The `chunks` table (the sqlite-vec-backed semantic index) has always had a
`layer` column added by `init_db` — an idempotent `ALTER TABLE chunks ADD
COLUMN layer TEXT`, so a brain indexed before this feature existed upgrades
its schema automatically on the next `init_db` call, with no manual migration
step and no data loss.

**The column existing is not the same as it being populated.** `layer` is
only *filled in* when a note is (re-)indexed after this feature is deployed —
`upsert_chunk` reads `meta.get("layer")` from the note's frontmatter at index
time. A note that already had a `layer:` field before you enabled RBAC, but
hasn't been re-indexed since, has a `NULL` layer in `chunks` — and `NULL`
fails the coarse layer check for every non-unrestricted role (deny-by-default
applies to missing layer, whether that's a missing frontmatter field or a
stale, unpopulated index row). **Run a full re-index (`brain-index`) after
turning on `[auth.rbac]`** so semantic search's coarse store-side wall
(`search_chunks_in_layers`) sees real layer values, not `NULL`s it then denies
across the board. Note-file reads (`brain_read`, `brain_query`) are unaffected
by this — they parse frontmatter directly from disk on every call, not from
the index — only semantic search (`brain_search`, `brain_related`) depends on
the index being current.

## The write-path existence oracle, and the folder-homogeneous-layers rule

There is one oracle this design does not close in code, and closes by
*convention* instead: **a restricted write to a path that exists but is
invisible returns a different outcome than a write to a path that is
genuinely absent.**

Concretely: `handle_brain_write("secret/x.md", ...)` for a caller who can't
read the `secret` layer returns `"File not found: secret/x.md"` (the
oracle-safe read-side response, since the write handler checks `visible()` on
any pre-existing file before checking `can_write`). But
`handle_brain_write("brand-new/x.md", ...)` for a path that has never existed
returns `"Written: ..."` on success. A caller who tries writing to the *same
path twice* — once when it doesn't exist, once when someone else has since
created an invisible note there — can distinguish "nothing here" from
"something here I can't see" purely from which of those two responses comes
back. This is the classic create/collision (mailbox) problem: making "create"
and "silently overwrite-and-report-success" indistinguishable from "deny"
would require either accepting data loss (silently discarding the write) or
misreporting success on a write that didn't happen — both worse than the
narrow oracle they'd close.

**The design closes this by profile-authoring convention, not code:** *write
layers should be folder-homogeneous.* Structure the brain so every note in a
folder a given role can write shares that role's write layer — i.e., a
writer's write-layer set should line up with a set of folders it exclusively
owns, so it can never *address* a path that both (a) already exists and (b)
belongs to a layer the writer can't see. Under a well-formed profile of this
shape, the ambiguous case — a restricted writer's own folder containing a
note in a layer that writer can't read — is unreachable by construction. If
you ever observe that collision in practice, treat it as a **misconfiguration
symptom** (someone hand-placed a foreign-layer note inside a role's writable
folder) — not a leak channel to patch around in code. Fixing the profile
(moving the note, or aligning the role's folders/layers) is the correct
remedy, not adding write-path special-casing.

## Administering policy

Policy — roles, identities, principal→role mappings, the default role — is
managed through the admin plane, not by hand-editing `profile.toml` on a
running brain: the `brain-admin` CLI and the REST routes it wraps,
`/api/admin/*`. Both write the same thing, through the same writer
(`lib.policy_edit.PolicyEditor`): **every mutation is a git commit to the
profile repo.** There is no policy table in Postgres — the profile repo
remains the single source of policy truth. (What *does* live in Postgres,
if you opt in, is agent-token credentials — see
[Token lifecycle](#token-lifecycle-agent-credentials) below — and, in the
full-stack tier, the vector index; see
[docs/recipes/full-stack-compose.md](recipes/full-stack-compose.md).)

### The git-truth model

- Every `role set`, `role rm`, `identity map`/`unmap`, `principal set`/`rm`,
  and `default-role set` operation reads `profile.toml`, rewrites only the
  changed `[auth.rbac]` table with `tomlkit` (preserving comments and
  unrelated content), and commits it (`policy: <description>`) to the
  profile repo. `git log` on the profile clone is the audit trail for policy
  changes.
- Edits are idempotent: re-applying an already-current role or mapping is a
  no-op that returns the current `HEAD` sha rather than creating an empty
  commit.
- A failed commit (e.g. a rejecting pre-commit hook) rolls the working file
  back to its pre-edit content — the live policy a running provider reads is
  never left mid-mutation.
- `ProfilePolicyProvider` hot-reloads `profile.toml` on mtime change (see
  [docs/auth.md](auth.md)), so a policy edit takes effect on the next request
  with no restart.

### `brain-admin` — local and remote

`brain-admin` reaches policy through one of two transports, chosen by
whether `--url`/`BRAIN_API_URL` is set:

- **Local (default)** — operates directly on the profile repo and, for
  `token` subcommands, Postgres. This is the `docker exec` recovery path: it
  needs no running `brain-api` and no network, so it still works if the API
  is down or auth is misconfigured.

  ```bash
  docker exec -it brain brain-admin role set maker --read '*' --write '*'
  docker exec -it brain brain-admin principal set fenn-desk maker
  docker exec -it brain brain-admin token mint fenn-desk
  ```

- **Remote** — talks to `/api/admin/*` over HTTP with a bearer token
  (`--token`/`BRAIN_ADMIN_TOKEN`), for admins without shell access to the
  container:

  ```bash
  brain-admin --url https://brain.example.com --token "$BRAIN_ADMIN_TOKEN" \
    role set maker --read '*' --write '*'
  ```

Both transports raise the same two exception shapes — `PolicyEditError` for
user mistakes (unknown role, malformed layer list) and `RuntimeError` for
infra problems (unreachable API, misconfigured credentials) — so scripting
against either transport looks the same.

### Token lifecycle (agent credentials)

`token mint`/`token revoke`/`token list` only work when
`BRAIN_POLICY_CREDENTIALS=postgres` (see
[docs/auth.md](auth.md#env-var-reference)): they mint/revoke rows in
Postgres's `agent_tokens` table via `lib.credentials.PgCredentialStore`,
never in the profile repo — credentials and role grants are deliberately
different kinds of state (see [The git-truth model](#the-git-truth-model)
above). A token's plaintext is printed exactly once, at `mint` time; `token
list` and `policy show` never expose it, only the principal id and
revocation timestamp.

```bash
brain-admin token mint fenn-desk    # prints the plaintext token once — save it now
brain-admin token list              # principal id + created/revoked timestamps, no secrets
brain-admin token revoke fenn-desk  # kills every active token for that principal
```

Revocation is immediate: unlike the short-lived OAuth JWTs described in
[docs/auth.md](auth.md#token-lifecycle), a static agent token is checked
against the live `agent_tokens` table on every request, so a revoked token
stops working on its very next use rather than after some TTL expires.

### The 404 oracle, extended to the admin plane

The admin routes inherit the same oracle-safety discipline as the
content-read paths (see
[The oracle-safety guarantee](#the-oracle-safety-guarantee) above): every way
to fail to reach an admin action — `mode = "none"`, no token, an
authenticated-but-non-admin role, and a route that genuinely doesn't exist —
returns the identical `404`. A non-admin principal cannot learn that
`/api/admin/*` exists (versus any other unmapped path) from the response it
gets back; `brain-admin`'s remote transport surfaces all of these uniformly
as "not found or not authorized" rather than distinguishing them.

## The retrieval log

Alongside the git-commit audit trail for policy *mutations* (see
[The git-truth model](#the-git-truth-model) above), there is a separate,
append-only log of what the archive actually *showed* each principal:
`BRAIN_RETRIEVAL_LOG=postgres` records one row per note surfaced by a read
(`brain_search`, `brain_related`, `brain_read`, `brain_query`,
`brain_backlinks` and their REST equivalents), one row per successful write
(`write`/`edit`/`create`/`trash`/`restore`), and one row per admin action
(`policy_edit`, `token_mint`, `token_revoke`, `token_list`) — including from
`brain-admin`'s local transport, which has no resolved principal to
attribute to and so logs under the fixed `local-admin` id. Grain is
deliberately fine: a search that surfaces three notes logs three rows, not
one row for the query — so "which principals have seen note X" is a single
`filepath` filter away, not a query-text guess.

This is **not** a hook on `visible()`/`can_write()` themselves — those stay
pure predicates with no side effect (see the note at the top of
`lib/visibility.py`). The log hooks in at the handler/route result boundary
in `tools/lib/brain.py` and `tools/brain_api.py` instead, firing only
**after** a result is known — a forbidden note is never logged, because it
never reaches the point in the code where the hook fires, and neither is a
request that erred out before producing a result. The oracle-safety
guarantee above extends to the log itself: a restricted principal's read
history contains exactly what it was shown, nothing it was denied, and
nothing about a note it never asked about.

**Best-effort, and loud about it.** A log write that fails (Postgres down,
network blip) prints a warning to stderr and the request completes exactly
as it would have otherwise — the log is observational history, not a second
enforcement gate. `BRAIN_RETRIEVAL_LOG` unset (or `off`, the default) means
the hooks are a single env-var check per call and never construct a store —
see [Backward compatibility](#backward-compatibility) for the same
zero-cost-when-off shape RBAC itself follows.

Query it via `GET /api/admin/retrievals` (owner-gated, same 404 discipline as
the rest of the [admin plane](#the-404-oracle-extended-to-the-admin-plane))
or the CLI:

```bash
brain-admin log query --principal fenn-desk
brain-admin log query --kind admin --since 2026-07-01
```

Both accept `--principal`, `--kind` (`read`/`write`/`admin`), `--tool`,
`--since`/`--until`, `--path` (filepath substring), and `--limit`. This needs
the same Postgres the pgvector store and Postgres credential backend use —
see [docs/auth.md: BRAIN_RETRIEVAL_LOG](auth.md#the-retrieval-log-brain_retrieval_log)
for the env var and [the compose recipe](recipes/full-stack-compose.md) for
a worked example.

`tests/test_retrieval_hooks.py` locks the hook sites (both surfaces, plus
"never on a forbidden or errored path"); `tests/test_retrieval_log_e2e.py`
is the acceptance story end to end — a restricted search, a write, and an
admin edit, each producing exactly the rows they should and nothing else.

## Backward compatibility

`mode = "none"` (the bundled `ace` profile's setting, and the default for any
profile that doesn't declare `[auth]` at all) makes every request resolve to
`OWNER` — `read_layers = write_layers = ("*",)` — before a single token is
even inspected. Since `ace` also declares no `visibility`-mode fields, both
gates in `visible()` short-circuit to `True` for every note, regardless of
frontmatter shape. `tests/test_ace_backward_compat.py` proves this directly:
`visible()` returns `True` for a range of note shapes (including notes that
happen to carry a stray `layer:` or `known_by:` key ace never declares) under
`OWNER`, and `handle_brain_read`/`handle_brain_query`/`handle_brain_write`
behave identically whether or not a `principal=` argument is passed at all —
the parameter default **is** `OWNER`, so no pre-RBAC caller needs to change.

## Running on Postgres (full-stack tier)

RBAC's coarse layer check is enforced by the store as well as by
`lib/visibility.py` — `search_chunks_in_layers` needs a real, current `layer`
column to deny across the board (see
[Re-indexing: populating `layer`](#re-indexing-populating-layer) above). That
holds regardless of which vector store backs the index. The Postgres/pgvector
full-stack tier (`kitchencoder/second-brain:full`, `BRAIN_VECTOR_STORE=pgvector`
+ `BRAIN_DATABASE_URL`) is a drop-in replacement for the embedded sqlite-vec
store — see the [compose recipe](recipes/full-stack-compose.md) for the
`docker-compose.yml` and env vars. Whichever store you run, re-index after
turning on `[auth.rbac]` so `layer` is populated before you rely on it.

## See also

- [docs/auth.md](auth.md) — the token/principal resolution layer this feature
  is built on (bearer tokens, OAuth 2.1, static principals).
- [docs/recipes/full-stack-compose.md](recipes/full-stack-compose.md) — running
  the full-stack (Postgres/pgvector) tier this page's store-side wall applies to,
  including minting agent tokens with `brain-admin`.
- `tools/lib/policy_edit.py` (`PolicyEditor`) — the only writer of policy;
  every role/identity/principal change is a git commit.
- `tools/brain_admin.py` — the `brain-admin` CLI (local + remote transports)
  documented in [Administering policy](#administering-policy) above.
- `tools/lib/retrieval_log.py` (`PgRetrievalLog`, `safe_log_*`) — the
  append-only per-principal log described in
  [The retrieval log](#the-retrieval-log) above.
- `tests/test_visibility_enforcement.py` — end-to-end enforcement tests across
  both the shared `handle_brain_*` handlers and the REST routes in
  `tools/brain_api.py`, plus the anti-drift signature checks that fail CI if a
  future content handler or REST route is added without the gate.
- `tests/test_ace_backward_compat.py` — the inertness proof summarized above.
- `tests/test_retrieval_hooks.py`, `tests/test_retrieval_log_e2e.py` — the
  retrieval log's hook-site coverage and end-to-end acceptance story.
