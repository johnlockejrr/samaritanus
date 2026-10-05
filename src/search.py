#!/usr/bin/env python3
"""
search.py — search the Samaritan Pentateuch index built by build_index.py.

One SQLite file, opened read-only. Four modes:

  exact    the consonantal form. ברא finds ברא and nothing else.

  lemma    Root match: every form of the same Strong's family.
           Inflections of the same OSHB lexeme, plus sole-source derived
           lexemes (ראש → ראשית). Dual-etymology lookalikes stay apart
           (ברא does not find ברית).

  prefix   anything starting with the query.

  substr   anything containing the query.

Used as a library:

    from search import Index
    ix = Index("data/samaritanus.db")
    hits, total = ix.search("ברא", mode="lemma", order="canonical")
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

from samaritan_aliases import alias_strongs

FINALS = str.maketrans("ךםןףץ", "כמנפצ")
BOOK_ORDER = {"GEN": 1, "EXO": 2, "LEV": 3, "NUM": 4, "DEU": 5}
MODES = ("exact", "lemma", "prefix", "substr")
BOOK_CODES = frozenset(BOOK_ORDER)


def _book_codes(book: str | None) -> set[str] | None:
    """None means every book. Accepts one code or a comma-separated list."""
    if not book:
        return None
    return {part.strip().upper() for part in book.split(",") if part.strip()}


def consonantal(s: str) -> str:
    """Reduce Hebrew to consonants so queries match the consonantal index.

    Accepts vocalized and cantillated text: NFKD, drop combining marks (nikkud,
    te'amim), keep letters (and spaces for phrases), fold final forms.
    """
    s = s.replace("/", "")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\u05d0-\u05ea\s]", " ", s)
    return " ".join(w.translate(FINALS) for w in s.split())


@dataclass
class Hit:
    verse_id: str
    book_name: str
    chapter: int
    verse: int
    text: str
    matches: list[str]          # the surface forms that matched, for highlighting


class Index:
    def __init__(self, path: str | Path):
        self.db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
        self.db.row_factory = sqlite3.Row

    # ---------------------------------------------------------------- meta
    def stats(self) -> dict:
        return {r["key"]: r["value"] for r in self.db.execute("SELECT * FROM meta")}

    def lemma_of(self, word: str) -> list[dict]:
        """Which lexemes a written form belongs to. More than one means a homograph."""
        n = consonantal(word)
        rows = self.db.execute(
            """SELECT DISTINCT w.strongs, l.display, l.n_forms, l.n_occur
                 FROM words w JOIN lemmas l ON l.strongs = w.strongs
                WHERE w.norm = ? ORDER BY l.n_occur DESC""", (n,)).fetchall()
        if rows:
            return [dict(r) for r in rows]
        aliased = alias_strongs(n)
        if not aliased:
            return []
        row = self.db.execute(
            "SELECT strongs, display, n_forms, n_occur FROM lemmas WHERE strongs = ?",
            (aliased,)).fetchone()
        if row:
            return [dict(row)]
        return [{"strongs": aliased, "display": n, "n_forms": 0, "n_occur": 0}]

    def forms_of(self, word: str) -> list[str]:
        """Every written form in the Root family of this spelling."""
        return [row["form"] for row in self.form_rows_of(word)]

    def form_rows_of(self, word: str) -> list[dict]:
        """Written forms with occurrence counts for the Root family."""
        related = self._expand_strongs(self._strongs_for_norm(consonantal(word)))
        if not related:
            return []
        qs = ",".join("?" * len(related))
        return self._form_rows(f"strongs IN ({qs})", tuple(related))

    # -------------------------------------------------------------- search
    def forms_for(self, strongs: str) -> list[str]:
        """Written forms of one Strong's family, as the text spells them."""
        return [row["form"] for row in self.form_rows_for(strongs)]

    def form_rows_for(self, strongs: str) -> list[dict]:
        related = self._expand_strongs([strongs])
        qs = ",".join("?" * len(related))
        return self._form_rows(f"strongs IN ({qs})", tuple(related))

    def _strongs_for_norm(self, nq: str) -> list[str]:
        """OSHB lemma keys for a consonantal query, including orthography aliases."""
        matched = [r["strongs"] for r in self.db.execute(
            "SELECT DISTINCT strongs FROM words WHERE norm = ? AND strongs IS NOT NULL",
            (nq,))]
        if matched:
            return matched
        aliased = alias_strongs(nq)
        return [aliased] if aliased else []

    def _expand_strongs(self, keys: list[str]) -> list[str]:
        """OSHB lemma keys in the same sole-source Strong's family.

        Falls back to the keys themselves when strongs_expand is absent
        (older indexes) or has no row for a key.
        """
        if not keys:
            return []
        out: list[str] = []
        seen: set[str] = set()
        has_table = self.db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='strongs_expand'"
        ).fetchone()
        for key in keys:
            related: list[str] = []
            if has_table:
                related = [r["related"] for r in self.db.execute(
                    "SELECT related FROM strongs_expand WHERE strongs = ?", (key,))]
            if not related:
                related = [key]
            for item in related:
                if item not in seen:
                    seen.add(item)
                    out.append(item)
        return out

    def _form_rows(self, where: str, params: tuple) -> list[dict]:
        rows = self.db.execute(
            f"""SELECT surface AS form, n FROM (
                    SELECT surface, norm, count(*) AS n,
                           row_number() OVER (
                             PARTITION BY norm
                             ORDER BY count(*) DESC, length(surface), surface
                           ) AS rn
                      FROM words WHERE {where}
                      GROUP BY surface, norm
                ) WHERE rn = 1
                ORDER BY n DESC, length(norm), norm""", params).fetchall()
        return [dict(r) for r in rows]

    def _surfaces(self, where: str, params: tuple) -> list[str]:
        return [row["form"] for row in self._form_rows(where, params)]

    def search(self, q: str, mode: str = "lemma", order: str = "canonical",
               page: int = 1, size: int = 20, book: str | None = None,
               strongs: str | None = None) -> tuple[list[Hit], int]:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        nq = consonantal(q)
        if not nq:
            return [], 0

        # A multi-word query is a phrase in every mode. Lemma/prefix/substr
        # apply to a single written form; a phrase has no single lexeme.
        if " " in nq:
            return self._phrase(nq, order, page, size, book)

        where, params = self._word_predicate(nq, mode, strongs)
        if where is None:
            return [], 0

        sql = f"""
            SELECT w.verse_id, group_concat(DISTINCT w.surface) AS matches
              FROM words w WHERE {where}
          GROUP BY w.verse_id"""
        rows = self.db.execute(sql, params).fetchall()
        by_verse = {r["verse_id"]: r["matches"].split(",") for r in rows}
        return self._materialise(by_verse, order, page, size, book, nq)

    def _word_predicate(self, nq: str, mode: str, strongs: str | None = None):
        if mode == "exact":
            return "w.norm = ?", (nq,)
        if mode == "prefix":
            return "w.norm LIKE ? ESCAPE '\\'", (self._like(nq) + "%",)
        if mode == "substr":
            return "w.norm LIKE ? ESCAPE '\\'", ("%" + self._like(nq) + "%",)
        # lemma / Root: Strong's family of the query form (or of a picked meaning)
        if strongs:
            related = self._expand_strongs([strongs])
        else:
            related = self._expand_strongs(self._strongs_for_norm(nq))
        if related:
            qs = ",".join("?" * len(related))
            return f"w.strongs IN ({qs})", tuple(related)
        # the query form has no lemma: fall back to exact, not to nonsense
        return "w.norm = ?", (nq,)

    @staticmethod
    def _like(s: str) -> str:
        return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def _phrase(self, nq: str, order, page, size, book):
        """A multi-word query, matched as a phrase over the consonantal text."""
        rows = self.db.execute(
            "SELECT verse_id FROM verses WHERE norm MATCH ?",
            ('"' + nq.replace('"', " ") + '"',)).fetchall()
        by_verse = {r["verse_id"]: nq.split() for r in rows}
        return self._materialise(by_verse, order, page, size, book, nq)

    def _materialise(self, by_verse: dict[str, list[str]], order, page, size,
                     book: str | None, nq: str):
        if not by_verse:
            return [], 0
        ids = list(by_verse)
        qs = ",".join("?" * len(ids))
        sql = f"""SELECT verse_id, book, book_name, chapter, verse, text
                    FROM verses WHERE verse_id IN ({qs})"""
        params = list(ids)
        rows = [dict(r) for r in self.db.execute(sql, params)]
        codes = _book_codes(book)
        if codes:
            rows = [r for r in rows if r["verse_id"].split(".")[0] in codes]

        if order == "relevance":
            # more matching tokens first, then canonical. With one lexeme per
            # query there is no meaningful tf-idf to compute, and verse order
            # is what a reader of a Pentateuch actually wants as the tiebreak.
            rows.sort(key=lambda r: (-len(by_verse[r["verse_id"]]),
                                     self._canon(r["verse_id"])))
        else:
            rows.sort(key=lambda r: self._canon(r["verse_id"]))

        total = len(rows)
        start = (page - 1) * size
        page_rows = rows[start:start + size]
        hits = [Hit(r["verse_id"], r["book_name"], int(r["chapter"]), int(r["verse"]),
                    r["text"], sorted(set(by_verse[r["verse_id"]])))
                for r in page_rows]
        return hits, total

    @staticmethod
    def _canon(vid: str):
        b, c, v = vid.split(".")
        return (BOOK_ORDER.get(b, 99), int(c), int(v))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query")
    ap.add_argument("--db", default="samaritanus.db")
    ap.add_argument("--mode", default="lemma", choices=MODES)
    ap.add_argument("--order", default="canonical", choices=("canonical", "relevance"))
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("--size", type=int, default=10)
    ap.add_argument("--book", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--forms", action="store_true", help="just list the lexeme's forms")
    a = ap.parse_args()

    ix = Index(a.db)
    if a.forms:
        for lem in ix.lemma_of(a.query):
            print(f"Strong {lem['strongs']:>8}  {lem['display']:12} "
                  f"{lem['n_forms']:3} forms, {lem['n_occur']:4} occurrences")
        print(" ".join(ix.forms_of(a.query)))
        return

    hits, total = ix.search(a.query, a.mode, a.order, a.page, a.size, a.book)
    if a.json:
        print(json.dumps({"total": total, "hits": [asdict(h) for h in hits]},
                         ensure_ascii=False, indent=2))
        return
    print(f"{total} verses  ({a.mode})\n")
    for h in hits:
        print(f"{h.book_name} {h.chapter}:{h.verse}  [{' '.join(h.matches)}]")
        print(f"  {h.text}\n")


if __name__ == "__main__":
    main()
