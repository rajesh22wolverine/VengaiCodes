"""Stamp the project's app name into capacitor.config.json.

Run from the `build/` working directory, after merge_package_json.py.

The app name is read from project_files.json (see update_tauri_config.py
for why package.json's own "name" field can't be trusted here — it's a
protected, template-owned file that never receives the generated app's
real package.json content).
"""
import json
import os
import re

PKG_PATH = "package.json"
CAPACITOR_CONFIG_PATH = "capacitor.config.json"
PROJECT_FILES_PATH = "../project_files.json"

# Android/Java package segments can't start with a digit or be a reserved
# word (e.g. project name "3D Notes" -> "3dnotes" is an invalid applicationId
# and breaks `cap add android`/Gradle; "Class Tracker" -> "class" collides
# with the keyword). Prefix with "app" in either case rather than failing.
JAVA_RESERVED_WORDS = {
    "abstract", "assert", "boolean", "break", "byte", "case", "catch", "char",
    "class", "const", "continue", "default", "do", "double", "else", "enum",
    "extends", "final", "finally", "float", "for", "goto", "if", "implements",
    "import", "instanceof", "int", "interface", "long", "native", "new",
    "package", "private", "protected", "public", "return", "short", "static",
    "strictfp", "super", "switch", "synchronized", "this", "throw", "throws",
    "transient", "try", "void", "volatile", "while", "true", "false", "null",
}


def safe_package_segment(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]", "", name.lower())
    if not slug:
        return "generatedapp"
    if slug[0].isdigit() or slug in JAVA_RESERVED_WORDS:
        return f"app{slug}"
    return slug


if not os.path.exists(CAPACITOR_CONFIG_PATH):
    print("capacitor.config.json not found in template; skipping update")
    raise SystemExit(0)

pkg = json.load(open(PKG_PATH, "r", encoding="utf-8"))
cfg = json.load(open(CAPACITOR_CONFIG_PATH, "r", encoding="utf-8"))

project_name = None
if os.path.exists(PROJECT_FILES_PATH):
    try:
        project_name = json.load(open(PROJECT_FILES_PATH, "r", encoding="utf-8")).get("project_name")
    except (json.JSONDecodeError, OSError):
        project_name = None

raw_name = project_name or pkg.get("productName") or pkg.get("name") or "vengaicode-generated-app"

# appId needs the strict, package-safe slug; appName is the label shown
# on the device under the launcher icon, so it stays human-readable —
# just stripped of control characters that would corrupt the XML/JSON
# it ends up in.
display_name = re.sub(r"[\x00-\x1f]", "", raw_name).strip() or "VengaiCode App"
slug = safe_package_segment(raw_name)
app_id = f"com.vengaicode.{slug}"

cfg["appId"] = app_id
cfg["appName"] = display_name

with open(CAPACITOR_CONFIG_PATH, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2)

print(f"Updated {CAPACITOR_CONFIG_PATH}: appId={app_id} appName={display_name}")
