#!/usr/bin/env python3
"""Build data/samaritanus.db if it is missing.

Downloads the Open Scriptures Hebrew Bible morphology (WLC) and Strong's
Hebrew lexicon on first use, then runs build_index.py against
data/verses.ndjson. Safe to re-run.
"""
from __future__ import annotations

import io
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WLC_FILES = ("Gen.xml", "Exod.xml", "Lev.xml", "Num.xml", "Deut.xml")
OSHB_ZIP = "https://codeload.github.com/openscriptures/morphhb/zip/refs/heads/master"
STRONGS_ZIP = "https://codeload.github.com/openscriptures/strongs/zip/refs/heads/master"
STRONGS_NAME = "StrongHebrewG.xml"


def download_wlc(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    print(f"downloading OSHB morphology from {OSHB_ZIP}")
    with urllib.request.urlopen(OSHB_ZIP, timeout=180) as resp:
        payload = resp.read()
    written = 0
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for name in archive.namelist():
            base = Path(name).name
            if "/wlc/" in name and base in WLC_FILES:
                (dest / base).write_bytes(archive.read(name))
                written += 1
    if written != len(WLC_FILES):
        raise SystemExit(f"OSHB archive did not contain all of {WLC_FILES} (got {written})")


def download_strongs(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / STRONGS_NAME
    print(f"downloading Strong's Hebrew from {STRONGS_ZIP}")
    with urllib.request.urlopen(STRONGS_ZIP, timeout=180) as resp:
        payload = resp.read()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for name in archive.namelist():
            if name.endswith(f"hebrew/{STRONGS_NAME}"):
                out.write_bytes(archive.read(name))
                return
    raise SystemExit(f"Strong's archive did not contain hebrew/{STRONGS_NAME}")


def main() -> None:
    force = "--force" in sys.argv
    db = ROOT / "data" / "samaritanus.db"
    verses = ROOT / "data" / "verses.ndjson"
    wlc = ROOT / "data" / "wlc"
    strongs_dir = ROOT / "data" / "strongs"
    strongs_xml = strongs_dir / STRONGS_NAME
    if db.is_file() and not force:
        print(f"index present: {db}")
        return
    if not verses.is_file():
        raise SystemExit(f"missing verse file: {verses}")
    if not all((wlc / name).is_file() for name in WLC_FILES):
        download_wlc(wlc)
    if not strongs_xml.is_file():
        download_strongs(strongs_dir)

    sys.path.insert(0, str(ROOT / "scripts"))
    import build_index

    sys.argv = [
        "build_index.py",
        "--oshb", str(wlc),
        "--data", str(verses),
        "--strongs", str(strongs_xml),
        "--out", str(db),
    ]
    build_index.main()


if __name__ == "__main__":
    main()
