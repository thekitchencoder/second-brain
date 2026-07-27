# Recipe: full-stack tier (Postgres/pgvector) with docker-compose

The full-stack tier runs the `:full` image beside Postgres+pgvector.
Vectors live in Postgres, and — if you opt into
`BRAIN_POLICY_CREDENTIALS: postgres` — so do agent-token credentials.
Policy itself (roles, principal→role mappings) always stays in the profile
repo as git commits; Postgres never becomes a second source of policy
truth. One stateful service, one volume, one backup (`pg_dump`).

```yaml
# docker-compose.yml
services:
  postgres:
    image: pgvector/pgvector:pg17
    environment:
      POSTGRES_USER: brain
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set in .env}
      POSTGRES_DB: brain
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U brain -d brain"]
      interval: 5s
      timeout: 3s
      retries: 10

  brain:
    image: kitchencoder/second-brain:full
    depends_on:
      postgres:
        condition: service_healthy
    volumes:
      - /path/to/your/brain:/brain
    ports:
      - "7779:7779"
      - "7780:7780"
    environment:
      BRAIN_VECTOR_STORE: pgvector
      BRAIN_DATABASE_URL: postgresql://brain:${POSTGRES_PASSWORD}@postgres:5432/brain
      BRAIN_POLICY_CREDENTIALS: postgres

volumes:
  pgdata:
```

```bash
echo "POSTGRES_PASSWORD=$(openssl rand -hex 16)" > .env
docker compose up -d
docker compose exec brain brain-index run   # populate the index
```

Switching an existing brain from the embedded store: nothing to
migrate — notes are the source of truth. Start the stack and reindex;
`<brain>/.ai/embeddings.db` simply stops being read.

## Minting your first agent token

`BRAIN_POLICY_CREDENTIALS: postgres` above turns on the Postgres-backed
agent-token credential store (`agent_tokens` table) — see
[docs/auth.md](../auth.md#agent-token-credential-backends-brain_policy_credentials).
Policy itself (roles, principal→role mappings) still lives in the profile
repo, not in Postgres — mint a token only after the principal is mapped to a
role:

```bash
docker compose exec brain brain-admin role set maker --read '*' --write '*'
docker compose exec brain brain-admin principal set fenn-desk maker
docker compose exec brain brain-admin token mint fenn-desk
# prints the plaintext token exactly once — save it, it is not shown again
```

Give that token to the agent as a standard bearer credential
(`Authorization: Bearer <token>`) against the REST API or MCP HTTP
transport. See [docs/rbac.md](../rbac.md#administering-policy) for the full
`brain-admin` reference, including remote (non-`docker exec`) usage and
revocation.
