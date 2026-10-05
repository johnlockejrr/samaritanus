"""Samaritan Torah Search API (v0.2).

One SQLite file (built by scripts/build_index.py) answers every query.
Configuration is env-driven; see .env.example.
"""
from __future__ import annotations

import logging
import os
import re
import threading
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from search import BOOK_CODES, BOOK_ORDER, MODES, Index, consonantal
from security import attach as attach_limiter_backend
from security import install_security

logger = logging.getLogger("samaritanus")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

_FUZZ_TO_MODE = {0: "exact", 1: "lemma", 2: "substr"}
ENGLISH_BOOKS = {
    "GEN": "Genesis",
    "EXO": "Exodus",
    "LEV": "Leviticus",
    "NUM": "Numbers",
    "DEU": "Deuteronomy",
}
# OSHB writes "1254 a" and, for a few entries, "1008+".
_STRONGS = re.compile(r"^[0-9]{1,6}(?: ?[a-zA-Z])?\+?$")


def _env_bool(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


class Settings(BaseModel):
    max_query_length: int = 200
    max_page_size: int = 100
    docs_enabled: bool = False
    rate_limit_per_minute: int = 60
    trust_proxy: bool = False
    api_key: str | None = None
    search_cache_max_age: int = 60
    redis_url: str | None = None


class VerseOut(BaseModel):
    verse_id: str
    book_name: str
    chapter: int
    verse: int
    text: str
    matches: list[str]


class SearchOut(BaseModel):
    total: int
    page: int
    size: int
    total_pages: int
    has_more: bool
    mode: str
    order: str
    query: str
    normalized: str
    lemmas: list[dict[str, Any]] = Field(default_factory=list)
    forms: list[str] = Field(default_factory=list)
    # Per query word (phrases included). Single-word searches still fill lemmas/forms.
    terms: list[dict[str, Any]] = Field(default_factory=list)
    results: list[VerseOut]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        max_query_length=int(os.environ.get("MAX_QUERY_LENGTH", "200")),
        max_page_size=int(os.environ.get("MAX_PAGE_SIZE", "100")),
        docs_enabled=_env_bool("DOCS_ENABLED", "false"),
        rate_limit_per_minute=int(os.environ.get("RATE_LIMIT_PER_MINUTE", "60")),
        trust_proxy=_env_bool("TRUST_PROXY", "false"),
        api_key=os.environ.get("API_KEY") or None,
        search_cache_max_age=int(os.environ.get("SEARCH_CACHE_MAX_AGE", "60")),
        redis_url=os.environ.get("REDIS_URL") or None,
    )


def _db_path() -> Path:
    return Path(os.environ.get("SEARCH_DB", "data/samaritanus.db"))


_index_lock = threading.Lock()


def open_index(app_: FastAPI) -> Index | None:
    """Open the SQLite index once per process. Reopens if SEARCH_DB changes."""
    path = _db_path()
    with _index_lock:
        current = getattr(app_.state, "index", None)
        if current is not None and getattr(app_.state, "db_path", None) == str(path):
            return current
        if current is not None:
            current.db.close()
        app_.state.db_path = str(path)
        app_.state.index = None
        if not path.is_file():
            logger.error("Search index not found: %s. Run scripts/ensure_index.py.", path)
            return None
        try:
            app_.state.index = Index(path)
        except Exception:
            logger.exception("Failed to open search index %s", path)
            return None
        logger.info("Opened search index %s", path)
        return app_.state.index


@asynccontextmanager
async def lifespan(app_: FastAPI):
    open_index(app_)
    try:
        yield
    finally:
        ix = getattr(app_.state, "index", None)
        if ix is not None:
            ix.db.close()
            app_.state.index = None
            app_.state.db_path = None


settings = get_settings()
attach_limiter_backend(settings)

app = FastAPI(
    title="Samaritan Torah Search API",
    version="0.2.0",
    docs_url="/docs" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
    lifespan=lifespan,
)
install_security(app, get_settings)

_origins = [o.strip() for o in os.environ.get("CORS_ALLOW_ORIGINS", "").split(",") if o.strip()]
_credentials = _env_bool("CORS_ALLOW_CREDENTIALS", "false")
if "*" in _origins and _credentials:
    raise RuntimeError("CORS_ALLOW_CREDENTIALS cannot be used with the wildcard origin")
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=_credentials,
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    logger.info("CORS allowlist: %s (credentials=%s)", _origins, _credentials)


def get_index(request: Request) -> Index:
    ix = open_index(request.app)
    if ix is None:
        raise HTTPException(status_code=503, detail="Search index is not available")
    return ix


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


def _resolve_mode(mode: str | None, fuzziness: int | None) -> str:
    if mode is not None:
        return mode
    if fuzziness is not None:
        return _FUZZ_TO_MODE[fuzziness]
    return "lemma"


def _check_books(book: str | None) -> str | None:
    if not book:
        return None
    codes = [part.strip().upper() for part in book.split(",") if part.strip()]
    bad = [code for code in codes if code not in BOOK_CODES]
    if bad:
        raise HTTPException(status_code=400, detail=f"Unknown book code: {bad[0]}")
    return ",".join(codes)


