# Samaritan Torah Search — desktop (Tauri / Rust)

Windows-oriented desktop shell for the same UI as the web app. Search runs in
**Rust** against the SQLite index — no Python runtime in the packaged app.

## Layout

```
rust-app/
  src/                    React UI (same design as the web app)
  public/fonts/           Narkis Classic (personal use)
  search-engine/          Pure Rust port of search.py + aliases + API assembly
  src-tauri/
    src/lib.rs            Tauri commands: search, books, health
    resources/            Bundled samaritanus.db
```

## Prerequisites

- [Rust](https://rustup.rs/) (stable)
- Node.js 20+
- For **Windows builds**: run on Windows (or a Windows target) with
  [WebView2](https://developer.microsoft.com/microsoft-edge/webview2/) and the
  [Tauri Windows prerequisites](https://tauri.app/start/prerequisites/)
- For **Linux GUI**: webkit2gtk (see Tauri Linux prerequisites). On WSL without
  those libs you can still verify the search crate:

```bash
cargo test -p search-engine
```

## Setup

```bash
cd rust-app
npm install
# After rebuilding the parent index, refresh the bundled copy:
#   cp ../data/samaritanus.db src-tauri/resources/samaritanus.db
```

The search index is already at `src-tauri/resources/samaritanus.db` in the repo.

## Develop

```bash
npm run tauri:dev
```

## Build a Windows installer

On a Windows machine (or CI with a Windows runner):

```bash
npm run tauri:build
```

Artifacts land under `src-tauri/target/release/bundle/` (MSI / NSIS).

## Override the index path

```bash
SEARCH_DB=/path/to/samaritanus.db npm run tauri:dev
```

## Notes

- Index *building* (OSHB / Strong's download) stays in the parent Python
  scripts; this app only reads the finished DB.
- Narkis Classic fonts under `public/fonts/` are for personal use.
