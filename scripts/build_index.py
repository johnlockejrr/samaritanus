#!/usr/bin/env python3
"""
build_index.py — build the search index for the Samaritan Pentateuch.

    python build_index.py --oshb ./data/wlc --data data/verses.ndjson \
                          --strongs data/strongs/StrongHebrewG.xml \
                          --out data/samaritanus.db

Produces one SQLite file holding:
  - an FTS5 index over the verse text (BM25 relevance, phrase search)
  - a word table with each token's consonantal form and its Strong's lemma,
    taken from the Open Scriptures Hebrew Bible morphology
  - a lemma table mapping each Strong's number to a display form
  - a strongs_expand table linking each lemma to its Strong's derivation
    family (sole-source parents/children from StrongHebrewG.xml)

Every word is reduced to its consonantal skeleton before anything else:
vowels, cantillation and the maqaf are dropped and final letters are folded
(ך→כ, ם→מ, ן→נ, ף→פ, ץ→צ). Samaritan Hebrew is written consonantally, and the
MT is not, so this is what makes the two comparable at all.

Lemmas come from the MT verse with the same reference where the form occurs
there, and from the rest of the Pentateuch otherwise. Forms OSHB has no lemma
for keep a rule-stripped stem instead, so they are still findable.

Root search expands along Strong's sole-source derivation links so ראש
(H7218) finds ראשית (H7225), without merging dual-etymology lookalikes such
as ברא (H1254) with ברית (H1285).
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sqlite3
import sys
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
from samaritan_aliases import alias_strongs  # noqa: E402
OSIS_NS = {"o": "http://www.bibletechnologies.net/2003/OSIS/namespace"}
W = "{http://www.bibletechnologies.net/2003/OSIS/namespace}w"
VERSE = "{http://www.bibletechnologies.net/2003/OSIS/namespace}verse"

# OSHB file stem -> the three-letter code the Samaritan data uses
BOOKS = {"Gen": "GEN", "Exod": "EXO", "Lev": "LEV", "Num": "NUM", "Deut": "DEU"}

# single-letter prefix codes OSHB puts in the lemma field before the lexeme
OSHB_PREFIX_CODES = set("bcdhiklms")

FINALS = str.maketrans("ךםןףץ", "כמנפצ")


def consonantal(s: str) -> str:
    """Vowels, cantillation, punctuation and morpheme slashes out; finals folded.

    NFKD + drop combining marks so MT-pointed forms align with Samaritan
    consonants. Must stay consistent with src/search.py::consonantal.
    """
    s = s.replace("/", "")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\u05d0-\u05ea]", "", s)
    return s.translate(FINALS)


def content_strongs(lemma: str) -> str | None:
    """The lexical Strong's number, with attached prefixes ignored."""
    parts = [p for p in lemma.split("/") if p not in OSHB_PREFIX_CODES]
    return parts[-1].strip() if parts else None


def strongs_base(s: str) -> str:
    """OSHB '7218 a' / '1254a' → bare Strong's digits '7218' / '1254'."""
    digits = "".join(c for c in s if c.isdigit())
    return digits or s.strip()


# --- fallback stemmer, for the ~5% of forms OSHB cannot lemmatise -----------
PREFIXES = ("ובה", "וכה", "ולה", "ומה", "ושה", "וב", "וכ", "ול", "ומ", "וש",
            "וה", "בה", "כה", "לה", "מה", "שה", "ו", "ב", "כ", "ל", "מ", "ש", "ה")
VERB_PREFIXES = ("וי", "ות", "ונ", "וא", "י", "ת", "נ", "א")
SUFFIXES = ("יהמ", "יכמ", "ותיה", "נו", "כמ", "המ", "הנ", "תי", "תמ", "תנ",
            "יו", "יה", "ימ", "ות", "נה", "תה", "כ", "מ", "נ", "ו", "ה", "י")


def rule_stems(w: str) -> set[str]:
    """Every plausible stem of a consonantal form, by stripping known affixes."""
    out = {w}
    for p in PREFIXES + VERB_PREFIXES:
        if w.startswith(p) and len(w) - len(p) >= 2:
            out.add(w[len(p):])
    extra = set()
    for s in out:
        for suf in SUFFIXES:
            if s.endswith(suf) and len(s) - len(suf) >= 2:
                extra.add(s[: -len(suf)])
    return out | extra


