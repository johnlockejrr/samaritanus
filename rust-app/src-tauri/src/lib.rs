use search_engine::{BookOut, HealthOut, Index, SearchOut, SearchRequest};
use std::path::PathBuf;
use std::sync::Mutex;
use tauri::Manager;

struct AppState {
    index: Mutex<Option<Index>>,
}

fn resolve_db_path(app: &tauri::AppHandle) -> PathBuf {
    if let Ok(p) = std::env::var("SEARCH_DB") {
        return PathBuf::from(p);
    }
    if let Ok(res) = app.path().resource_dir() {
        let candidate = res.join("resources").join("samaritanus.db");
        if candidate.is_file() {
            return candidate;
        }
        let candidate = res.join("samaritanus.db");
        if candidate.is_file() {
            return candidate;
        }
    }
    let mut here = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let local = here.join("resources").join("samaritanus.db");
    if local.is_file() {
        return local;
    }
    here.pop();
    here.pop();
    here.join("data").join("samaritanus.db")
}

fn with_index<T>(
    state: &AppState,
    app: &tauri::AppHandle,
    f: impl FnOnce(&Index) -> Result<T, String>,
) -> Result<T, String> {
    let mut guard = state.index.lock().map_err(|e| e.to_string())?;
    if guard.is_none() {
        let path = resolve_db_path(app);
        *guard = Some(Index::open(&path)?);
    }
    f(guard.as_ref().unwrap())
}

#[tauri::command]
fn search(
    req: SearchRequest,
    state: tauri::State<'_, AppState>,
    app: tauri::AppHandle,
) -> Result<SearchOut, String> {
    with_index(&state, &app, |ix| ix.search_api(req))
}

#[tauri::command]
fn books(
    state: tauri::State<'_, AppState>,
    app: tauri::AppHandle,
) -> Result<Vec<BookOut>, String> {
    with_index(&state, &app, |ix| ix.books())
}

#[tauri::command]
fn health(state: tauri::State<'_, AppState>, app: tauri::AppHandle) -> Result<HealthOut, String> {
    let path = resolve_db_path(&app);
    match with_index(&state, &app, |ix| {
        Ok(HealthOut {
            status: "ok".into(),
            verses: ix.stats_verses()?,
            db: ix.path().display().to_string(),
        })
    }) {
        Ok(h) => Ok(h),
        Err(e) => Ok(HealthOut {
            status: "degraded".into(),
            verses: None,
            db: format!("{path:?} ({e})"),
        }),
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(AppState {
            index: Mutex::new(None),
        })
        .invoke_handler(tauri::generate_handler![search, books, health])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
