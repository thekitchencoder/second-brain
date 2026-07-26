# Recipe: full-stack tier (Postgres/pgvector) with docker-compose

The full-stack tier runs the `:full` image beside Postgres+pgvector.
Vectors, and in later releases policy and audit data, live in Postgres —
one stateful service, one volume, one backup (`pg_dump`).

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
