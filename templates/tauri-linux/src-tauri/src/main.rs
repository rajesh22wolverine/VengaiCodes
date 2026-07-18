// ═══════════════════════════════════════════════════════════════
//  VengaiCode — Generated App — Tauri Entry Point
//  This is a minimal, fixed Tauri shell. It is NOT AI-generated —
//  it is a stable template that wraps whatever frontend was built
//  by VengaiCode's code generation pipeline (the "distDir" in
//  tauri.conf.json points at that frontend's build output).
// ═══════════════════════════════════════════════════════════════

#![cfg_attr(
    all(not(debug_assertions), target_os = "windows"),
    windows_subsystem = "windows"
)]

fn main() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error while running VengaiCode generated app");
}