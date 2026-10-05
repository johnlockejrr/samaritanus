"""Tests for the production security layer (rate limiting, headers, API key).

Uses the pure RateLimiter class for deterministic timing and TestClient for the
middleware contract. Rate limiting is off by default (conftest) so functional
tests never trip it.
"""
import os

from fastapi.testclient import TestClient

import backend
import security


# --- RateLimiter (pure, no globals) ---
def test_rate_limiter_blocks_after_limit():
    rl = security.RateLimiter()
    now = 1000.0
    assert all(rl.allow("ip", 3, now=now) for _ in range(3))
    assert rl.allow("ip", 3, now=now) is False  # 4th within window blocked


def test_rate_limiter_window_expiry():
    rl = security.RateLimiter()
    assert all(rl.allow("ip", 2, window=60.0, now=0.0) for _ in range(2))
    assert rl.allow("ip", 2, window=60.0, now=59.0) is False
    assert rl.allow("ip", 2, window=60.0, now=61.0) is True  # window passed


def test_rate_limiter_is_per_key():
    rl = security.RateLimiter()
    assert rl.allow("a", 1)
    assert rl.allow("a", 1) is False
    assert rl.allow("b", 1) is True  # other client unaffected


def test_rate_limiter_zero_disables():
    rl = security.RateLimiter()
    assert all(rl.allow("ip", 0) for _ in range(500))


def _req(remote, xff):
    class _Client:
        host = remote

    class _Req:
        client = _Client()
        headers = {} if xff is None else {"x-forwarded-for": xff}

        def get_header(self, k):  # pragma: no cover - parity helper
            return self.headers.get(k)

    return _Req()


def test_client_ip_trust_proxy_flag():
    # without trust_proxy the socket peer wins, even if XFF is spoofed
    assert security._client_ip(_req("1.2.3.4", "9.9.9.9"), False) == "1.2.3.4"
    # with trust_proxy behind a LB the first XFF hop is used
    assert security._client_ip(_req("1.2.3.4", "9.9.9.9"), True) == "9.9.9.9"
    # trust_proxy on but no XFF header -> falls back to peer
    assert security._client_ip(_req("1.2.3.4", None), True) == "1.2.3.4"


# --- middleware contract via TestClient ---
def _client(monkeypatch):
    return TestClient(backend.app)


def test_security_headers_present(monkeypatch):
    r = _client(monkeypatch).get("/api/search", params={"q": "x"})
    assert r.status_code == 200
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert "frame-ancestors" in r.headers["content-security-policy"]
    assert r.headers["referrer-policy"] == "no-referrer"


def test_request_id_echoed(monkeypatch):
    r = _client(monkeypatch).get("/api/search", params={"q": "x"}, headers={"x-request-id": "abc123"})
    assert r.headers["x-request-id"] == "abc123"


def test_api_cache_control(monkeypatch):
    r = _client(monkeypatch).get("/api/search", params={"q": "x"})
    assert "max-age=" in r.headers["cache-control"]


def test_health_is_not_cached(monkeypatch):
    r = _client(monkeypatch).get("/api/health")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"


def test_csp_constant_has_hardening_directives():
    for d in ("default-src", "base-uri", "object-src", "frame-ancestors", "script-src"):
        assert d in security.CSP
    assert "unsafe-inline" not in security.CSP.split("script-src")[1].split(";")[0]


def test_api_key_gating(monkeypatch):
    os.environ["API_KEY"] = "s3cr3t"
    backend.get_settings.cache_clear()
    try:
        c = _client(monkeypatch)
        assert c.get("/api/search", params={"q": "x"}).status_code == 401
        assert c.get("/api/search", params={"q": "x"}, headers={"x-api-key": "wrong"}).status_code == 401
        assert c.get("/api/search", params={"q": "x"}, headers={"x-api-key": "s3cr3t"}).status_code == 200
        # health stays open for monitoring/load-balancers
        assert c.get("/api/health").status_code == 200
    finally:
        del os.environ["API_KEY"]
        backend.get_settings.cache_clear()


def test_rate_limit_returns_429(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "2")
    backend.get_settings.cache_clear()
    security._limiter.reset()
    try:
        c = _client(monkeypatch)
        codes = [c.get("/api/search", params={"q": "x"}).status_code for _ in range(4)]
        assert codes[:2] == [200, 200]
        assert 429 in codes
        assert c.get("/api/search", params={"q": "x"}).headers.get("retry-after") == "60"
    finally:
        backend.get_settings.cache_clear()
        security._limiter.reset()


# --- Redis backend (hermetic: fake client, no server / no redis package required) ---
class FakePipe:
    def __init__(self, store):
        self._store = store
        self._ops = []

    def incr(self, k):
        self._ops.append(("incr", k))
        return self

    def expire(self, k, t):
        self._ops.append(("expire", k))
        return self

    def execute(self):
        out = []
        for op, k in self._ops:
            if op == "incr":
                self._store[k] = self._store.get(k, 0) + 1
                out.append(self._store[k])
            else:
                out.append(True)
        return out


class FakeRedis:
    def __init__(self):
        self.store = {}

    def pipeline(self):
        return FakePipe(self.store)


def test_redis_limiter_counts_and_blocks_within_window():
    fr = FakeRedis()
    rl = security.RedisRateLimiter("redis://does-not-matter", client=fr)
    assert [rl.allow("ip", 2, now=1000.0) for _ in range(2)] == [True, True]
    assert rl.allow("ip", 2, now=1000.0) is False  # 3rd in same window blocked


def test_redis_limiter_new_window_allows_again():
    fr = FakeRedis()
    rl = security.RedisRateLimiter("redis://does-not-matter", client=fr)
    assert rl.allow("ip", 1, window=60.0, now=1000.0) is True
    assert rl.allow("ip", 1, window=60.0, now=1000.0) is False
    assert rl.allow("ip", 1, window=60.0, now=1060.0) is True  # next minute bucket


def test_redis_limiter_zero_disables():
    rl = security.RedisRateLimiter("redis://x", client=FakeRedis())
    assert all(rl.allow("ip", 0) for _ in range(50))


def test_attach_noop_without_redis_url(monkeypatch):
    before = security.get_limiter()
    security.attach(type("S", (), {"redis_url": None})())
    assert security.get_limiter() is before  # stays in-memory


def test_attach_falls_back_if_redis_unavailable(monkeypatch):
    def boom(url):
        raise ImportError("no redis lib")
    monkeypatch.setattr(security, "RedisRateLimiter", boom)
    original = security._limiter
    security.attach(type("S", (), {"redis_url": "redis://x"})())
    assert security.get_limiter() is original  # graceful fallback to memory
    security._active_limiter = original
