"""Samaritan orthography → Strong's lemma aliases.

OSHB lemmas follow MT spelling. A few Samaritan forms differ enough that
verse/corpus alignment never assigns a Strong's number. Map those stems
(and the MT spellings users type) onto the matching Strong's entry.

Used at index build (retag unlemmatized tokens) and at query time (Root
match when the typed spelling is absent from the Samaritan text).
"""

from __future__ import annotations

# Consonantal stems → Strong's (OSHB-style number string).
# ראשון / ראשונה: Samaritan inserts י (ראישון); ו may be present or absent.
LEMMA_ALIASES: dict[str, str] = {
    # Samaritan (with waw)
    "ראישונ": "7223",
    "ראישונה": "7223",
    "ראישונימ": "7223",
    "ראישונות": "7223",
    # Samaritan (without waw)
    "ראישנ": "7223",
    "ראישנה": "7223",
    "ראישנימ": "7223",
    "ראישנות": "7223",
    # MT spellings (query rewrite; not used in the SP text)
    "ראשונ": "7223",
    "ראשונה": "7223",
    "ראשונימ": "7223",
    "ראשונות": "7223",
}

# Same proclitics as build_index.rule_stems — keep in sync for alias lookup.
_PREFIXES = (
    "ובה", "וכה", "ולה", "ומה", "ושה", "וב", "וכ", "ול", "ומ", "וש",
    "וה", "בה", "כה", "לה", "מה", "שה", "ו", "ב", "כ", "ל", "מ", "ש", "ה",
)


def alias_strongs(norm: str) -> str | None:
    """Strong's for a consonantal form via Samaritan/MT orthography aliases."""
    if not norm:
        return None
    variants = {norm}
    for form in list(variants):
        for prefix in _PREFIXES:
            if form.startswith(prefix) and len(form) - len(prefix) >= 3:
                variants.add(form[len(prefix):])
    # Second pass: ה + ב etc. stacked on Samaritan forms.
    for form in list(variants):
        for prefix in _PREFIXES:
            if form.startswith(prefix) and len(form) - len(prefix) >= 3:
                variants.add(form[len(prefix):])
    for stem in sorted(variants, key=len, reverse=True):
        if stem in LEMMA_ALIASES:
            return LEMMA_ALIASES[stem]
    return None
