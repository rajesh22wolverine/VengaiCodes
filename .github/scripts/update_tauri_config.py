"""Stamp the merged package.json's name/version into src-tauri/tauri.conf.json.

Run from the `build/` working directory, after merge_package_json.py.
"""
import json
import os
import re

PKG_PATH = "package.json"
TAURI_PATH = "src-tauri/tauri.conf.json"

# Tauri's bundle.identifier must contain only alphanumeric characters,
# hyphens, and periods (confirmed against the v1 config docs) — npm package
# names are allowed underscores and other characters .replace(' ', '') alone
# doesn't strip, so a name like "my_todo_app" produced an identifier segment
# Tauri's bundler would reject. Strip anything outside that charset instead.
def safe_identifier_segment(name: str) -> str:
    slug = re.sub(r"[^a-z0-9-]", "", name.lower())
    return slug or "generatedapp"


if not os.path.exists(TAURI_PATH):
    print("tauri.conf.json not found in template; skipping update")
    raise SystemExit(0)

pkg = json.load(open(PKG_PATH, "r", encoding="utf-8"))
cfg = json.load(open(TAURI_PATH, "r", encoding="utf-8"))

name = pkg.get("name") or pkg.get("productName") or "vengaicode-generated-app"
version = pkg.get("version") or "0.1.0"
identifier = f"com.vengaicode.{safe_identifier_segment(name)}"

cfg.setdefault("package", {})["productName"] = name
cfg["package"]["version"] = version
cfg.setdefault("tauri", {}).setdefault("bundle", {})["identifier"] = identifier

with open(TAURI_PATH, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2)

print(f"Updated {TAURI_PATH}: productName={name} version={version} identifier={identifier}")
