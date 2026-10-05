# Deploy (production)

One container serves the API and the built web UI on port 8000.

```bash
docker compose up -d --build
curl -fsS localhost:8000/api/health
```

Open http://localhost:8000. Change the published port with `APP_PORT` in `.env`
(see [`.env.example`](.env.example)). The process runs as a non-root user; the
index is baked into the image.

Useful settings behind a reverse proxy:

```text
TRUST_PROXY=true
RATE_LIMIT_PER_MINUTE=60
SEARCH_CACHE_MAX_AGE=60
DOCS_ENABLED=false
APP_PORT=8000
```

`TRUST_PROXY=true` makes the rate limiter use the first `X-Forwarded-For` hop —
set it only when the proxy is the only caller that can reach the container.

Optional API key on `/api/*` (health stays open): set `API_KEY` and send
`X-API-Key`. Optional shared rate limit across workers: install
`requirements-redis.txt` in a custom image and set `REDIS_URL`.

Bare-metal (no Docker): `./scripts/make_release.sh`, unzip on the server,
`pip install -r requirements.txt`, then `./start.sh`.

## Nginx + TLS

```nginx
server {
    listen 443 ssl;
    server_name search.example.org;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

Bind the container to localhost when Nginx is on the same host:

```text
APP_PORT=127.0.0.1:8000
```

Compose maps `${APP_PORT:-8000}:8000`, so `127.0.0.1:8000` binds only on the host.

## Traefik

```text
DOMAIN=search.example.org
LE_EMAIL=admin@example.org
TRUST_PROXY=true
RATE_LIMIT_PER_MINUTE=60
DOCS_ENABLED=false
```

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

Do not add a second Content-Security-Policy on the proxy; the app already sends
security headers.
