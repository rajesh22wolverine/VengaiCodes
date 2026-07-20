"""Stamp the merged package.json's name into capacitor.config.json.

Run from the `build/` working directory, after merge_package_json.py.
"""
import json
import os
import re

PKG_PATH = "package.json"
CAPACITOR_CONFIG_PATH = "capacitor.config.json"

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

name = pkg.get("name") or pkg.get("productName") or "vengaicode-generated-app"
slug = safe_package_segment(name)
app_id = f"com.vengaicode.{slug}"

cfg["appId"] = app_id
cfg["appName"] = name

with open(CAPACITOR_CONFIG_PATH, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2)

print(f"Updated {CAPACITOR_CONFIG_PATH}: appId={app_id} appName={name}")
