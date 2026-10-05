# Production (v0.2) — one host, Nginx + TLS

One container serves the API and the built web UI. Nginx terminates TLS and
proxies to it. Put real settings in `.env`, not in the repository.

## 1. Start the app

```bash
docker compose up -d --build
curl -fsS localhost:8000/api/health
```

## 2. Settings behind a proxy

```text
TRUST_PROXY=true
RATE_LIMIT_PER_MINUTE=60
SEARCH_CACHE_MAX_AGE=60
DOCS_ENABLED=false
APP_PORT=8000
```

Then `docker compose up -d`.

`TRUST_PROXY=true` makes the rate limiter use the first `X-Forwarded-For` hop.
Set it only when Nginx is the only caller that can reach the container.

Optional API key on `/api/*` (health stays open): set `API_KEY` and send
`X-API-Key`. Optional shared rate limit across workers: install
`requirements-redis.txt` in a custom image and set `REDIS_URL`.

## 3. Nginx

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
