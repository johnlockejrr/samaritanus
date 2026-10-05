#!/usr/bin/env bash
# Build a deployable zip: built SPA + Python API + prebuilt SQLite index.
#
#   ./scripts/make_release.sh
#   ./scripts/make_release.sh --skip-frontend   # reuse existing dist/
#   ./scripts/make_release.sh --force-index     # rebuild data/samaritanus.db
#
# Output: release/samaritan-torah-search-<version>.zip
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

SKIP_FRONTEND=0
FORCE_INDEX=0
for arg in "$@"; do
  case "$arg" in
    --skip-frontend) SKIP_FRONTEND=1 ;;
    --force-index) FORCE_INDEX=1 ;;
    -h|--help)
      sed -n '2,10p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      exit 1
      ;;
  esac
done

VERSION="$(python3 -c "import json; print(json.load(open('package.json'))['version'])")"
NAME="samaritan-torah-search-${VERSION}"
OUT_DIR="${ROOT}/release"
STAGE="${OUT_DIR}/${NAME}"
ZIP="${OUT_DIR}/${NAME}.zip"

PY="${ROOT}/.venv/bin/python3"
if [[ ! -x "$PY" ]]; then
  PY="$(command -v python3)"
fi

echo "==> version ${VERSION}"

if [[ "$SKIP_FRONTEND" -eq 0 ]]; then
  echo "==> building frontend"
  if [[ ! -d node_modules ]]; then
    npm ci
  fi
  npm run build
else
  if [[ ! -f dist/index.html ]]; then
    echo "ERROR: dist/ missing; run without --skip-frontend" >&2
    exit 1
  fi
  echo "==> reusing existing dist/"
fi

echo "==> ensuring search index"
if [[ "$FORCE_INDEX" -eq 1 ]]; then
  "$PY" scripts/ensure_index.py --force
else
  "$PY" scripts/ensure_index.py
fi
if [[ ! -f data/samaritanus.db ]]; then
  echo "ERROR: data/samaritanus.db was not built" >&2
  exit 1
fi

echo "==> staging ${STAGE}"
rm -rf "$STAGE"
mkdir -p "$STAGE/data" "$STAGE/dist"

# Runtime layout matches the Docker image: Python modules at package root.
cp -a src/backend.py src/search.py src/security.py src/samaritan_aliases.py "$STAGE/"
cp -a requirements.txt .env.example start.sh "$STAGE/"
cp -a data/samaritanus.db "$STAGE/data/"
cp -a dist/. "$STAGE/dist/"
chmod +x "$STAGE/start.sh"

cat > "$STAGE/DEPLOY.md" <<EOF
# Samaritan Torah Search ${VERSION} — deploy package

Prebuilt web UI, Python API, and SQLite index. One process serves both on
port 8000.

## Run

\`\`\`bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
./start.sh
\`\`\`

Open http://localhost:8000. Health: http://localhost:8000/api/health

Copy \`.env.example\` to \`.env\` for production knobs (\`TRUST_PROXY\`,
\`RATE_LIMIT_PER_MINUTE\`, \`API_KEY\`, …). Optional: \`PORT\`, \`WEB_CONCURRENCY\`.

## Contents

| Path | Role |
|---|---|
| \`start.sh\` | gunicorn entrypoint |
| \`backend.py\` … | API + search |
| \`dist/\` | built SPA |
| \`data/samaritanus.db\` | search index (~11 MB) |
| \`requirements.txt\` | Python deps |

No Node.js, morphology downloads, or source rebuild steps are required on the
server.
EOF

echo "==> zipping"
mkdir -p "$OUT_DIR"
rm -f "$ZIP"
# zip from parent so the archive has a single top-level folder
(cd "$OUT_DIR" && zip -qr "${NAME}.zip" "$NAME")

SIZE="$(du -h "$ZIP" | awk '{print $1}')"
rm -rf "$STAGE"
echo
echo "Release ready: ${ZIP} (${SIZE})"
echo
echo "Deploy: unzip, pip install -r requirements.txt, ./start.sh"
