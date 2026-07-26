# Portable AI engine binary (manual setup required)

The "Detect Portable AI Model" feature spawns a bundled `llama-server`
binary (from [llama.cpp](https://github.com/ggml-org/llama.cpp), MIT
licensed) to run `.gguf` model files found on a USB drive.

This directory needs the actual binary before the feature works — it
isn't fetched automatically by this repo.

## Setup (Windows)

1. Download the latest Windows release asset from
   https://github.com/ggml-org/llama.cpp/releases (look for a `win-*.zip`
   build containing `llama-server.exe`).
2. Rename it to match Tauri v1's sidecar naming convention (binary name
   + target triple):
   ```
   llama-server-x86_64-pc-windows-msvc.exe
   ```
3. Place it in this directory:
   `apps/desktop/src-tauri/binaries/llama-server-x86_64-pc-windows-msvc.exe`

`tauri.conf.json`'s `bundle.externalBin` already points at
`binaries/llama-server` — Tauri appends the target triple automatically
at build time.

Linux/macOS sidecars aren't set up yet (the desktop app's only
confirmed-live build today is Windows) — add
`llama-server-x86_64-unknown-linux-gnu` / `llama-server-*-apple-darwin`
here later if those platforms need this feature too.