@app.get("/api/search", response_model=SearchOut)
def search(
    request: Request,
    q: str = Query(..., min_length=1),
    mode: str | None = Query(None, description="exact, lemma, prefix, or substr"),
    fuzziness: int | None = Query(None, ge=0, le=2, description="legacy: 0 exact, 1 root, 2 contains"),
    order: Literal["canonical", "relevance"] = Query("canonical"),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1),
    book: str | None = Query(None, description="GEN, EXO, LEV, NUM, DEU; comma-separated"),
    strongs: str | None = Query(None, description="restrict Root match to one Strong's number"),
) -> SearchOut:
    cfg = get_settings()
    q = q.strip()
    if not q:
        raise HTTPException(status_code=422, detail="Query must contain non-whitespace characters")
    if len(q) > cfg.max_query_length:
        raise HTTPException(status_code=414, detail=f"Query exceeds {cfg.max_query_length} characters")
    size = min(size, cfg.max_page_size)
    chosen = _resolve_mode(mode, fuzziness)
    if chosen not in MODES:
        raise HTTPException(status_code=400, detail=f"mode must be one of {', '.join(MODES)}")
    book = _check_books(book)
    if strongs is not None and not _STRONGS.fullmatch(strongs):
        raise HTTPException(status_code=400, detail="Invalid Strong's number")

    ix = get_index(request)
    # A Strong's filter only means something once the query is a single lexeme.
    normalized = consonantal(q)
    tokens = [t for t in normalized.split() if t]
    lexeme = strongs if chosen == "lemma" and len(tokens) == 1 else None
    hits, total = ix.search(q, mode=chosen, order=order, page=page, size=size, book=book, strongs=lexeme)
    lemmas: list[dict[str, Any]] = []
    forms: list[str] = []
    terms: list[dict[str, Any]] = []
    if chosen == "lemma" and tokens:
        raw_parts = [part for part in q.split() if consonantal(part)]
        for raw in raw_parts:
            tok = consonantal(raw)
            term_lemmas = ix.lemma_of(tok)
            if lexeme and len(tokens) == 1:
                term_form_rows = ix.form_rows_for(lexeme)
            else:
                term_form_rows = ix.form_rows_of(tok)
            terms.append({
                "word": raw,
                "lemmas": term_lemmas,
                "forms": [row["form"] for row in term_form_rows],
                "form_rows": term_form_rows,
            })
        if len(tokens) == 1:
            lemmas = terms[0]["lemmas"]
            forms = terms[0]["forms"]
        else:
            # Flat lists for clients that ignore `terms`: union across the phrase.
            seen_s: set[str] = set()
            for term in terms:
                for lem in term["lemmas"]:
                    key = lem["strongs"]
                    if key not in seen_s:
                        seen_s.add(key)
                        lemmas.append(lem)
            seen_f: set[str] = set()
            for term in terms:
                for form in term["forms"]:
                    if form not in seen_f:
                        seen_f.add(form)
                        forms.append(form)

    total_pages = (total + size - 1) // size if total else 0
    return SearchOut(
        total=total,
        page=page,
        size=size,
        total_pages=total_pages,
        has_more=page < total_pages,
        mode=chosen,
        order=order,
        query=q,
        normalized=normalized,
        lemmas=lemmas,
        forms=forms,
        terms=terms,
        results=[
            VerseOut(
                **{
                    **h.__dict__,
                    "book_name": ENGLISH_BOOKS.get(h.verse_id.split(".", 1)[0], h.book_name),
                }
            )
            for h in hits
        ],
    )


@app.get("/api/forms")
def forms(request: Request, q: str = Query(..., min_length=1)) -> dict[str, Any]:
    q = q.strip()
    if not q:
        raise HTTPException(status_code=422, detail="Query must contain non-whitespace characters")
    ix = get_index(request)
    return {"query": q, "normalized": consonantal(q), "lemmas": ix.lemma_of(q), "forms": ix.forms_of(q)}


@app.get("/api/books")
def books(request: Request) -> list[dict[str, Any]]:
    ix = get_index(request)
    rows = ix.db.execute(
        """SELECT book_name,
                  substr(verse_id, 1, instr(verse_id, '.') - 1) AS code,
                  count(*) AS verses
             FROM verses GROUP BY code ORDER BY min(rowid)"""
    ).fetchall()
    found = []
    for row in rows:
        item = dict(row)
        item["book_name"] = ENGLISH_BOOKS.get(item["code"], item["book_name"])
        found.append(item)
    found.sort(key=lambda item: BOOK_ORDER.get(item["code"], 99))
    return found


@app.get("/api/health")
def health(request: Request) -> dict[str, Any]:
    ix = open_index(request.app)
    out: dict[str, Any] = {
        "status": "degraded",
        "verses": None,
        "index": getattr(request.app.state, "db_path", None),
    }
    if ix is None:
        return out
    try:
        n = ix.db.execute("SELECT count(*) FROM verses").fetchone()[0]
    except Exception as exc:
        logger.warning("Health check failed: %s", exc)
        return out
    meta = {key: value for key, value in ix.stats().items() if key != "verses"}
    out.update(status="ok", verses=n, **meta)
    return out


def _mount_spa() -> None:
    directory = os.environ.get("STATIC_DIR", "")
    if directory and os.path.isdir(directory):
        app.mount("/", StaticFiles(directory=directory, html=True), name="spa")
        logger.info("Serving the web UI from %s", directory)


_mount_spa()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
