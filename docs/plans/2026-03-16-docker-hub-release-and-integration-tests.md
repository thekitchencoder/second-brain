# Docker Hub Release Pipeline + Integration Tests

**Date:** 2026-03-16
**Status:** Ready for implementation

---

## Goal

Prepare the `second-brain` project for public release on Docker Hub as `kitchencoder/second-brain`, with a GitHub Actions release pipeline and testcontainers-based integration tests that verify Phase 1 of the co-dependent confabulation roadmap.

---

## Section 1: GitHub Repo + Release Pipeline

### Repo

Create `thekitchencoder/second-brain` as a public GitHub repository via `gh repo create`.

### Version syncing

Version is sourced from the git tag (`v0.1.0` → `0.1.0`) and synced to:
- `pyproject.toml` — `version = "x.y.z"`
- `Dockerfile` — `LABEL version="x.y.z"`

A `scripts/sync-version.sh` script performs the sync. The GitHub Actions workflow calls it and commits the result back to the release branch.

### GitHub Actions workflow

File: `.github/workflows/docker-release.yml`

Triggers on `release: published`. Two jobs:

**sync-version:**
1. Extract version from tag (`v0.1.0` → `0.1.0`)
2. Update `pyproject.toml`
3. Run `scripts/sync-version.sh`
4. Commit and push back to release branch

**docker** (needs: sync-version):
1. Checkout updated code
2. Set up Docker Buildx
3. Log in to Docker Hub (`DOCKER_USERNAME=kitchencoder`, `DOCKER_PASSWORD` secret)
4. Extract metadata (semver tags + `latest`)
5. Build and push `docker.io/kitchencoder/second-brain` with tags: `latest`, `0.1`, `0.1.0`

### docker-compose.yml

Default profile uses the published image for end users:
```yaml
image: kitchencoder/second-brain:latest
```

Local dev overrides via `docker-compose.override.yml` (gitignored):
```yaml
services:
  vault:
    build: .
```

---

## Section 2: Integration Tests with testcontainers

### Fixture vault

Location: `tests/fixtures/vault/`

Minimal vault with known content designed to exercise Phase 1 roadmap criteria:

| File | Purpose |
|------|---------|
| `Projects/confabulation/context-co-dependent-confabulation.md` | Tagged `epistemic-lens`, `confabulation` — primary search target |
| `Sources/cognitive-debt-paper-summary.md` | Source doc linked from confabulation note |
| `Cards/strange-loops.md` | Related card — must appear in `vault_related` results |
| `templates/example.md` | Exists only to verify templates are NOT indexed |
| `.zk/config.toml` | Minimal config so zk recognises the vault root |

All fixture notes have complete frontmatter (type, status, created, tags).

### Test suite

File: `tests/test_integration.py`

Container scope: one container per test session. `vault-index run` executes once at session setup.

Tests (all marked `@pytest.mark.integration`):

| Test | Assertion |
|------|-----------|
| `test_search_returns_frontmatter` | `vault_search("co-dependent confabulation")` returns the context note with type, status, created, tags in output |
| `test_query_by_tag_epistemic_lens` | `vault_query(tag="epistemic-lens")` returns the confabulation note path |
| `test_related_deduplicates_by_file` | `vault_related(confabulation_note)` returns cognitive-debt and strange-loops as distinct files, not repeated chunks |
| `test_templates_not_indexed` | After indexing, no chunks exist with a filepath containing `/templates/` |

### testcontainers setup

- Builds (or pulls) the image, mounts `tests/fixtures/vault` as `/vault`
- Sets `EMBEDDING_BASE_URL` to point at Docker Model Runner (or skips if unavailable, marking tests as `xfail`)
- Runs `vault-index run` inside the container before tests begin
- Calls MCP handler functions via `docker exec` and asserts on stdout

### pytest configuration

`pyproject.toml`:
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["integration: requires Docker and a running embedding model"]
```

Run unit tests only: `pytest -m "not integration"`
Run integration tests: `pytest -m integration`

---

## Section 3: Files to Create/Modify

### New files

- `.github/workflows/docker-release.yml`
- `scripts/sync-version.sh`
- `docker-compose.override.yml` (gitignored)
- `tests/test_integration.py`
- `tests/fixtures/vault/Projects/confabulation/context-co-dependent-confabulation.md`
- `tests/fixtures/vault/Sources/cognitive-debt-paper-summary.md`
- `tests/fixtures/vault/Cards/strange-loops.md`
- `tests/fixtures/vault/templates/example.md`
- `tests/fixtures/vault/.zk/config.toml`

### Modified files

- `Dockerfile` — add `LABEL version="0.1.0"`
- `docker-compose.yml` — default to published image, document override pattern
- `pyproject.toml` — set version to `0.1.0`, add `testcontainers` dev dependency, add pytest markers config
- `requirements.txt` — add `testcontainers` (or keep in pyproject only)
- `.gitignore` — add `docker-compose.override.yml`

---

## Secrets Required

Set in GitHub repo settings before first release:
- `DOCKER_USERNAME` = `kitchencoder`
- `DOCKER_PASSWORD` = Docker Hub access token (not password)
