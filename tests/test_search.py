"""Search API against a tiny fixture index. No network required."""
import os

from fastapi.testclient import TestClient

import backend


def _client():
    return TestClient(backend.app)


def test_root_match_finds_inflections_not_lookalikes():
    body = _client().get("/api/search", params={"q": "ברא", "mode": "lemma", "size": 10}).json()
    ids = [row["verse_id"] for row in body["results"]]
    assert ids == ["GEN.1.1", "GEN.1.21", "NUM.1.1"]
    assert "GEN.1.5" not in ids
    assert "GEN.15.18" not in ids
    assert body["mode"] == "lemma"
    assert body["total"] == 3
    assert any(lemma["strongs"] == "1254a" for lemma in body["lemmas"])
    assert "ויברא" in body["forms"]
    assert "ברית" not in body["forms"]


def test_root_match_follows_strongs_family():
    """ראש (H7218) and ראשית (H7225) share a sole-source Strong's root."""
    client = _client()
    rosh = client.get("/api/search", params={"q": "ראש", "mode": "lemma"}).json()
    ids = [row["verse_id"] for row in rosh["results"]]
    assert "GEN.2.10" in ids
    assert "GEN.1.1" in ids  # בראשית
    assert "בראשית" in rosh["forms"]
    assert "ברית" not in rosh["forms"]

    reshit = client.get("/api/search", params={"q": "בראשית", "mode": "lemma"}).json()
    assert "GEN.1.1" in [row["verse_id"] for row in reshit["results"]]
    assert "GEN.2.10" in [row["verse_id"] for row in reshit["results"]]
    assert "ראש" in reshit["forms"]


def test_samaritan_rishon_alias():
    """Samaritan ראישון maps to H7223; MT ראשון and ראש find it via Root."""
    client = _client()
    for q in ("ראשון", "ראישון", "ראש"):
        body = client.get("/api/search", params={"q": q, "mode": "lemma"}).json()
        ids = [row["verse_id"] for row in body["results"]]
        assert "GEN.8.13" in ids, q
    assert "הראישון" in client.get(
        "/api/search", params={"q": "ראשון", "mode": "lemma"}
    ).json()["forms"]
    # Exact keeps MT and Samaritan spellings apart.
    assert client.get("/api/search", params={"q": "ראשון", "mode": "exact"}).json()["total"] == 0


def test_exact_does_not_include_inflections():
    body = _client().get("/api/search", params={"q": "ברא", "mode": "exact"}).json()
    assert [row["verse_id"] for row in body["results"]] == ["GEN.1.1", "NUM.1.1"]
    assert "GEN.1.21" not in [row["verse_id"] for row in body["results"]]
    assert body["results"][0]["matches"] == ["ברא"]


def test_vocalized_and_cantillated_queries_strip_to_consonants():
    # בָּרָ֣א (qamats + munah) and וַיִּבְרָ֨א must match the same as ברא / ויברא.
    client = _client()
    vocalized = client.get("/api/search", params={"q": "בָּרָ֣א", "mode": "lemma"}).json()
    assert vocalized["normalized"] == "ברא"
    assert vocalized["total"] == 3
    assert [row["verse_id"] for row in vocalized["results"]] == ["GEN.1.1", "GEN.1.21", "NUM.1.1"]
    phrased = client.get(
        "/api/search", params={"q": "בְּרֵאשִׁ֖ית בָּרָ֣א", "mode": "exact"}
    ).json()
    assert phrased["normalized"] == "בראשית ברא"
    assert [row["verse_id"] for row in phrased["results"]] == ["GEN.1.1"]


def test_legacy_fuzziness_maps_to_root_and_contains():
    root = _client().get("/api/search", params={"q": "ברא", "fuzziness": 1}).json()
    assert root["mode"] == "lemma"
    assert root["total"] == 3
    broad = _client().get("/api/search", params={"q": "בר", "fuzziness": 2}).json()
    assert broad["mode"] == "substr"
    assert broad["total"] >= 3


