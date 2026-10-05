#!/bin/bash
# Serve the API and the built web UI on one port.
# Works from a release zip root and from the Docker image (/app).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

export SEARCH_DB="${SEARCH_DB:-$ROOT/data/samaritanus.db}"
export STATIC_DIR="${STATIC_DIR:-$ROOT/dist}"

if [[ ! -f "${SEARCH_DB}" ]]; then
  echo "ERROR: search index not found at ${SEARCH_DB}."
  echo "  Rebuild the image / release so the index is included, or set SEARCH_DB."
  exit 1
fi
if [[ ! -d "${STATIC_DIR}" ]]; then
  echo "ERROR: web UI not found at ${STATIC_DIR}."
  echo "  Run npm run build (or make_release.sh), or set STATIC_DIR."
  exit 1
fi

echo "Starting Samaritan Torah Search on port ${PORT:-8000} (API + web UI)..."
exec gunicorn \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-2}" \
  --worker-class uvicorn.workers.UvicornWorker \
  --timeout 30 \
  --graceful-timeout 10 \
  backend:app
