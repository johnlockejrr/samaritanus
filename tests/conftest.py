import os
import sqlite3
import sys
from pathlib import Path

# Hermetic defaults before the app reads its settings.
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "0")
os.environ.setdefault("DOCS_ENABLED", "false")
os.environ.pop("API_KEY", None)
os.environ.pop("STATIC_DIR", None)

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from search import consonantal  # noqa: E402

FIX_DIR = Path(__file__).resolve().parent / ".tmp"
FIX_DIR.mkdir(exist_ok=True)
FIX_DB = FIX_DIR / "fixture.db"
if FIX_DB.exists():
    FIX_DB.unlink()

_SCHEMA = """
CREATE VIRTUAL TABLE verses USING fts5(
  verse_id UNINDEXED, book UNINDEXED, book_name UNINDEXED,
  chapter UNINDEXED, verse UNINDEXED, text, norm,
  tokenize='unicode61 remove_diacritics 2'
);
CREATE TABLE words (
  verse_id TEXT NOT NULL,
  pos INTEGER NOT NULL,
  surface TEXT NOT NULL,
  norm TEXT NOT NULL,
  strongs TEXT,
  source TEXT NOT NULL
);
CREATE TABLE lemmas (
  strongs TEXT PRIMARY KEY,
  display TEXT NOT NULL,
  n_forms INTEGER NOT NULL,
  n_occur INTEGER NOT NULL
);
CREATE TABLE strongs_expand (
  strongs TEXT NOT NULL,
  related TEXT NOT NULL,
  PRIMARY KEY (strongs, related)
);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""

_RAW_VERSES = [
    ("GEN.1.1", "1", "Genesis", 1, 1, "בראשית ברא אלהים"),
    ("GEN.1.5", "1", "Genesis", 1, 5, "ויקרא אלהים לאור יום"),
    ("GEN.1.21", "1", "Genesis", 1, 21, "ויברא אלהים"),
    ("GEN.2.10", "1", "Genesis", 2, 10, "ראש הנהר"),
    ("GEN.8.13", "1", "Genesis", 8, 13, "הראישון"),
    ("GEN.15.18", "1", "Genesis", 15, 18, "כרת ברית"),
    ("EXO.20.1", "2", "Exodus", 20, 1, "וידבר אלהים"),
    ("NUM.1.1", "4", "Numeri", 1, 1, "ברא"),
]
_VERSES = [(*row, consonantal(row[-1])) for row in _RAW_VERSES]
_RAW_WORDS = [
    ("GEN.1.1", 0, "בראשית", "7225", "verse"),
    ("GEN.1.1", 1, "ברא", "1254a", "verse"),
    ("GEN.1.1", 2, "אלהים", "430", "verse"),
    ("GEN.1.5", 1, "בא", "935", "verse"),
    ("GEN.1.21", 0, "ויברא", "1254a", "verse"),
    ("GEN.1.21", 1, "אלהים", "430", "verse"),
    ("GEN.2.10", 0, "ראש", "7218 a", "verse"),
    ("GEN.8.13", 0, "הראישון", "7223", "alias"),
    ("GEN.15.18", 1, "ברית", "1285", "verse"),
    ("EXO.20.1", 1, "אלהים", "430", "verse"),
    ("NUM.1.1", 0, "ברא", "9999", "verse"),
]
_WORDS = [(vid, pos, surface, consonantal(surface), strongs, source) for vid, pos, surface, strongs, source in _RAW_WORDS]
_LEMMAS = [
    ("1254a", "ברא", 2, 2),
    ("7225", "בראשית", 1, 1),
    ("7218 a", "ראש", 1, 1),
    ("7223", "הראישון", 1, 1),
    ("430", "אלהים", 1, 3),
    ("935", "בא", 1, 1),
    ("1285", "ברית", 1, 1),
    ("9999", "ברא", 1, 1),
]
# Sole-source family: ראש (7218) ↔ ראשית (7225) ↔ ראישון (7223). ברא stays apart from ברית.
_EXPAND = [
    ("1254a", "1254a"),
    ("7225", "7225"),
    ("7225", "7218 a"),
    ("7225", "7223"),
    ("7218 a", "7218 a"),
    ("7218 a", "7225"),
    ("7218 a", "7223"),
    ("7223", "7223"),
    ("7223", "7218 a"),
    ("7223", "7225"),
    ("430", "430"),
    ("935", "935"),
    ("1285", "1285"),
    ("9999", "9999"),
]

_db = sqlite3.connect(FIX_DB)
_db.executescript(_SCHEMA)
_db.executemany("INSERT INTO verses VALUES (?,?,?,?,?,?,?)", _VERSES)
_db.executemany("INSERT INTO words VALUES (?,?,?,?,?,?)", _WORDS)
_db.executemany("INSERT INTO lemmas VALUES (?,?,?,?)", _LEMMAS)
_db.executemany("INSERT INTO strongs_expand VALUES (?,?)", _EXPAND)
_db.executemany(
    "INSERT INTO meta VALUES (?,?)",
    [("verses", "8"), ("tokens", "11"), ("lemmas", "8"), ("strongs_expand", str(len(_EXPAND)))],
)
_db.commit()
_db.close()

os.environ["SEARCH_DB"] = str(FIX_DB)
