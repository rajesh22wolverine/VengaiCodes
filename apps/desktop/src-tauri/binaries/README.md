# Portable AI engine binary (manual setup required)

The "Detect Portable AI Model" feature spawns a bundled `llama-server`
binary (from [llama.cpp](https://github.com/ggml-org/llama.cpp), MIT
licensed) to run `.gguf` model files found on a USB drive.

This directory needs the actual binary before the feature works. It is
gitignored (`.gitignore`: `binaries/*.exe`, `binaries/*.dll`), so it is
never committed.

**CI fetches it automatically.** `.github/workflows/build-desktop-
windows.yml` downloads a pinned llama.cpp Windows release and drops the
sidecar here before `tauri build` runs — a fresh runner has nothing in
this directory, and `tauri.conf.json` treats the sidecar as a hard build
dependency, so without that step the build fails with "path matching
binaries/llama-server-x86_64-pc-windows-msvc.exe not found." Bump
`LLAMA_CPP_TAG` in that workflow to move the engine version.

The manual steps below are only needed for **local** desktop builds.

## Setup (Windows, local builds only)

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