def load_oshb(wlc_dir: Path):
    """-> (verse_id -> {form: strongs}, form -> Counter(strongs))"""
    by_verse: dict[str, dict[str, str]] = {}
    form_strongs: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for stem, code in BOOKS.items():
        path = wlc_dir / f"{stem}.xml"
        if not path.exists():
            raise SystemExit(f"missing OSHB book: {path}")
        for v in ET.parse(path).getroot().iter(VERSE):
            oid = v.get("osisID")
            if not oid:
                continue
            _, ch, vs = oid.split(".")
            vid = f"{code}.{ch}.{vs}"
            words = {}
            for w in v.findall("o:w", OSIS_NS):
                form = consonantal("".join(w.itertext()))
                strongs = content_strongs(w.get("lemma", ""))
                if form and strongs:
                    words[form] = strongs
                    form_strongs[form][strongs] += 1
            by_verse[vid] = words
    return by_verse, form_strongs


def load_verses(path: Path) -> list[dict]:
    """The NDJSON bulk file, or a plain JSON list."""
    rows = []
    text = path.read_text(encoding="utf-8")
    if text.lstrip().startswith("["):
        return json.loads(text)
    for line in text.splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        if "text" in d:
            rows.append(d)
    return rows


def load_sole_derivation(path: Path) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Sole-source Strong's derivation edges from StrongHebrewG.xml.

    Only links where an entry cites exactly one parent `src` are kept. Dual
    etymologies (e.g. ברית citing both ברא and ברה) are excluded so Root
    search does not merge unrelated lookalikes.
    """
    xml = path.read_bytes()
    xml = re.sub(br'\sxmlns="[^"]+"', b"", xml, count=1)
    root = ET.fromstring(xml)
    children: dict[str, set[str]] = collections.defaultdict(set)
    parents: dict[str, set[str]] = collections.defaultdict(set)
    for div in root.iter("div"):
        if div.get("type") != "entry":
            continue
        n = div.get("n")
        if not n or not n.isdigit():
            continue
        srcs = {
            w.get("src")
            for w in div.iter("w")
            if w.get("src") and w.get("src").isdigit()
        }
        if len(srcs) != 1:
            continue
        parent = next(iter(srcs))
        children[parent].add(n)
        parents[n].add(parent)
    return children, parents


def family_bases(num: str, children: dict[str, set[str]],
                 parents: dict[str, set[str]]) -> set[str]:
    """Climb sole parents to roots, then take all sole-source descendants."""
    roots: set[str] = set()
    stack = [num]
    seen: set[str] = set()
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        ps = parents.get(cur)
        if not ps:
            roots.add(cur)
        else:
            stack.extend(ps)
    family = set(roots)
    stack = list(roots)
    while stack:
        cur = stack.pop()
        for child in children.get(cur, ()):
            if child not in family:
                family.add(child)
                stack.append(child)
    family.add(num)
    return family


def build_expand_rows(lemma_keys: list[str], strongs_xml: Path | None) -> list[tuple[str, str]]:
    """(strongs, related) pairs for every OSHB lemma in the same sole-source family."""
    by_base: dict[str, list[str]] = collections.defaultdict(list)
    for key in lemma_keys:
        by_base[strongs_base(key)].append(key)

    if strongs_xml is None or not strongs_xml.is_file():
        return [(k, k) for k in lemma_keys]

    children, parents = load_sole_derivation(strongs_xml)
    rows: list[tuple[str, str]] = []
    seen_pair: set[tuple[str, str]] = set()
    for key in lemma_keys:
        members = family_bases(strongs_base(key), children, parents)
        related_keys = []
        for base in members:
            related_keys.extend(by_base.get(base, ()))
        if not related_keys:
            related_keys = [key]
        for related in related_keys:
            pair = (key, related)
            if pair not in seen_pair:
                seen_pair.add(pair)
                rows.append(pair)
    return rows


SCHEMA = """
PRAGMA journal_mode=DELETE;
DROP TABLE IF EXISTS verses;
DROP TABLE IF EXISTS words;
DROP TABLE IF EXISTS lemmas;
DROP TABLE IF EXISTS strongs_expand;
DROP TABLE IF EXISTS meta;

CREATE VIRTUAL TABLE verses USING fts5(
  verse_id UNINDEXED, book UNINDEXED, book_name UNINDEXED,
  chapter UNINDEXED, verse UNINDEXED,
  text,                      -- as written, for display
  norm,                      -- consonantal, for matching
  tokenize='unicode61 remove_diacritics 2'
);

CREATE TABLE words (
  verse_id TEXT NOT NULL,
  pos      INTEGER NOT NULL,
  surface  TEXT NOT NULL,    -- as written
  norm     TEXT NOT NULL,    -- consonantal
  strongs  TEXT,             -- OSHB lexeme, NULL when unknown
  source   TEXT NOT NULL     -- verse | corpus | alias | stem
);
CREATE INDEX words_strongs ON words(strongs);
CREATE INDEX words_norm    ON words(norm);
CREATE INDEX words_verse   ON words(verse_id);

