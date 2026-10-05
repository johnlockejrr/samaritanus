# Quickstart (v0.2)

## On your machine

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
./dev.sh
```

That is the only command you re-run afterwards. It starts the API and the page
together:

```
UI   http://127.0.0.1:5173
API  http://127.0.0.1:8000/api/health
```

The first run downloads Hebrew morphology and builds `data/samaritanus.db`.
Later runs reuse that file. Node.js 20+ is required; `./dev.sh` runs `npm ci`
when `node_modules` is missing.

Search `ברא` with Match set to **Root**.

## One container

```bash
docker compose up -d --build
curl -fsS localhost:8000/api/health
```

Open http://localhost:8000. The container serves the page and the API on that
port (no separate search server). Change the host port with `APP_PORT` in `.env`.

A healthy response looks like `{"status":"ok","verses":5841,...}`.

## If it fails

| Symptom | What to do |
|---|---|
| `Python dependencies are missing` | Activate the venv and `pip install -r requirements.txt`. |
| First `./dev.sh` stops while downloading | Check network access to GitHub, then run it again. |
| Port already in use | Stop the other process, or set `PORT` for the API. The page stays on 5173. |
| `/api/health` is `degraded` | Index missing. Run `python3 scripts/ensure_index.py`. |
