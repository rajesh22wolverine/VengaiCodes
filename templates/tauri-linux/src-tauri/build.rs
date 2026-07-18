// ═══════════════════════════════════════════════════════════════
//  VengaiCode — Generated App — Tauri Build Script
//
//  Runs at compile time. Populates OUT_DIR and processes
//  tauri.conf.json into resources that tauri::generate_context!()
//  expects. Without this file, Cargo has no way to know it should
//  run tauri-build's preprocessing — hence the "OUT_DIR env var
//  is not set" error.
// ═══════════════════════════════════════════════════════════════

fn main() {
    tauri_build::build()
}
