# Portable AI engine binary (manual setup required)

The "Detect Portable AI Model" feature spawns a bundled `llama-server`
binary (from [llama.cpp](https://github.com/ggml-org/llama.cpp), MIT
licensed) to run `.gguf` model files found on a USB drive.

This directory needs the actual binary before the feature works. It is
gitignored, so it is never committed.

**CI fetches it automatically, on both platforms.**
`.github/workflows/build-desktop-windows.yml` and
`build-desktop-linux.yml` each download the same pinned llama.cpp
release and drop the sidecar here before `tauri build` runs — a fresh
runner has nothing in this directory, and `tauri.conf.json` treats the
sidecar as a hard build dependency, so without that step the build fails
with "path matching binaries/llama-server-<triple> not found." Bump
`LLAMA_CPP_TAG` in **both** workflows together; shipping a different
engine version per OS means a bug reproduces on one and not the other.

## Why the resource config is split per platform

The sidecar is a thin launcher that loads the real engine from shared
libraries beside it — `*.dll` on Windows, `*.so*` on Linux. Those have
to be declared in `bundle.resources` or the installer ships a launcher
with nothing to launch.

They cannot both live in `tauri.conf.json`. Tauri v1 treats a resource
glob that matches **zero** files as a hard error, so a Windows build
dies on `path matching binaries/*.so* not found.` and a Linux build dies
on `path matching binaries/*.dll not found.` — this is exactly how runs
34216459894 and 34216456420 failed on 2026-09-08.

So `bundle.resources` is absent from the shared config and lives only in
`tauri.windows.conf.json` / `tauri.linux.conf.json`, which Tauri merges
in per target. Keep it that way: moving either glob back into the base
config breaks the *other* platform's build.

## Setup (local builds only)

CI does this for you; these steps are only for building on your own
machine.

1. Download the release asset for your OS from
   https://github.com/ggml-org/llama.cpp/releases — `win-cpu-x64.zip` or
   `ubuntu-x64.tar.gz`, matching the `LLAMA_CPP_TAG` pinned in the
   workflows.
2. Rename `llama-server` to match Tauri v1's sidecar naming convention
   (binary name + target triple):
   ```
   llama-server-x86_64-pc-windows-msvc.exe     # Windows
   llama-server-x86_64-unknown-linux-gnu       # Linux
   ```
3. Place it in this directory, along with every `*.dll` (Windows) or
   `*.so*` (Linux) from the same archive.

`tauri.conf.json`'s `bundle.externalBin` already points at
`binaries/llama-server` — Tauri appends the target triple automatically
at build time.

macOS isn't set up (`icons/icon.icns` is still an empty stub, so nothing
builds there yet) — add `llama-server-*-apple-darwin` plus a
`tauri.macos.conf.json` with the matching `*.dylib` glob if that
platform ever ships.
