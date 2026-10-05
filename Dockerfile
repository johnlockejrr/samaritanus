# ---------- Stage 1: build the static frontend ----------
FROM node:20-slim AS webbuild
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci
COPY index.html vite.config.js postcss.config.js ./
COPY public ./public
COPY src ./src
RUN npm run build

# ---------- Stage 2: API + index + the built UI, one port ----------
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./
COPY scripts/build_index.py scripts/ensure_index.py ./scripts/
COPY data/verses.ndjson ./data/verses.ndjson
RUN python3 scripts/ensure_index.py \
 && rm -rf data/wlc data/strongs
COPY --from=webbuild /web/dist ./dist
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh \
 && groupadd -r app && useradd -r -g app -d /app -s /usr/sbin/nologin app \
 && chown -R app:app /app
USER app

ENV SEARCH_DB=/app/data/samaritanus.db \
    STATIC_DIR=/app/dist \
    PORT=8000 \
    PYTHONUNBUFFERED=1
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1
CMD ["/app/start.sh"]
