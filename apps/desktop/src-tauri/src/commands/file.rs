// ═══════════════════════════════════════════════════════════════
//  VengaiCode Desktop — Local folder scanning for the Reverse App
//  feature's "local_folder" source mode.
//
//  The ONE Reverse App mode that reaches an actually-installed
//  application rather than something published online: the user picks
//  a real folder on their machine (e.g. an installed Electron app's
//  install directory), this walks it with real filesystem access (the
//  backend is a remote HTTP server — it has no way to read the user's
//  disk itself), and returns a bounded set of candidate files
//  (base64-encoded) for the frontend to upload to
//  POST /reverse/analyze. Any app.asar found is uploaded as-is — the
//  backend's parse_asar() unpacks it server-side, not here, so this
//  side stays simple file I/O with no archive-format parsing of its own.
// ═══════════════════════════════════════════════════════════════

use std::path::Path;

use base64::engine::general_purpose::STANDARD as BASE64;
use base64::Engine;
use serde::Serialize;

// Same rationale/shape as scan.rs's MAX_SCAN_DEPTH: bounded so a huge or
// deeply-nested install folder can't hang the scan indefinitely.
const MAX_SCAN_DEPTH: u32 = 10;
const MAX_FILES_COLLECTED: usize = 60;
const MAX_REGULAR_FILE_BYTES: u64 = 200_000;
// Matches the backend's MAX_ASAR_BYTES (reverse_engineer.py) — no point
// reading more locally than the server will accept.
const MAX_ASAR_FILE_BYTES: u64 = 80 * 1024 * 1024;

const CANDIDATE_EXTENSIONS: &[&str] = &[
    "json", "js", "ts", "jsx", "tsx", "py", "rb", "java", "go", "rs", "php",
    "prisma", "toml", "gradle", "xml",
];
const SKIP_DIR_NAMES: &[&str] = &["node_modules", ".git", ".svn", "__pycache__", "locales"];

#[derive(Serialize, Clone)]
pub struct LocalFileEntry {
    pub relative_path: String,
    pub content_base64: String,
    pub is_asar: bool,
}

#[derive(Serialize, Clone)]
pub struct LocalFolderScanResult {
    pub root_label: String,
    pub files: Vec<LocalFileEntry>,
    // True if the file-count cap was hit before the walk finished — the
    // frontend surfaces this so the user knows the scan was partial.
    pub truncated: bool,
}

fn is_candidate_file(filename: &str) -> bool {
    let lower = filename.to_lowercase();
    if lower.ends_with(".asar") {
        return true;
    }
    match filename.rsplit('.').next() {
        Some(ext) if ext != filename => CANDIDATE_EXTENSIONS.contains(&ext.to_lowercase().as_str()),
        _ => false,
    }
}

fn walk(dir: &Path, depth: u32, root: &Path, out: &mut Vec<LocalFileEntry>, truncated: &mut bool) {
    if out.len() >= MAX_FILES_COLLECTED {
        *truncated = true;
        return;
    }
    if depth > MAX_SCAN_DEPTH {
        return;
    }
    let Ok(entries) = std::fs::read_dir(dir) else {
        return;
    };

    for entry in entries.flatten() {
        if out.len() >= MAX_FILES_COLLECTED {
            *truncated = true;
            return;
        }
        let Ok(file_type) = entry.file_type() else {
            continue;
        };
        let path = entry.path();
        let name = entry.file_name().to_string_lossy().to_string();

        if file_type.is_dir() {
            if name.starts_with('.') || SKIP_DIR_NAMES.contains(&name.as_str()) {
                continue;
            }
            walk(&path, depth + 1, root, out, truncated);
        } else if file_type.is_file() {
            if !is_candidate_file(&name) {
                continue;
            }
            let is_asar = name.to_lowercase().ends_with(".asar");
            let cap = if is_asar { MAX_ASAR_FILE_BYTES } else { MAX_REGULAR_FILE_BYTES };
            let size = entry.metadata().map(|m| m.len()).unwrap_or(0);
            if size == 0 || size > cap {
                continue;
            }
            let Ok(bytes) = std::fs::read(&path) else {
                continue;
            };
            let relative_path = path
                .strip_prefix(root)
                .unwrap_or(&path)
                .to_string_lossy()
                .replace('\\', "/");
            out.push(LocalFileEntry {
                relative_path,
                content_base64: BASE64.encode(&bytes),
                is_asar,
            });
        }
    }
}

/// Walks a folder the user picked (via the dialog.open allowlist on the
/// frontend), collecting a bounded set of real candidate source/manifest
/// files plus any app.asar archive found, for upload to
/// POST /reverse/analyze (source_type="local_folder"). Real filesystem
/// access only Tauri's Rust side has — the backend can't reach the user's
/// disk itself.
#[tauri::command]
pub fn scan_local_folder(path: String) -> Result<LocalFolderScanResult, String> {
    let root = Path::new(&path);
    if !root.is_dir() {
        return Err("That doesn't look like a folder.".to_string());
    }
    let root_label = root
        .file_name()
        .map(|n| n.to_string_lossy().to_string())
        .unwrap_or_else(|| path.clone());

    let mut files = Vec::new();
    let mut truncated = false;
    walk(root, 0, root, &mut files, &mut truncated);

    Ok(LocalFolderScanResult {
        root_label,
        files,
        truncated,
    })
}