def test_phrase_and_book_filter():
    phrase = _client().get("/api/search", params={"q": "ברא אלהים", "mode": "exact"}).json()
    assert [row["verse_id"] for row in phrase["results"]] == ["GEN.1.1"]
    exodus = _client().get("/api/search", params={"q": "אלהים", "book": "EXO"}).json()
    assert [row["verse_id"] for row in exodus["results"]] == ["EXO.20.1"]


def test_phrase_root_returns_per_word_meanings_and_forms():
    body = _client().get("/api/search", params={"q": "ברא אלהים", "mode": "lemma"}).json()
    assert body["total"] >= 1
    assert len(body["terms"]) == 2
    assert body["terms"][0]["word"] == "ברא"
    assert body["terms"][1]["word"] == "אלהים"
    assert any(lem["strongs"] == "1254a" for lem in body["terms"][0]["lemmas"])
    assert any(lem["strongs"] == "430" for lem in body["terms"][1]["lemmas"])
    assert "ויברא" in body["terms"][0]["forms"]
    assert body["lemmas"]  # flat union still filled
    assert body["forms"]


def test_strongs_accepts_oshb_spellings():
    client = _client()
    assert client.get("/api/search", params={"q": "ברא", "strongs": "1254 a"}).status_code == 200
    assert client.get("/api/search", params={"q": "ברא", "strongs": "1008+"}).status_code == 200
    assert client.get("/api/search", params={"q": "ברא", "strongs": "1254 a OR 1"}).status_code == 400


def test_strongs_narrows_a_homograph_query():
    client = _client()
    everything = client.get("/api/search", params={"q": "ברא", "mode": "lemma"}).json()
    assert everything["total"] == 3
    narrowed = client.get("/api/search", params={"q": "ברא", "mode": "lemma", "strongs": "1254a"}).json()
    assert [row["verse_id"] for row in narrowed["results"]] == ["GEN.1.1", "GEN.1.21"]
    assert client.get("/api/search", params={"q": "ברא", "strongs": "not a number"}).status_code == 400


def test_pagination_and_size_clamp():
    body = _client().get("/api/search", params={"q": "אלהים", "page": 1, "size": 1}).json()
    assert body["total"] == 3
    assert body["total_pages"] == 3
    assert body["has_more"] is True
    assert len(body["results"]) == 1
    huge = _client().get("/api/search", params={"q": "אלהים", "size": 5000}).json()
    assert huge["size"] == backend.get_settings().max_page_size


def test_validation():
    client = _client()
    assert client.get("/api/search", params={"q": "   "}).status_code == 422
    assert client.get("/api/search").status_code == 422
    assert client.get("/api/search", params={"q": "א" * 201}).status_code == 414
    assert client.get("/api/search", params={"q": "א", "mode": "fuzzy"}).status_code == 400
    assert client.get("/api/search", params={"q": "א", "book": "JOB"}).status_code == 400
    # Latin letters are not Hebrew; the query is accepted and matches nothing.
    assert client.get("/api/search", params={"q": "x"}).status_code == 200


def test_books_and_health():
    client = _client()
    books = client.get("/api/books").json()
    assert [row["code"] for row in books] == ["GEN", "EXO", "NUM"]
    assert books[-1]["book_name"] == "Numbers"
    numbered = client.get("/api/search", params={"q": "ברא", "book": "NUM"}).json()
    assert numbered["results"][0]["book_name"] == "Numbers"
    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert health["verses"] == 8


def test_missing_index_is_503(monkeypatch):
    monkeypatch.setenv("SEARCH_DB", os.path.join(os.path.dirname(__file__), "missing.db"))
    with TestClient(backend.app) as client:
        assert client.get("/api/search", params={"q": "ברא"}).status_code == 503
        assert client.get("/api/health").json()["status"] == "degraded"
