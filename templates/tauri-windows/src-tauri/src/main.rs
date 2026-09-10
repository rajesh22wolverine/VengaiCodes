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

use std::sync::Mutex;

use tauri::api::process::{Command, CommandChild, CommandEvent};
use tauri::Manager;

// Holds the spawned backend sidecar's child handle, if this app has one
// bundled at all — only FastAPI-backed projects get an externalBin entry
// at packaging time (see .github/scripts/install_backend_sidecar.py).
// Stored so it can be killed when the window closes instead of outliving
// the app as an orphaned process still holding the port open.
struct BackendSidecar(Mutex<Option<CommandChild>>);

fn main() {
    tauri::Builder::default()
        .manage(BackendSidecar(Mutex::new(None)))
        .setup(|app| {
            // Not every generated app has a bundled backend — new_sidecar()
            // simply fails here for everyone else, and that failure is
            // expected, not an error: log it and let the window open
            // normally either way.
            let sidecar = match Command::new_sidecar("backend") {
                Ok(cmd) => cmd,
                Err(err) => {
                    eprintln!("[backend sidecar] not bundled for this app: {err}");
                    return Ok(());
                }
            };

            // The generated backend's SQLite path is a CWD-relative
            // "./app.db" (see codegen/backend/fastapi.py's _DATABASE_PY) —
            // the install directory a desktop app launches from (e.g.
            // Program Files on Windows) is often not writable, so the
            // sidecar's working directory is pinned to the app's own data
            // dir instead.
            let data_dir = app
                .path_resolver()
                .app_data_dir()
                .unwrap_or_else(std::env::temp_dir);
            if let Err(err) = std::fs::create_dir_all(&data_dir) {
                eprintln!("[backend sidecar] could not create data dir {data_dir:?}: {err}");
            }

            match sidecar.current_dir(data_dir).spawn() {
                Ok((mut rx, child)) => {
                    *app.state::<BackendSidecar>().0.lock().unwrap() = Some(child);

                    tauri::async_runtime::spawn(async move {
                        while let Some(event) = rx.recv().await {
                            if let CommandEvent::Stderr(line) = event {
                                eprintln!("[backend] {line}");
                            }
                        }
                    });
                }
                Err(err) => eprintln!("[backend sidecar] failed to spawn: {err}"),
            }

            Ok(())
        })
        .on_window_event(|event| {
            // The sidecar is NOT killed automatically when the window
            // closes (a known Tauri v1 behavior) — without this it would
            // keep running, holding the port, until the OS reaps it.
            if let tauri::WindowEvent::Destroyed = event.event() {
                let state = event.window().state::<BackendSidecar>();
                let mut guard = state.0.lock().unwrap();
                if let Some(child) = guard.take() {
                    let _ = child.kill();
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running VengaiCode generated app");
}
