"""Stamp the project's app name into src-tauri/tauri.conf.json.

Run from the `build/` working directory, after merge_package_json.py.

The app name is read from project_files.json (fetched to the repo root
before this template was copied into build/) rather than package.json's
own "name"/"productName" fields — frontend/package.json is a protected,
template-owned file (see PROTECTED_FILES in inject_frontend_files.py)
and never actually receives the generated app's real package.json
content, so it can't be trusted as the source of truth here.
"""
import json
import os
import re

PKG_PATH = "package.json"
TAURI_PATH = "src-tauri/tauri.conf.json"
PROJECT_FILES_PATH = "../project_files.json"


# Tauri's bundle.identifier must contain only alphanumeric characters,
# hyphens, and periods (confirmed against the v1 config docs). productName
# feeds directly into the .msi/.exe/.deb/.AppImage output filenames, and
# Debian binary package names disallow spaces/underscores/uppercase, so
# it gets the same safe, lowercase-hyphenated slug rather than the raw
# human-typed app name.
def safe_slug(name: str) -> str:
    slug = re.sub(r"\s+", "-", (name or "").strip().lower())
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "generatedapp"


if not os.path.exists(TAURI_PATH):
    print("tauri.conf.json not found in template; skipping update")
    raise SystemExit(0)

pkg = json.load(open(PKG_PATH, "r", encoding="utf-8"))
cfg = json.load(open(TAURI_PATH, "r", encoding="utf-8"))

project_name = None
if os.path.exists(PROJECT_FILES_PATH):
    try:
        project_name = json.load(open(PROJECT_FILES_PATH, "r", encoding="utf-8")).get("project_name")
    except (json.JSONDecodeError, OSError):
        project_name = None

raw_name = project_name or pkg.get("productName") or pkg.get("name") or "vengaicode-generated-app"
slug = safe_slug(raw_name)
version = pkg.get("version") or "0.1.0"
identifier = f"com.vengaicode.{slug}"

cfg.setdefault("package", {})["productName"] = slug
cfg["package"]["version"] = version
cfg.setdefault("tauri", {}).setdefault("bundle", {})["identifier"] = identifier

with open(TAURI_PATH, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2)

print(f"Updated {TAURI_PATH}: productName={slug} version={version} identifier={identifier}")
