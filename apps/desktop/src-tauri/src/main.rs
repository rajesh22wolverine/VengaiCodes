// ═══════════════════════════════════════════════════════════════
//  VengaiCode — Desktop App — Tauri Entry Point
//
//  The frontend (apps/desktop/src) makes zero `invoke()` calls — it
//  talks to the same VengaiCode backend as the web/mobile apps over
//  plain HTTP via axios (see src/lib/api.ts), exactly like a browser
//  tab would. So this shell needs no custom Tauri commands: it just
//  hosts that same React/Vite build in a native window.
//
//  The src/commands/, src/database/, src/security/ module stubs
//  elsewhere in this crate are pre-existing scaffolding from an
//  earlier, unimplemented plan (licensing/local-DB/encryption
//  features the frontend never ended up calling) — intentionally not
//  wired up here. Nothing currently needs them, and inventing fake
//  behavior for undefined licensing/security requirements would be
//  worse than not building them at all. Left in place, untouched, in
//  case that plan gets revisited with real requirements.
// ═══════════════════════════════════════════════════════════════

#![cfg_attr(
    all(not(debug_assertions), target_os = "windows"),
    windows_subsystem = "windows"
)]

fn main() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error while running the VengaiCode desktop app");
}
