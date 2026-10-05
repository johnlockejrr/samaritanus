# Production (v0.2) — Traefik

The app container serves the API and the web UI on port 8000. Traefik terminates
TLS and routes to it. Settings live in `.env`.

## 1. Environment

```text
DOMAIN=search.example.org
LE_EMAIL=admin@example.org
APP_PORT=8000
TRUST_PROXY=true
RATE_LIMIT_PER_MINUTE=60
DOCS_ENABLED=false
```

## 2. Compose

Save as `docker-compose.traefik.yml` next to the Dockerfile:

```yaml
services:
  traefik:
    image: traefik:v3.1
    command:
      - --providers.docker=true
      - --providers.docker.exposedbydefault=false
      - --entrypoints.web.address=:80
      - --entrypoints.websecure.address=:443
      - --certificatesresolvers.le.acme.email=${LE_EMAIL}
      - --certificatesresolvers.le.acme.storage=/letsencrypt/acme.json
      - --certificatesresolvers.le.acme.httpchallenge.entrypoint=web
    ports: ["80:80", "443:443"]
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - traefik_certs:/letsencrypt
    networks: [edge]

  app:
    build: .
    env_file: .env
    environment:
      TRUST_PROXY: "true"
      STATIC_DIR: /app/dist
      SEARCH_DB: /app/data/samaritanus.db
    labels:
      - traefik.enable=true
      - traefik.http.routers.app.rule=Host(`${DOMAIN}`)
      - traefik.http.routers.app.entrypoints=websecure
      - traefik.http.routers.app.tls.certresolver=le
      - traefik.http.services.app.loadbalancer.server.port=8000
      - traefik.http.routers.http.rule=Host(`${DOMAIN}`)
      - traefik.http.routers.http.entrypoints=web
      - traefik.http.routers.http.middlewares=https-redirect
      - traefik.http.middlewares.https-redirect.redirectscheme.scheme=https
      - traefik.http.middlewares.ratelimit.ratelimit.average=60
      - traefik.http.middlewares.ratelimit.ratelimit.burst=120
      - traefik.http.routers.app.middlewares=ratelimit
      - traefik.http.routers.app.service=app
    networks: [edge]

volumes: { traefik_certs: }
networks:
  edge: {}
```

```bash
docker compose -f docker-compose.traefik.yml up -d --build
curl -fsS https://search.example.org/api/health
```

`TRUST_PROXY=true` is required so the app sees HTTPS and the client IP. The app
already sends security headers; do not add a second content-security policy on
the proxy. For one shared rate counter across workers, set `REDIS_URL`.
