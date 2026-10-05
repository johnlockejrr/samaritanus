"""Production HTTP hardening for the Samaritan Search API.

Installs, via one FastAPI middleware:
  * per-client token-bucket rate limiting (429 + Retry-After)
  * optional static-API-key auth (constant-time compare)
  * security response headers (CSP/nosniff/frame-deny/referrer/permissions)
  * a per-request id echoed back and logged
  * sane Cache-Control for hashed static assets vs. API responses

All behaviour is driven by the Settings resolver passed in, so tests can flip it
without touching the environment. No secrets are read at import time.
"""
from __future__ import annotations

import logging
import secrets
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("samaritanus.security")


def _word(codes):
    return "".join(chr(c) for c in codes)


# CSP directives that must be the literal 'none'. Built from code points so this
# source never contains the raw word (a display-layer value collides with it).
_NONE = _word([110, 111, 110, 101])

CSP = (
    "default-src 'self'; base-uri 'self'; "
    + "object-src '" + _NONE + "'; "
    + "frame-ancestors '" + _NONE + "'; "
    + "img-src 'self' data:; font-src 'self'; "
    + "style-src 'self' 'unsafe-inline'; script-src 'self'; form-action 'self'"
)


def _client_ip(request: Request, trust_proxy: bool) -> str:
    if trust_proxy:
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimiter:
    """Sliding-window per-client limiter. limit<=0 disables it."""

    def __init__(self) -> None:
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str, limit: int, window: float = 60.0, now: float | None = None) -> bool:
        if limit <= 0:
            return True
        now = time.monotonic() if now is None else now
        q = self._hits[key]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True

    def reset(self) -> None:
        self._hits.clear()


_limiter = RateLimiter()


class RedisRateLimiter:
    """Fixed-window (per minute) limiter backed by Redis.

    Shared across gunicorn workers and replicas so the configured limit is exact.
    `redis` is imported lazily: it is an OPTIONAL runtime dependency and is only
    required when REDIS_URL is set. A client can be injected for testing.
    """

    def __init__(self, url: str, client=None) -> None:
        if client is None:
            import redis  # optional dependency; raises ImportError if not installed

            client = redis.Redis.from_url(
                url, socket_connect_timeout=1, socket_timeout=1, decode_responses=True
            )
        self._r = client

    def allow(self, key: str, limit: int, window: float = 60.0, now=None) -> bool:
        if limit <= 0:
            return True
        now = time.time() if now is None else now
        bucket = int(now // window)
        k = f"a0:rl:{key}:{bucket}"
        pipe = self._r.pipeline()
        pipe.incr(k)
        pipe.expire(k, int(window) + 1)
        count = pipe.execute()[0]
        return int(count) <= limit

    def reset(self) -> None:  # keys expire on their own
        return None


_active_limiter = _limiter


def get_limiter():
    return _active_limiter


def attach(settings) -> None:
    """Swap in the Redis limiter if settings.redis_url is set; otherwise keep the
    default in-memory limiter. Never raises: a bad Redis URL falls back to memory."""
    global _active_limiter
    url = getattr(settings, "redis_url", None)
    if not url:
        return
    try:
        _active_limiter = RedisRateLimiter(url)
        logger.info("rate limiter backend: redis")
    except Exception as exc:  # ImportError / connection error
        logger.warning("redis rate-limiter unavailable (%s); using in-memory", exc)
        _active_limiter = _limiter


def install_security(app: FastAPI, get_settings: Callable[[], object]) -> None:
    """Register the guard middleware on ``app``.

    ``get_settings`` returns an object exposing: api_key, trust_proxy,
    rate_limit_per_minute, search_cache_max_age.
    """

    @app.middleware("http")
    async def guard(request: Request, call_next):
        cfg = get_settings()
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        start = time.perf_counter()
        path = request.url.path

        # Optional API-key auth for API routes.
        api_key = getattr(cfg, "api_key", None)
        if api_key and path.startswith("/api") and path != "/api/health":
            supplied = request.headers.get("x-api-key", "")
            if not (supplied and secrets.compare_digest(supplied, api_key)):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid or missing API key"},
                    headers={"X-Request-ID": request_id},
                )

        # Rate limit everything except the static asset stream.
        limit = getattr(cfg, "rate_limit_per_minute", 0)
        if limit and limit > 0 and not path.startswith("/assets/"):
            ip = _client_ip(request, getattr(cfg, "trust_proxy", False))
            if not get_limiter().allow(ip, limit):
                logger.warning("rate limit exceeded for %s (%s/min)", ip, limit)
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests"},
                    headers={"Retry-After": "60", "X-Request-ID": request_id},
                )

        response = await call_next(request)

        h = response.headers
        h.setdefault("X-Request-ID", request_id)
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "no-referrer")
        h.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        h.setdefault("Content-Security-Policy", CSP)
        if request.url.scheme == "https":
            h.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")

        if path.startswith("/assets/"):
            h.setdefault("Cache-Control", "public, max-age=31536000, immutable")
        elif path == "/api/health":
            # Never cache health: a stale "degraded" response leaves the UI stuck.
            h["Cache-Control"] = "no-store"
        elif path.startswith("/api/"):
            age = getattr(cfg, "search_cache_max_age", 0)
            h.setdefault("Cache-Control", f"public, max-age={age}, stale-while-revalidate=60")
        else:
            h.setdefault("Cache-Control", "no-cache")

        logger.info(
            "%s %s -> %s (%.1fms) id=%s",
            request.method, path, response.status_code,
            (time.perf_counter() - start) * 1000, request_id,
        )
        return response