CREATE TABLE lemmas (
  strongs TEXT PRIMARY KEY,
  display TEXT NOT NULL,     -- the shortest attested form, as a label
  n_forms INTEGER NOT NULL,
  n_occur INTEGER NOT NULL
);

-- Root match: every OSHB lemma key that shares a sole-source Strong's family
CREATE TABLE strongs_expand (
  strongs TEXT NOT NULL,
  related TEXT NOT NULL,
  PRIMARY KEY (strongs, related)
);
CREATE INDEX strongs_expand_related ON strongs_expand(related);

CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--oshb", required=True, type=Path,
                    help="the wlc/ directory of openscriptures/morphhb")
    ap.add_argument("--data", required=True, type=Path,
                    help="the Samaritan verses (NDJSON bulk file or JSON list)")
    ap.add_argument("--strongs", type=Path, default=None,
                    help="StrongHebrewG.xml from openscriptures/strongs (Root families)")
    ap.add_argument("--out", default=Path("samaritanus.db"), type=Path)
    a = ap.parse_args()

    print("reading OSHB morphology ...")
    mt_by_verse, form_strongs = load_oshb(a.oshb)
    print(f"  {len(mt_by_verse)} MT verses, {len(form_strongs)} distinct forms")

    rows = load_verses(a.data)
    print(f"reading Samaritan text ... {len(rows)} verses")

    db = sqlite3.connect(a.out)
    db.executescript(SCHEMA)

    stats = collections.Counter()
    word_rows, verse_rows = [], []
    lemma_forms: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)

    for r in rows:
        vid = r["verse_id"]
        mtw = mt_by_verse.get(vid, {})
        toks = r["text"].split()
        norms = []
        for i, w in enumerate(toks):
            n = consonantal(w)
            if not n:
                continue
            norms.append(n)
            if n in mtw:                       # same verse: the safest lemma
                strongs, src = mtw[n], "verse"
            elif n in form_strongs:            # elsewhere in the Pentateuch
                strongs, src = form_strongs[n].most_common(1)[0][0], "corpus"
            else:
                aliased = alias_strongs(n)     # known Samaritan orthography
                if aliased:
                    strongs, src = aliased, "alias"
                else:                          # no morphology: keep a stem
                    strongs, src = None, "stem"
            stats[src] += 1
            word_rows.append((vid, i, w, n, strongs, src))
            if strongs:
                lemma_forms[strongs][n] += 1
        verse_rows.append((vid, r.get("book"), r.get("book_name"),
                           r.get("chapter"), r.get("verse"), r["text"], " ".join(norms)))

    lemma_keys = list(lemma_forms)
    print("building Strong's root families ...")
    expand_rows = build_expand_rows(lemma_keys, a.strongs)
    family_sizes = collections.Counter(s for s, _ in expand_rows)
    multi = sum(1 for n in family_sizes.values() if n > 1)
    print(f"  {len(expand_rows)} expand edges; {multi} lemmas with family size > 1")

    db.executemany("INSERT INTO verses VALUES (?,?,?,?,?,?,?)", verse_rows)
    db.executemany("INSERT INTO words VALUES (?,?,?,?,?,?)", word_rows)
    db.executemany(
        "INSERT INTO lemmas VALUES (?,?,?,?)",
        [(s, min(c, key=len), len(c), sum(c.values())) for s, c in lemma_forms.items()])
    db.executemany("INSERT INTO strongs_expand VALUES (?,?)", expand_rows)
    db.executemany("INSERT INTO meta VALUES (?,?)", [
        ("verses", str(len(verse_rows))),
        ("tokens", str(len(word_rows))),
        ("lemmas", str(len(lemma_forms))),
        ("strongs_expand", str(len(expand_rows))),
        ("coverage_verse", str(stats["verse"])),
        ("coverage_corpus", str(stats["corpus"])),
        ("coverage_alias", str(stats["alias"])),
        ("coverage_none", str(stats["stem"])),
    ])
    db.commit()
    db.execute("ANALYZE")
    db.commit()

    tot = sum(stats.values())
    print(f"\nindexed {len(verse_rows)} verses, {tot} tokens, {len(lemma_forms)} lemmas")
    print(f"  lemma from the same verse : {stats['verse']:6d} ({stats['verse']/tot*100:5.1f}%)")
    print(f"  lemma from elsewhere in MT: {stats['corpus']:6d} ({stats['corpus']/tot*100:5.1f}%)")
    print(f"  Samaritan orthography alias: {stats['alias']:6d} ({stats['alias']/tot*100:5.1f}%)")
    print(f"  no lemma, stem fallback   : {stats['stem']:6d} ({stats['stem']/tot*100:5.1f}%)")
    print(f"\nwrote {a.out} ({a.out.stat().st_size/1024/1024:.1f} MB)")


if __name__ == "__main__":
    main()
