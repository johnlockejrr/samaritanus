//! Samaritan orthography → Strong's lemma aliases.
//! Keep in sync with `src/samaritan_aliases.py`.

use std::collections::HashSet;

const LEMMA_ALIASES: &[(&str, &str)] = &[
    ("ראישונ", "7223"),
    ("ראישונה", "7223"),
    ("ראישונימ", "7223"),
    ("ראישונות", "7223"),
    ("ראישנ", "7223"),
    ("ראישנה", "7223"),
    ("ראישנימ", "7223"),
    ("ראישנות", "7223"),
    ("ראשונ", "7223"),
    ("ראשונה", "7223"),
    ("ראשונימ", "7223"),
    ("ראשונות", "7223"),
];

const PREFIXES: &[&str] = &[
    "ובה", "וכה", "ולה", "ומה", "ושה", "וב", "וכ", "ול", "ומ", "וש", "וה", "בה", "כה",
    "לה", "מה", "שה", "ו", "ב", "כ", "ל", "מ", "ש", "ה",
];

fn lookup_alias(stem: &str) -> Option<&'static str> {
    LEMMA_ALIASES
        .iter()
        .find(|(k, _)| *k == stem)
        .map(|(_, v)| *v)
}

/// Strong's for a consonantal form via Samaritan/MT orthography aliases.
pub fn alias_strongs(norm: &str) -> Option<String> {
    if norm.is_empty() {
        return None;
    }
    let mut variants: HashSet<String> = HashSet::new();
    variants.insert(norm.to_string());
    for form in variants.clone() {
        for prefix in PREFIXES {
            if form.starts_with(prefix) && form.chars().count() - prefix.chars().count() >= 3 {
                variants.insert(form[prefix.len()..].to_string());
            }
        }
    }
    for form in variants.clone() {
        for prefix in PREFIXES {
            if form.starts_with(prefix) && form.chars().count() - prefix.chars().count() >= 3 {
                variants.insert(form[prefix.len()..].to_string());
            }
        }
    }
    let mut stems: Vec<String> = variants.into_iter().collect();
    stems.sort_by_key(|s| std::cmp::Reverse(s.chars().count()));
    for stem in stems {
        if let Some(s) = lookup_alias(&stem) {
            return Some(s.to_string());
        }
    }
    None
}
