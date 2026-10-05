# Docker (v0.2)

One image, one container. It builds the React UI, builds the SQLite index from
`data/verses.ndjson` plus Open Scriptures Hebrew Bible morphology, and serves
the API and the SPA on port 8000.

```bash
docker compose up -d --build
curl -fsS localhost:8000/api/health
```

Open http://localhost:8000.

Optional `.env` (see `.env.example`):

```text
APP_PORT=8000
TRUST_PROXY=false
RATE_LIMIT_PER_MINUTE=60
API_KEY=
DOCS_ENABLED=false
```

The process runs as a non-root user. `/api/health` is the healthcheck. The index
is baked into the image; no extra data volume is required.

After a corpus or code change:

```bash
docker compose up -d --build
```
