// ═══════════════════════════════════════════════════════════════
//  VengaiCode Desktop — Portable AI engine lifecycle
//  Spawns the bundled llama-server sidecar against a model file
//  found on a removable drive, health-checks it, and tracks it so
//  it can be stopped later (including on app exit).
// ═══════════════════════════════════════════════════════════════

use std::collections::HashMap;
use std::sync::Mutex;
use std::time::Duration;

use serde::Serialize;
use tauri::api::process::{Command, CommandChild};
use tauri::State;

/// Tracks running portable-engine child processes, keyed by port —
/// managed as Tauri app state so they can be stopped individually or
/// swept on app exit (see main.rs).
#[derive(Default)]
pub struct PortableEngines(pub Mutex<HashMap<u16, CommandChild>>);

#[derive(Serialize, Clone)]
pub struct PortableEngineStatus {
    pub port: u16,
    pub base_url: String,
    pub ready: bool,
}

const HEALTH_CHECK_ATTEMPTS: u32 = 40;
const HEALTH_CHECK_INTERVAL_MS: u64 = 500;

fn stop_child_on_port(engines: &PortableEngines, port: u16) {
    if let Some(child) = engines.0.lock().unwrap().remove(&port) {
        let _ = child.kill();
    }
}

async fn wait_until_healthy(port: u16) -> bool {
    let health_url = format!("http://127.0.0.1:{port}/health");
    let client = reqwest::Client::new();

    for _ in 0..HEALTH_CHECK_ATTEMPTS {
        tokio::time::sleep(Duration::from_millis(HEALTH_CHECK_INTERVAL_MS)).await;
        if let Ok(resp) = client.get(&health_url).send().await {
            if resp.status().is_success() {
                return true;
            }
        }
    }
    false
}

#[tauri::command]
pub async fn launch_portable_model(
    model_path: String,
    port: u16,
    engines: State<'_, PortableEngines>,
) -> Result<PortableEngineStatus, String> {
    // Replace anything already occupying this priority slot's port.
    stop_child_on_port(&engines, port);

    let (mut rx, child) = Command::new_sidecar("llama-server")
        .map_err(|e| format!("Portable AI engine binary not found: {e}"))?
        .args(["--model", &model_path, "--port", &port.to_string(), "--host", "127.0.0.1"])
        .spawn()
        .map_err(|e| format!("Failed to start the portable AI engine: {e}"))?;

    // Drain stdout/stderr in the background so the sidecar never blocks
    // on a full pipe buffer while we're waiting on the health check.
    tauri::async_runtime::spawn(async move {
        while rx.recv().await.is_some() {}
    });

    engines.0.lock().unwrap().insert(port, child);

    if wait_until_healthy(port).await {
        Ok(PortableEngineStatus {
            port,
            base_url: format!("http://127.0.0.1:{port}/v1"),
            ready: true,
        })
    } else {
        stop_child_on_port(&engines, port);
        Err("The portable AI engine didn't become ready in time.".into())
    }
}

#[tauri::command]
pub fn stop_portable_model(port: u16, engines: State<'_, PortableEngines>) {
    stop_child_on_port(&engines, port);
}
