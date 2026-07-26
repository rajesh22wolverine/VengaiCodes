// ═══════════════════════════════════════════════════════════════
//  VengaiCode — Desktop App — Tauri Entry Point
//
//  The frontend (apps/desktop/src) talks to the same VengaiCode
//  backend as the web/mobile apps over plain HTTP via axios (see
//  src/lib/api.ts) for everything except one thing: detecting and
//  running a portable AI model off a USB/removable drive needs real
//  OS access (drive enumeration, spawning a local inference engine),
//  which only the Rust side can do — see commands::scan and
//  commands::ai, invoked from SettingsScreen.tsx via `invoke()`.
//
//  The src/database/, src/security/ module stubs (and the unused
//  commands::{auth,export,file,licence,project} stubs) are
//  pre-existing scaffolding from an earlier, unimplemented plan
//  (licensing/local-DB/encryption features the frontend never ended
//  up calling) — intentionally not wired up here. Left in place,
//  untouched, in case that plan gets revisited with real requirements.
// ═══════════════════════════════════════════════════════════════

#![cfg_attr(
    all(not(debug_assertions), target_os = "windows"),
    windows_subsystem = "windows"
)]

mod commands;

use commands::ai::{launch_portable_model, stop_portable_model, PortableEngines};
use commands::scan::{list_removable_drives, scan_drive_for_models};
use tauri::Manager;

fn main() {
    tauri::Builder::default()
        .manage(PortableEngines::default())
        .invoke_handler(tauri::generate_handler![
            list_removable_drives,
            scan_drive_for_models,
            launch_portable_model,
            stop_portable_model,
        ])
        .build(tauri::generate_context!())
        .expect("error while building the VengaiCode desktop app")
        .run(|app_handle, event| {
            // Make sure no portable-engine child process outlives the app.
            if let tauri::RunEvent::Exit = event {
                let engines = app_handle.state::<PortableEngines>();
                let mut children = engines.0.lock().unwrap();
                for (_, child) in children.drain() {
                    let _ = child.kill();
                }
            }
        });
}
