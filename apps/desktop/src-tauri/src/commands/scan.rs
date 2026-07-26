// ═══════════════════════════════════════════════════════════════
//  VengaiCode Desktop — Portable drive & AI model scanning
//  Detects plugged-in removable drives and looks for .gguf model
//  files on them, for the "Detect Portable AI Model" Settings flow.
// ═══════════════════════════════════════════════════════════════

use std::path::Path;

use serde::Serialize;
use sysinfo::Disks;

#[derive(Serialize, Clone)]
pub struct DriveInfo {
    pub mount_point: String,
    pub name: String,
    pub available_space: u64,
    pub total_space: u64,
}

#[derive(Serialize, Clone)]
pub struct PortableModelInfo {
    pub path: String,
    pub filename: String,
    pub size_bytes: u64,
    pub display_name: String,
}

#[tauri::command]
pub fn list_removable_drives() -> Vec<DriveInfo> {
    let disks = Disks::new_with_refreshed_list();
    disks
        .list()
        .iter()
        .filter(|d| d.is_removable())
        .map(|d| DriveInfo {
            mount_point: d.mount_point().to_string_lossy().to_string(),
            name: d.name().to_string_lossy().to_string(),
            available_space: d.available_space(),
            total_space: d.total_space(),
        })
        .collect()
}

// Bounded so a huge/slow drive can't hang the scan indefinitely.
const MAX_SCAN_DEPTH: u32 = 3;

fn display_name_from_filename(filename: &str) -> String {
    filename
        .strip_suffix(".gguf")
        .unwrap_or(filename)
        .replace(['_', '-'], " ")
}

fn walk_for_models(dir: &Path, depth: u32, out: &mut Vec<PortableModelInfo>) {
    if depth > MAX_SCAN_DEPTH {
        return;
    }
    let Ok(entries) = std::fs::read_dir(dir) else {
        return;
    };

    for entry in entries.flatten() {
        let Ok(file_type) = entry.file_type() else {
            continue;
        };
        let path = entry.path();

        if file_type.is_dir() {
            let name = entry.file_name().to_string_lossy().to_string();
            // Skip hidden/system dirs — dotfiles, Windows/macOS volume metadata.
            if name.starts_with('.') || name.starts_with('$') || name == "System Volume Information" {
                continue;
            }
            walk_for_models(&path, depth + 1, out);
        } else if file_type.is_file() {
            let filename = entry.file_name().to_string_lossy().to_string();
            if filename.to_lowercase().ends_with(".gguf") {
                let size_bytes = entry.metadata().map(|m| m.len()).unwrap_or(0);
                out.push(PortableModelInfo {
                    path: path.to_string_lossy().to_string(),
                    display_name: display_name_from_filename(&filename),
                    filename,
                    size_bytes,
                });
            }
        }
    }
}

#[tauri::command]
pub fn scan_drive_for_models(path: String) -> Vec<PortableModelInfo> {
    let mut out = Vec::new();
    walk_for_models(Path::new(&path), 0, &mut out);
    out
}
