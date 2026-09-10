"""Move the built backend executable into the Tauri template as a real
sidecar process, patch tauri.conf.json so Tauri actually bundles/allows
it, and repoint the already-injected frontend's API calls at it.

Run from the `build/` working directory, gated by the workflow's
"sidecar_kind != none" check, AFTER:
  - the framework's build step ran in ../backend_src (PyInstaller for
    fastapi/flask/django, `cargo build --release` for actix/axum, `go
    build` for gin)
  - "Inject generated frontend files into template" (so build/src/**
    contains the real generated JS/JSX to repoint, not the template's own
    placeholder files)

Reads BACKEND_FRAMEWORK from the environment (set by the workflow) to
pick the right source binary path and sidecar port — see SIDECAR_PORTS
below for why the port differs per framework.

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
format built in codegen/frontend/react.py and every codegen/backend/*.py
adapter, all from the SAME architecture-phase endpoint list), and screens
are told to call it with `fetch`. So generated code should contain
literal '/api/..., "/api/... or `/api/... substrings. This rewrites those
to the sidecar's absolute local URL, because a packaged Tauri window's
origin is NOT the sidecar's — a relative fetch would otherwise try to hit
Tauri's own asset server, not the backend, and silently 404 no matter how
correct the sidecar plumbing is. This is a plain substring rewrite, not a
JS parse, so it cannot be 100% guaranteed against every way the AI might
have phrased a URL — but it is the same literal string every generated
screen was actually given, so it is the highest-confidence mechanical fix
available without executing/parsing the generated JS.
"""
import glob
import json
import os
import platform
import re
import shutil

BINARIES_DIR = "src-tauri/binaries"
TAURI_CONF_PATH = "src-tauri/tauri.conf.json"

# fastapi/flask/django have no port of their own — _sidecar_run.py (see
# extract_backend_files.py) picks 47812. actix/axum/gin are different:
# their generated main.rs/main.go already hardcodes 127.0.0.1:8080 (or
# :8080 on all interfaces for gin) with no override mechanism, so the
# frontend rewrite has to target THAT port instead for those three.
SIDECAR_PORTS = {
    "fastapi": 47812,
    "flask": 47812,
    "django": 47812,
    "actix": 8080,
    "axum": 8080,
    "gin": 8080,
}

# GitHub's windows-latest/ubuntu-latest runners are both x86_64 — this
# script only ever runs on those two, from build-windows-installer.yml and
# build-linux-installer.yml, so there is no need to detect anything finer.
_TRIPLES = {
    "Windows": ("x86_64-pc-windows-msvc", ".exe"),
    "Linux": ("x86_64-unknown-linux-gnu", ""),
}


def _rust_crate_name() -> str:
    """The actix/axum sidecar's compiled binary is named after Cargo.toml's
    [package] name (build_backend_sidecar has no other way to know it —
    see codegen/backend/actix.py's _cargo_toml(), which derives it from
    the project's own name), NOT a fixed "backend" like the other
    frameworks — read it straight out of the generated Cargo.toml rather
    than re-deriving the same slug independently and risking drift."""
    cargo_toml_path = "../backend_src/Cargo.toml"
    with open(cargo_toml_path, "r", encoding="utf-8") as f:
        content = f.read()
    match = re.search(r'^\s*name\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if not match:
        raise RuntimeError(f"Could not find [package] name in {cargo_toml_path}")
    return match.group(1)


def _source_binary(framework: str, ext: str) -> str:
    if framework in ("fastapi", "flask", "django"):
        return f"../backend_src/dist/backend{ext}"
    if framework in ("actix", "axum"):
        return f"../backend_src/target/release/{_rust_crate_name()}{ext}"
    if framework == "gin":
        return f"../backend_src/dist_go/backend{ext}"
    raise ValueError(f"No sidecar bundling wired up for backend framework {framework!r}")


def install_binary(framework: str) -> None:
    system = platform.system()
    if system not in _TRIPLES:
        print(f"Unsupported platform for backend sidecar: {system} — skipping")
        raise SystemExit(0)

    triple, ext = _TRIPLES[system]
    source_binary = _source_binary(framework, ext)

    if not os.path.exists(source_binary):
        print(f"No backend sidecar binary found at {source_binary} — skipping "
              "(the build step must have failed or been skipped)")
        raise SystemExit(1)

    os.makedirs(BINARIES_DIR, exist_ok=True)
    dest_binary = os.path.join(BINARIES_DIR, f"backend-{triple}{ext}")
    shutil.copy2(source_binary, dest_binary)
    print(f"Installed backend sidecar ({framework}): {dest_binary}")


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


def rewrite_frontend_api_base(sidecar_base_url: str) -> None:
    replacements = {
        "'/api/": f"'{sidecar_base_url}/api/",
        '"/api/': f'"{sidecar_base_url}/api/',
        "`/api/": f"`{sidecar_base_url}/api/",
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
    print(f"Rewrote API base URL to {sidecar_base_url} in {touched} frontend file(s)")


framework = os.environ.get("BACKEND_FRAMEWORK", "")
port = SIDECAR_PORTS.get(framework)
if port is None:
    print(f"No sidecar bundling wired up for backend framework {framework!r} — skipping")
    raise SystemExit(0)

install_binary(framework)
patch_tauri_conf()
rewrite_frontend_api_base(f"http://127.0.0.1:{port}")
