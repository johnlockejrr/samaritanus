# Samaritan Torah Search

**v0.2** — search the Samaritan Pentateuch (5,841 verses) in the browser.

One process serves the page and the API. The index is one SQLite file with four
match modes: **Root** (same Strong's family: inflections and sole-source
derived nouns), Exact, Prefix, and Contains. The UI follows the
[Dicta Tanakh search](https://search.dicta.org.il/) layout; menus are in
English. The text is consonantal, so there are no vowel-point controls.

## Start the web UI

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
./dev.sh
```

Open http://127.0.0.1:5173. The repo includes a prebuilt
`data/samaritanus.db`; `./dev.sh` rebuilds it only if missing (or use
`python3 scripts/ensure_index.py --force` to regenerate from OSHB/Strong's).
Ctrl-C stops both processes. `npm start` runs the same script.

If `/api/health` is `degraded`, run `python3 scripts/ensure_index.py`. If ports
clash, stop the other process or set `PORT` for the API (UI stays on 5173).

## Production

```bash
docker compose up --build
```

Serves the SPA and API on http://localhost:8000. For Nginx/Traefik, env knobs,
and bare-metal zip deploys, see [DEPLOY.md](DEPLOY.md).

## Search API

`GET /api/search?q=ברא&mode=lemma&order=canonical&page=1&size=10`

| `mode` | Meaning |
|---|---|
| `lemma` | Root: same Strong's family. `ברא` finds `ויברא`; `ראש` finds `ראשית`. Not `בא` or `ברית`. |
| `exact` | Those consonants, or a phrase when the query has more than one word. |
| `prefix` | Words that start with the query. |
| `substr` | Words that contain it. |

Vocalized or cantillated queries are accepted: the server normalizes with NFKD
and strips marks so they match the consonantal index.

`order` is `canonical` (Genesis → Deuteronomy) or `relevance`.
`book` is `GEN`, `EXO`, `LEV`, `NUM`, `DEU`, or a comma-separated list.
`strongs` limits a root search to one Strong's number when a spelling has more
than one meaning. The legacy `fuzziness` query param still maps:
`0` → exact, `1` → lemma, `2` → substr.

Other routes: `/api/books`, `/api/forms?q=`, `/api/health`.

## Configuration

See [.env.example](.env.example). Nothing secret is required for a local run.
Useful knobs: `RATE_LIMIT_PER_MINUTE`, `TRUST_PROXY`, `API_KEY`,
`DOCS_ENABLED`, `SEARCH_CACHE_MAX_AGE`, and optional `REDIS_URL`
(`pip install -r requirements-redis.txt`).

## Rebuild the index

```bash
python3 scripts/ensure_index.py          # skip if data/samaritanus.db exists
python3 scripts/ensure_index.py --force  # rebuild
```

Corpus: `data/verses.ndjson`. Lemmas: OSHB, aligned by verse reference, with a
stem fallback for forms that have no lemma. Root families:
[openscriptures/strongs](https://github.com/openscriptures/strongs) sole-source
derivation links. A small Samaritan orthography table maps forms such as
`ראישון` → H7223 (`ראשון`). Both datasets are CC BY 4.0.

## Zip release (bare-metal deploy)

```bash
./scripts/make_release.sh
```

Writes `release/samaritan-torah-search-<version>.zip`. Details: [DEPLOY.md](DEPLOY.md).
Options: `--skip-frontend`, `--force-index`.

## GitHub Releases (web zip + Windows + Linux)

Push a version tag to build everything and attach it under
[Releases](https://github.com/johnlockejrr/samaritanus/releases):

```bash
# bump version in package.json / rust-app package + tauri.conf if needed, then:
git tag v0.2.1
git push origin v0.2.1
```

Or: Actions → **Release** → Run workflow → enter `v0.2.1`.

Each release includes the web deploy zip, Windows NSIS/MSI, Linux `.deb`/AppImage,
plus GitHub’s automatic Source code zip/tar.gz.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
npm test
```

## Layout

```
src/         FastAPI (backend.py), SQLite search (search.py), React UI
scripts/     build_index.py, ensure_index.py
data/        verses.ndjson + prebuilt samaritanus.db
dev.sh       local UI + API together
start.sh     container entrypoint (API + built SPA)
```

## License

MIT for this code. The Samaritan text and the OSHB morphology have their own terms.
