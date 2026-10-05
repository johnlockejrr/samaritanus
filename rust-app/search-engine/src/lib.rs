//! Read-only search over the Samaritan Pentateuch SQLite index.
//! Port of `src/search.py` + the search-response assembly from `backend.py`.

mod aliases;

use aliases::alias_strongs;
use rusqlite::{params_from_iter, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use unicode_normalization::UnicodeNormalization;

const FINALS: &[(char, char)] = &[
    ('ך', 'כ'),
    ('ם', 'מ'),
    ('ן', 'נ'),
    ('ף', 'פ'),
    ('ץ', 'צ'),
];

const BOOK_ORDER: &[(&str, i32)] = &[
    ("GEN", 1),
    ("EXO", 2),
    ("LEV", 3),
    ("NUM", 4),
    ("DEU", 5),
];

const ENGLISH_BOOKS: &[(&str, &str)] = &[
    ("GEN", "Genesis"),
    ("EXO", "Exodus"),
    ("LEV", "Leviticus"),
    ("NUM", "Numbers"),
    ("DEU", "Deuteronomy"),
];

fn book_rank(code: &str) -> i32 {
    BOOK_ORDER
        .iter()
        .find(|(c, _)| *c == code)
        .map(|(_, n)| *n)
        .unwrap_or(99)
}

fn english_book(code: &str, fallback: &str) -> String {
    ENGLISH_BOOKS
        .iter()
        .find(|(c, _)| *c == code)
        .map(|(_, n)| (*n).to_string())
        .unwrap_or_else(|| fallback.to_string())
}

fn fold_final(c: char) -> char {
    FINALS
        .iter()
        .find(|(from, _)| *from == c)
        .map(|(_, to)| *to)
        .unwrap_or(c)
}

/// NFKD, drop combining marks, keep Hebrew letters + spaces, fold finals.
pub fn consonantal(s: &str) -> String {
    let s = s.replace('/', "");
    let nfkd: String = s.nfkd().collect();
    let mut cleaned = String::new();
    for c in nfkd.chars() {
        if unicode_normalization::char::canonical_combining_class(c) != 0 {
            continue;
        }
        if ('\u{05d0}'..='\u{05ea}').contains(&c) || c.is_whitespace() {
            cleaned.push(if c.is_whitespace() { ' ' } else { fold_final(c) });
        } else {
            cleaned.push(' ');
        }
    }
    cleaned.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn escape_like(s: &str) -> String {
    s.replace('\\', "\\\\").replace('%', "\\%").replace('_', "\\_")
}

fn canon_key(vid: &str) -> (i32, i32, i32) {
    let mut parts = vid.split('.');
    let b = parts.next().unwrap_or("");
    let c: i32 = parts.next().and_then(|x| x.parse().ok()).unwrap_or(0);
    let v: i32 = parts.next().and_then(|x| x.parse().ok()).unwrap_or(0);
    (book_rank(b), c, v)
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Hit {
    pub verse_id: String,
    pub book_name: String,
    pub chapter: i32,
    pub verse: i32,
    pub text: String,
    pub matches: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Lemma {
    pub strongs: String,
    pub display: String,
    pub n_forms: i32,
    pub n_occur: i32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FormRow {
    pub form: String,
    pub n: i32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TermOut {
    pub word: String,
    pub lemmas: Vec<Lemma>,
    pub forms: Vec<String>,
    pub form_rows: Vec<FormRow>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchOut {
    pub total: i32,
    pub page: i32,
    pub size: i32,
    pub total_pages: i32,
    pub has_more: bool,
    pub mode: String,
    pub order: String,
    pub query: String,
    pub normalized: String,
    pub lemmas: Vec<Lemma>,
    pub forms: Vec<String>,
    pub terms: Vec<TermOut>,
    pub results: Vec<Hit>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BookOut {
    pub book_name: String,
    pub code: String,
    pub verses: i32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HealthOut {
    pub status: String,
    pub verses: Option<i32>,
    pub db: String,
}

#[derive(Debug, Deserialize)]
pub struct SearchRequest {
    pub q: String,
    pub mode: Option<String>,
    pub order: Option<String>,
    pub page: Option<i32>,
    pub size: Option<i32>,
    pub book: Option<String>,
    pub strongs: Option<String>,
    pub fuzziness: Option<i32>,
}

pub struct Index {
    conn: Mutex<Connection>,
    path: PathBuf,
    has_expand: bool,
}

impl Index {
    pub fn open(path: impl AsRef<Path>) -> Result<Self, String> {
        let path = path.as_ref().to_path_buf();
        if !path.is_file() {
            return Err(format!("search index not found: {}", path.display()));
        }
        let conn = Connection::open_with_flags(
            &path,
            rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY,
        )
        .map_err(|e| e.to_string())?;
        let has_expand: bool = conn
            .query_row(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='strongs_expand'",
                [],
                |_| Ok(true),
            )
            .optional()
            .map_err(|e| e.to_string())?
            .unwrap_or(false);
        Ok(Self {
            conn: Mutex::new(conn),
            path,
            has_expand,
        })
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub fn stats_verses(&self) -> Result<Option<i32>, String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let v: Option<String> = conn
            .query_row("SELECT value FROM meta WHERE key='verses'", [], |r| r.get(0))
            .optional()
            .map_err(|e| e.to_string())?;
        Ok(v.and_then(|s| s.parse().ok()))
    }

    pub fn books(&self) -> Result<Vec<BookOut>, String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let mut stmt = conn
            .prepare(
                "SELECT book_name,
                        substr(verse_id, 1, instr(verse_id, '.') - 1) AS code,
                        count(*) AS verses
                   FROM verses GROUP BY code ORDER BY min(rowid)",
            )
            .map_err(|e| e.to_string())?;
        let rows = stmt
            .query_map([], |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, i32>(2)?,
                ))
            })
            .map_err(|e| e.to_string())?;
        let mut found = Vec::new();
        for row in rows {
            let (book_name, code, verses) = row.map_err(|e| e.to_string())?;
            found.push(BookOut {
                book_name: english_book(&code, &book_name),
                code,
                verses,
            });
        }
        found.sort_by_key(|b| book_rank(&b.code));
        Ok(found)
    }

    pub fn lemma_of(&self, word: &str) -> Result<Vec<Lemma>, String> {
        let n = consonantal(word);
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let mut stmt = conn
            .prepare(
                "SELECT DISTINCT w.strongs, l.display, l.n_forms, l.n_occur
                   FROM words w JOIN lemmas l ON l.strongs = w.strongs
                  WHERE w.norm = ? ORDER BY l.n_occur DESC",
            )
            .map_err(|e| e.to_string())?;
        let rows = stmt
            .query_map([&n], |r| {
                Ok(Lemma {
                    strongs: r.get(0)?,
                    display: r.get(1)?,
                    n_forms: r.get(2)?,
                    n_occur: r.get(3)?,
                })
            })
            .map_err(|e| e.to_string())?;
        let mut out = Vec::new();
        for row in rows {
            out.push(row.map_err(|e| e.to_string())?);
        }
        if !out.is_empty() {
            return Ok(out);
        }
        drop(stmt);
        let Some(aliased) = alias_strongs(&n) else {
            return Ok(vec![]);
        };
        let row = conn
            .query_row(
                "SELECT strongs, display, n_forms, n_occur FROM lemmas WHERE strongs = ?",
                [&aliased],
                |r| {
                    Ok(Lemma {
                        strongs: r.get(0)?,
                        display: r.get(1)?,
                        n_forms: r.get(2)?,
                        n_occur: r.get(3)?,
                    })
                },
            )
            .optional()
            .map_err(|e| e.to_string())?;
        Ok(match row {
            Some(l) => vec![l],
            None => vec![Lemma {
                strongs: aliased,
                display: n,
                n_forms: 0,
                n_occur: 0,
            }],
        })
    }

    fn strongs_for_norm(&self, nq: &str) -> Result<Vec<String>, String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let mut stmt = conn
            .prepare(
                "SELECT DISTINCT strongs FROM words WHERE norm = ? AND strongs IS NOT NULL",
            )
            .map_err(|e| e.to_string())?;
        let rows = stmt
            .query_map([nq], |r| r.get::<_, String>(0))
            .map_err(|e| e.to_string())?;
        let mut matched = Vec::new();
        for row in rows {
            matched.push(row.map_err(|e| e.to_string())?);
        }
        if !matched.is_empty() {
            return Ok(matched);
        }
        Ok(alias_strongs(nq).into_iter().collect())
    }

    fn expand_strongs(&self, keys: &[String]) -> Result<Vec<String>, String> {
        if keys.is_empty() {
            return Ok(vec![]);
        }
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let mut out = Vec::new();
        let mut seen = HashSet::new();
        for key in keys {
            let mut related = Vec::new();
            if self.has_expand {
                let mut stmt = conn
                    .prepare("SELECT related FROM strongs_expand WHERE strongs = ?")
                    .map_err(|e| e.to_string())?;
                let rows = stmt
                    .query_map([key], |r| r.get::<_, String>(0))
                    .map_err(|e| e.to_string())?;
                for row in rows {
                    related.push(row.map_err(|e| e.to_string())?);
                }
            }
            if related.is_empty() {
                related.push(key.clone());
            }
            for item in related {
                if seen.insert(item.clone()) {
                    out.push(item);
                }
            }
        }
        Ok(out)
    }

    fn form_rows_where(&self, related: &[String]) -> Result<Vec<FormRow>, String> {
        if related.is_empty() {
            return Ok(vec![]);
        }
        let placeholders = related.iter().map(|_| "?").collect::<Vec<_>>().join(",");
        let sql = format!(
            "SELECT surface AS form, n FROM (
                    SELECT surface, norm, count(*) AS n,
                           row_number() OVER (
                             PARTITION BY norm
                             ORDER BY count(*) DESC, length(surface), surface
                           ) AS rn
                      FROM words WHERE strongs IN ({placeholders})
                      GROUP BY surface, norm
                ) WHERE rn = 1
                ORDER BY n DESC, length(norm), norm"
        );
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let mut stmt = conn.prepare(&sql).map_err(|e| e.to_string())?;
        let rows = stmt
            .query_map(params_from_iter(related.iter()), |r| {
                Ok(FormRow {
                    form: r.get(0)?,
                    n: r.get(1)?,
                })
            })
            .map_err(|e| e.to_string())?;
        let mut out = Vec::new();
        for row in rows {
            out.push(row.map_err(|e| e.to_string())?);
        }
        Ok(out)
    }

    pub fn form_rows_of(&self, word: &str) -> Result<Vec<FormRow>, String> {
        let related = self.expand_strongs(&self.strongs_for_norm(&consonantal(word))?)?;
        self.form_rows_where(&related)
    }

    pub fn form_rows_for(&self, strongs: &str) -> Result<Vec<FormRow>, String> {
        let related = self.expand_strongs(&[strongs.to_string()])?;
        self.form_rows_where(&related)
    }

    pub fn search(
        &self,
        q: &str,
        mode: &str,
        order: &str,
        page: i32,
        size: i32,
        book: Option<&str>,
        strongs: Option<&str>,
    ) -> Result<(Vec<Hit>, i32), String> {
        match mode {
            "exact" | "lemma" | "prefix" | "substr" => {}
            _ => return Err(format!("mode must be one of exact, lemma, prefix, substr")),
        }
        let nq = consonantal(q);
        if nq.is_empty() {
            return Ok((vec![], 0));
        }
        if nq.contains(' ') {
            return self.phrase(&nq, order, page, size, book);
        }
        let (where_sql, params) = self.word_predicate(&nq, mode, strongs)?;
        let sql = format!(
            "SELECT w.verse_id, group_concat(DISTINCT w.surface) AS matches
               FROM words w WHERE {where_sql}
           GROUP BY w.verse_id"
        );
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let mut stmt = conn.prepare(&sql).map_err(|e| e.to_string())?;
        let rows = stmt
            .query_map(params_from_iter(params.iter()), |r| {
                Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?))
            })
            .map_err(|e| e.to_string())?;
        let mut by_verse: HashMap<String, Vec<String>> = HashMap::new();
        for row in rows {
            let (vid, matches) = row.map_err(|e| e.to_string())?;
            by_verse.insert(
                vid,
                matches.split(',').map(|s| s.to_string()).collect(),
            );
        }
        drop(stmt);
        drop(conn);
        self.materialise(by_verse, order, page, size, book)
    }

    fn word_predicate(
        &self,
        nq: &str,
        mode: &str,
        strongs: Option<&str>,
    ) -> Result<(String, Vec<String>), String> {
        match mode {
            "exact" => Ok(("w.norm = ?".into(), vec![nq.to_string()])),
            "prefix" => Ok((
                "w.norm LIKE ? ESCAPE '\\'".into(),
                vec![format!("{}%", escape_like(nq))],
            )),
            "substr" => Ok((
                "w.norm LIKE ? ESCAPE '\\'".into(),
                vec![format!("%{}%", escape_like(nq))],
            )),
            _ => {
                let related = if let Some(s) = strongs {
                    self.expand_strongs(&[s.to_string()])?
                } else {
                    self.expand_strongs(&self.strongs_for_norm(nq)?)?
                };
                if related.is_empty() {
                    return Ok(("w.norm = ?".into(), vec![nq.to_string()]));
                }
                let qs = related.iter().map(|_| "?").collect::<Vec<_>>().join(",");
                Ok((format!("w.strongs IN ({qs})"), related))
            }
        }
    }

    fn phrase(
        &self,
        nq: &str,
        order: &str,
        page: i32,
        size: i32,
        book: Option<&str>,
    ) -> Result<(Vec<Hit>, i32), String> {
        let phrase = format!("\"{}\"", nq.replace('"', " "));
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let mut stmt = conn
            .prepare("SELECT verse_id FROM verses WHERE norm MATCH ?")
            .map_err(|e| e.to_string())?;
        let rows = stmt
            .query_map([&phrase], |r| r.get::<_, String>(0))
            .map_err(|e| e.to_string())?;
        let tokens: Vec<String> = nq.split_whitespace().map(|s| s.to_string()).collect();
        let mut by_verse = HashMap::new();
        for row in rows {
            let vid = row.map_err(|e| e.to_string())?;
            by_verse.insert(vid, tokens.clone());
        }
        drop(stmt);
        drop(conn);
        self.materialise(by_verse, order, page, size, book)
    }

    fn materialise(
        &self,
        by_verse: HashMap<String, Vec<String>>,
        order: &str,
        page: i32,
        size: i32,
        book: Option<&str>,
    ) -> Result<(Vec<Hit>, i32), String> {
        if by_verse.is_empty() {
            return Ok((vec![], 0));
        }
        let ids: Vec<String> = by_verse.keys().cloned().collect();
        let placeholders = ids.iter().map(|_| "?").collect::<Vec<_>>().join(",");
        let sql = format!(
            "SELECT verse_id, book, book_name, chapter, verse, text
               FROM verses WHERE verse_id IN ({placeholders})"
        );
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let mut stmt = conn.prepare(&sql).map_err(|e| e.to_string())?;
        let rows = stmt
            .query_map(params_from_iter(ids.iter()), |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(2)?,
                    r.get::<_, i32>(3)?,
                    r.get::<_, i32>(4)?,
                    r.get::<_, String>(5)?,
                ))
            })
            .map_err(|e| e.to_string())?;
        let mut verse_rows = Vec::new();
        for row in rows {
            verse_rows.push(row.map_err(|e| e.to_string())?);
        }
        drop(stmt);
        drop(conn);

        let codes: Option<HashSet<String>> = book.map(|b| {
            b.split(',')
                .map(|p| p.trim().to_uppercase())
                .filter(|p| !p.is_empty())
                .collect()
        });
        if let Some(ref codes) = codes {
            verse_rows.retain(|(vid, _, _, _, _)| {
                vid.split('.').next().map(|c| codes.contains(c)).unwrap_or(false)
            });
        }

        if order == "relevance" {
            verse_rows.sort_by(|a, b| {
                let la = by_verse.get(&a.0).map(|m| m.len()).unwrap_or(0);
                let lb = by_verse.get(&b.0).map(|m| m.len()).unwrap_or(0);
                lb.cmp(&la)
                    .then_with(|| canon_key(&a.0).cmp(&canon_key(&b.0)))
            });
        } else {
            verse_rows.sort_by(|a, b| canon_key(&a.0).cmp(&canon_key(&b.0)));
        }

        let total = verse_rows.len() as i32;
        let start = ((page - 1) * size).max(0) as usize;
        let page_rows = verse_rows
            .into_iter()
            .skip(start)
            .take(size.max(0) as usize);
        let mut hits = Vec::new();
        for (vid, book_name, chapter, verse, text) in page_rows {
            let code = vid.split('.').next().unwrap_or("").to_string();
            let mut matches = by_verse.get(&vid).cloned().unwrap_or_default();
            matches.sort();
            matches.dedup();
            hits.push(Hit {
                verse_id: vid,
                book_name: english_book(&code, &book_name),
                chapter,
                verse,
                text,
                matches,
            });
        }
        Ok((hits, total))
    }

    pub fn search_api(&self, req: SearchRequest) -> Result<SearchOut, String> {
        let q = req.q.trim().to_string();
        if q.is_empty() {
            return Err("Query must contain non-whitespace characters".into());
        }
        if q.chars().count() > 200 {
            return Err("Query exceeds 200 characters".into());
        }
        let mut mode = req.mode.unwrap_or_else(|| "lemma".into());
        if let Some(f) = req.fuzziness {
            mode = match f {
                0 => "exact".into(),
                1 => "lemma".into(),
                2 => "substr".into(),
                _ => mode,
            };
        }
        let order = req.order.unwrap_or_else(|| "canonical".into());
        let page = req.page.unwrap_or(1).max(1);
        let size = req.size.unwrap_or(10).clamp(1, 100);
        let book = req.book.filter(|b| !b.is_empty());
        if let Some(ref b) = book {
            for part in b.split(',') {
                let code = part.trim().to_uppercase();
                if code.is_empty() {
                    continue;
                }
                if !BOOK_ORDER.iter().any(|(c, _)| *c == code) && code != "-" {
                    return Err(format!("Unknown book code: {code}"));
                }
            }
        }
        let strongs = req.strongs.filter(|s| !s.is_empty());
        if let Some(ref s) = strongs {
            let re_ok = !s.is_empty()
                && s.chars()
                    .all(|c| c.is_ascii_digit() || matches!(c, ' ' | 'a'..='z' | 'A'..='Z' | '+'));
            if !re_ok {
                return Err("Invalid Strong's number".into());
            }
        }

        let normalized = consonantal(&q);
        let tokens: Vec<&str> = normalized.split_whitespace().collect();
        let lexeme = if mode == "lemma" && tokens.len() == 1 {
            strongs.clone()
        } else {
            None
        };
        let book_ref = book.as_deref();
        let (hits, total) = self.search(
            &q,
            &mode,
            &order,
            page,
            size,
            book_ref,
            lexeme.as_deref(),
        )?;

        let mut lemmas = Vec::new();
        let mut forms = Vec::new();
        let mut terms = Vec::new();
        if mode == "lemma" && !tokens.is_empty() {
            let raw_parts: Vec<String> = q
                .split_whitespace()
                .filter(|p| !consonantal(p).is_empty())
                .map(|s| s.to_string())
                .collect();
            for raw in raw_parts {
                let tok = consonantal(&raw);
                let term_lemmas = self.lemma_of(&tok)?;
                let term_form_rows = if let (Some(ref lex), true) = (&lexeme, tokens.len() == 1) {
                    self.form_rows_for(lex)?
                } else {
                    self.form_rows_of(&tok)?
                };
                let term_forms: Vec<String> =
                    term_form_rows.iter().map(|r| r.form.clone()).collect();
                terms.push(TermOut {
                    word: raw,
                    lemmas: term_lemmas,
                    forms: term_forms,
                    form_rows: term_form_rows,
                });
            }
            if tokens.len() == 1 && !terms.is_empty() {
                lemmas = terms[0].lemmas.clone();
                forms = terms[0].forms.clone();
            } else {
                let mut seen_s = HashSet::new();
                let mut seen_f = HashSet::new();
                for term in &terms {
                    for lem in &term.lemmas {
                        if seen_s.insert(lem.strongs.clone()) {
                            lemmas.push(lem.clone());
                        }
                    }
                    for form in &term.forms {
                        if seen_f.insert(form.clone()) {
                            forms.push(form.clone());
                        }
                    }
                }
            }
        }

        let total_pages = if total == 0 {
            0
        } else {
            (total + size - 1) / size
        };
        Ok(SearchOut {
            total,
            page,
            size,
            total_pages,
            has_more: page < total_pages,
            mode,
            order,
            query: q,
            normalized,
            lemmas,
            forms,
            terms,
            results: hits,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    fn db_path() -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../src-tauri/resources/samaritanus.db")
    }

    fn open_ix() -> Index {
        Index::open(db_path()).expect("open bundled samaritanus.db")
    }

    #[test]
    fn lemma_elohim_matches_python_baseline() {
        let ix = open_ix();
        let out = ix
            .search_api(SearchRequest {
                q: "אלהים".into(),
                mode: Some("lemma".into()),
                order: Some("canonical".into()),
                page: Some(1),
                size: Some(5),
                book: None,
                strongs: None,
                fuzziness: None,
            })
            .unwrap();
        assert_eq!(out.total, 698);
        assert_eq!(out.results[0].verse_id, "GEN.1.1");
        assert!(out.results[0].matches.iter().any(|m| m.contains("אלהים")));
        assert!(!out.terms.is_empty());
        assert_eq!(out.terms[0].word, "אלהים");
    }

    #[test]
    fn lemma_alias_raishon_maps_to_h7223_family() {
        let ix = open_ix();
        let out = ix
            .search_api(SearchRequest {
                q: "ראישון".into(),
                mode: Some("lemma".into()),
                order: Some("canonical".into()),
                page: Some(1),
                size: Some(3),
                book: None,
                strongs: None,
                fuzziness: None,
            })
            .unwrap();
        assert_eq!(out.total, 201);
        assert_eq!(out.results[0].verse_id, "GEN.1.1");
    }

    #[test]
    fn exact_bereshit_one_hit() {
        let ix = open_ix();
        let out = ix
            .search_api(SearchRequest {
                q: "בראשית".into(),
                mode: Some("exact".into()),
                order: None,
                page: Some(1),
                size: Some(3),
                book: None,
                strongs: None,
                fuzziness: None,
            })
            .unwrap();
        assert_eq!(out.total, 1);
    }

    #[test]
    fn books_lists_pentateuch() {
        let ix = open_ix();
        let books = ix.books().unwrap();
        assert_eq!(books.len(), 5);
        assert_eq!(books[0].code, "GEN");
        assert!(books.iter().all(|b| b.verses > 0));
    }
}
