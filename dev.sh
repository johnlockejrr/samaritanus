#!/usr/bin/env bash
# One command for the web UI: builds the index if needed, then starts the API
# and the Vite dev server together. Ctrl-C stops both.
set -euo pipefail
cd "$(dirname "$0")"

if [[ -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

PY="${PYTHON:-python3}"
if ! "$PY" -c "import fastapi, uvicorn" >/dev/null 2>&1; then
  echo "Python dependencies are missing. From this directory:"
  echo "  python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

"$PY" scripts/ensure_index.py

if [[ ! -d node_modules ]]; then
  npm ci
fi

API_PID=""
cleanup() {
  if [[ -n "${API_PID}" ]]; then
    kill "${API_PID}" 2>/dev/null || true
    wait "${API_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

PORT="${PORT:-8000}"
export SEARCH_DB="${SEARCH_DB:-$PWD/data/samaritanus.db}"
unset STATIC_DIR || true

"$PY" -m uvicorn backend:app --app-dir src --host 127.0.0.1 --port "${PORT}" &
API_PID=$!

ready=0
for _ in $(seq 1 50); do
  if "$PY" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${PORT}/api/health', timeout=1)" >/dev/null 2>&1; then
    ready=1
    break
  fi
  if ! kill -0 "${API_PID}" 2>/dev/null; then
    echo "The API exited before it was ready."
    exit 1
  fi
  sleep 0.1
done
if [[ "${ready}" -ne 1 ]]; then
  echo "The API did not answer /api/health on port ${PORT}."
  exit 1
fi

echo ""
echo "  Samaritan Torah Search"
echo "  UI   http://127.0.0.1:5173"
echo "  API  http://127.0.0.1:${PORT}/api/health"
echo ""

npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
