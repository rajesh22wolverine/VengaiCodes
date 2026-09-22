// ═══════════════════════════════════════════════════════════════
//  VengaiCode — Desktop App — Tauri Entry Point
//
//  The frontend (apps/desktop/src) talks to the same VengaiCode
//  backend as the web/mobile apps over plain HTTP via axios (see
//  src/lib/api.ts) for everything except what needs real OS access:
//  detecting/running a portable AI model off a USB/removable drive
//  (commands::scan, commands::ai — SettingsScreen.tsx), and reading a
//  real installed app's folder for the Reverse App feature's
//  local_folder mode (commands::file — ReverseAppTab.tsx), since the
//  backend is a remote HTTP server with no access to the user's disk.
//
//  The src/database/, src/security/ module stubs (and the unused
//  commands::{auth,export,licence,project} stubs) are pre-existing
//  scaffolding from an earlier, unimplemented plan (licensing/local-DB/
//  encryption features the frontend never ended up calling) —
//  intentionally not wired up here. Left in place, untouched, in case
//  that plan gets revisited with real requirements.
// ═══════════════════════════════════════════════════════════════

#![cfg_attr(
    all(not(debug_assertions), target_os = "windows"),
    windows_subsystem = "windows"
)]

mod commands;

use commands::ai::{launch_portable_model, stop_portable_model, PortableEngines};
use commands::file::scan_local_folder;
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
            scan_local_folder,
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
