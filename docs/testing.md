# Testing

Two test suites, two environments.

## Unit tests (`task test`)

Runs all non-integration tests inside a throwaway Docker container. This is the default and gives full coverage, including the SQLite/sqlite-vec tests that can't run on macOS system Python.

```bash
task test
```

No setup needed beyond having the dev image built (`task build`).

You can also run unit tests directly on the host with `python3 -m pytest -m "not integration"`, but macOS system Python restricts `enable_load_extension`, so the db and index test suites will skip. The container run is the canonical one.

### What's tested

| Suite | File | What it covers |
|-------|------|----------------|
| Brain service | `tests/test_brain_service.py` | search, query, read, write, create, edit, trash, restore, backlinks |
| REST API | `tests/test_brain_api.py` | FastAPI endpoints, path traversal, input validation |
| Database | `tests/lib/test_db.py` | sqlite-vec init, upsert, search, delete, embeddings |
| Indexer | `tests/test_brain_index.py` | indexing, chunk dedup, watcher, stale path cleanup |
| MCP transport | `tests/test_mcp_transport.py` | server creation, tool registration, transport selection |
| Edit operations | `tests/lib/test_edit.py` | frontmatter updates, section edits, wikilink insertion |

### Dependencies

Unit tests use only standard library + what's in the Docker image. No extra packages needed on the host.

If running on the host directly (not via `task test`), you need `pytest` and the packages in `requirements.txt`. The db/index/mcp tests will skip due to macOS SQLite restrictions.

## Integration tests (`task test-integration`)

Spins up a real brain container via `testcontainers`, indexes the fixture brain against a live embedding model, and tests search, query, and related-note features end-to-end.

```bash
task test-integration
```

### Prerequisites

1. Docker running
2. Dev image built (`task build`)
3. Docker Model Runner running with an embedding model loaded
4. Host packages: `pip3 install testcontainers fastapi httpx`

### How it works

The test fixture lives in `tests/fixtures/vault/` — a small brain with three notes (a context primer, a card, and a source). The `brain_container` pytest fixture:

1. Starts a container from the dev image with the fixture brain mounted
2. Checks the embedding model is reachable (skips all tests if not)
3. Runs `brain-index run` to build the embeddings database
4. Yields the container for tests to exec commands against
5. Cleans up the generated `embeddings.db` from the fixture directory

### Embedding model

The default model is `ai/embeddinggemma:latest`. To use a different model:

```bash
task test-integration EMBEDDING_MODEL=your-model-name
```

The embedding URL defaults to `model-runner.docker.internal` (Docker's internal hostname for reaching the host from inside a container). This is correct for Docker Model Runner. If you're using a different embedding server, override `EMBEDDING_BASE_URL` in the task env or pass it directly.

Check what models are loaded:

```bash
curl http://localhost:12434/engines/llama.cpp/v1/models
```

### What's tested

| Test | What it verifies |
|------|------------------|
| `test_search_returns_confabulation_note_with_frontmatter` | Semantic search returns the right note with full frontmatter |
| `test_query_by_tag_returns_epistemic_lens_documents` | Tag-based query finds all matching documents |
| `test_related_returns_distinct_files_not_repeated_chunks` | Related notes are deduplicated (one entry per file, not per chunk) |
| `test_templates_not_indexed` | Template files in `templates/` are excluded from the search index |

## Test fixtures

The fixture brain (`tests/fixtures/vault/`) contains:

- `Efforts/confabulation/context-co-dependent-confabulation.md` — context primer with epistemic-lens tags
- `Cards/strange-loops.md` — a card tagged with epistemic-lens
- `Sources/cognitive-debt-paper-summary.md` — a source document

These are real-format notes with proper frontmatter, used by both unit and integration tests.

## Adding tests

- Unit tests go in `tests/` (or `tests/lib/` for lower-level modules)
- Mark integration tests with `@pytest.mark.integration`
- Tests that need `sqlite_vec` should include the `pytestmark` skip (see `test_db.py` for the pattern)
- The Python path includes `tools/` (set in `pyproject.toml`), so import directly: `from brain_index import index_file`
