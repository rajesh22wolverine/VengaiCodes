"""Stamp the merged package.json's name/version into src-tauri/tauri.conf.json.

Run from the `build/` working directory, after merge_package_json.py.
"""
import json
import os

PKG_PATH = "package.json"
TAURI_PATH = "src-tauri/tauri.conf.json"

if not os.path.exists(TAURI_PATH):
    print("tauri.conf.json not found in template; skipping update")
    raise SystemExit(0)

pkg = json.load(open(PKG_PATH, "r", encoding="utf-8"))
cfg = json.load(open(TAURI_PATH, "r", encoding="utf-8"))

name = pkg.get("name") or pkg.get("productName") or "vengaicode-generated-app"
version = pkg.get("version") or "0.1.0"
identifier = f"com.vengaicode.{name.replace(' ', '').lower()}"

cfg.setdefault("package", {})["productName"] = name
cfg["package"]["version"] = version
cfg.setdefault("tauri", {}).setdefault("bundle", {})["identifier"] = identifier

with open(TAURI_PATH, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2)

print(f"Updated {TAURI_PATH}: productName={name} version={version} identifier={identifier}")
