"""Move the PyInstaller-built backend executable into the Tauri template as
a real sidecar process, patch tauri.conf.json so Tauri actually bundles/
allows it, and repoint the already-injected frontend's API calls at it.

Run from the `build/` working directory, gated by the workflow's
"backend_framework == fastapi" check, AFTER:
  - "Build backend sidecar executable" (PyInstaller ran in ../backend_src,
    producing ../backend_src/dist/backend[.exe])
  - "Inject generated frontend files into template" (so build/src/**
    contains the real generated JS/JSX to repoint, not the template's own
    placeholder files)

Cargo.toml already carries the "process-command-api" feature
unconditionally (see templates/*/src-tauri/Cargo.toml) — declaring it is
harmless with no sidecar reference. tauri.conf.json is different: Tauri
validates at build time that every bundle.externalBin entry has a
matching binaries/<name>-<target-triple> file, so declaring it for a
project with no bundled binary would break EVERY desktop build, not just
backend-less ones — hence the conditional patch here instead of baking it
into the template.

FRONTEND REWRITE, and its one real assumption: every endpoint the AI is
given during codegen is a literal "/api/..." path (see the endpoints_text
format built in codegen/frontend/react.py and codegen/backend/fastapi.py
from the SAME architecture-phase endpoint list), and screens are told to
call it with `fetch`. So generated code should contain literal
'/api/..., "/api/... or `/api/... substrings. This rewrites those to the
sidecar's absolute local URL, because a packaged Tauri window's origin is
NOT the sidecar's — a relative fetch would otherwise try to hit Tauri's
own asset server, not the backend, and silently 404 no matter how correct
the sidecar plumbing is. This is a plain substring rewrite, not a JS
parse, so it cannot be 100% guaranteed against every way the AI might
have phrased a URL — but it is the same literal string every generated
screen was actually given, so it is the highest-confidence mechanical fix
available without executing/parsing the generated JS.
"""
import glob
import json
import os
import platform
import shutil

BACKEND_SRC_DIST = "../backend_src/dist"
BINARIES_DIR = "src-tauri/binaries"
TAURI_CONF_PATH = "src-tauri/tauri.conf.json"
SIDECAR_PORT = 47812  # must match extract_backend_files.py's SIDECAR_PORT
SIDECAR_BASE_URL = f"http://127.0.0.1:{SIDECAR_PORT}"

# GitHub's windows-latest/ubuntu-latest runners are both x86_64 — this
# script only ever runs on those two, from build-windows-installer.yml and
# build-linux-installer.yml, so there is no need to detect anything finer.
_TRIPLES = {
    "Windows": ("x86_64-pc-windows-msvc", ".exe"),
    "Linux": ("x86_64-unknown-linux-gnu", ""),
}


def install_binary() -> None:
    system = platform.system()
    if system not in _TRIPLES:
        print(f"Unsupported platform for backend sidecar: {system} — skipping")
        raise SystemExit(0)

    triple, ext = _TRIPLES[system]
    source_binary = os.path.join(BACKEND_SRC_DIST, f"backend{ext}")

    if not os.path.exists(source_binary):
        print(f"No backend sidecar binary found at {source_binary} — skipping "
              "(the build step must have failed or been skipped)")
        raise SystemExit(1)

    os.makedirs(BINARIES_DIR, exist_ok=True)
    dest_binary = os.path.join(BINARIES_DIR, f"backend-{triple}{ext}")
    shutil.copy2(source_binary, dest_binary)
    print(f"Installed backend sidecar: {dest_binary}")


def patch_tauri_conf() -> None:
    with open(TAURI_CONF_PATH, "r", encoding="utf-8") as f:
        conf = json.load(f)

    tauri_section = conf.setdefault("tauri", {})
    tauri_section.setdefault("bundle", {})["externalBin"] = ["binaries/backend"]

    shell_allowlist = tauri_section.setdefault("allowlist", {}).setdefault("shell", {})
    shell_allowlist["sidecar"] = True
    scope = shell_allowlist.setdefault("scope", [])
    if not any(entry.get("name") == "binaries/backend" for entry in scope):
        scope.append({"name": "binaries/backend", "sidecar": True})

    with open(TAURI_CONF_PATH, "w", encoding="utf-8") as f:
        json.dump(conf, f, indent=2)

    print(f"Patched {TAURI_CONF_PATH}: externalBin=binaries/backend, shell.sidecar=true")


def rewrite_frontend_api_base() -> None:
    replacements = {
        "'/api/": f"'{SIDECAR_BASE_URL}/api/",
        '"/api/': f'"{SIDECAR_BASE_URL}/api/',
        "`/api/": f"`{SIDECAR_BASE_URL}/api/",
    }
    touched = 0
    for path in glob.glob("src/**/*.js*", recursive=True):
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        original = content
        for old, new in replacements.items():
            content = content.replace(old, new)
        if content != original:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            touched += 1
    print(f"Rewrote API base URL to {SIDECAR_BASE_URL} in {touched} frontend file(s)")


install_binary()
patch_tauri_conf()
rewrite_frontend_api_base()
