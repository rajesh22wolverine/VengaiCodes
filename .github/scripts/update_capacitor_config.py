"""Stamp the merged package.json's name into capacitor.config.json.

Run from the `build/` working directory, after merge_package_json.py.
"""
import json
import os
import re

PKG_PATH = "package.json"
CAPACITOR_CONFIG_PATH = "capacitor.config.json"

if not os.path.exists(CAPACITOR_CONFIG_PATH):
    print("capacitor.config.json not found in template; skipping update")
    raise SystemExit(0)

pkg = json.load(open(PKG_PATH, "r", encoding="utf-8"))
cfg = json.load(open(CAPACITOR_CONFIG_PATH, "r", encoding="utf-8"))

name = pkg.get("name") or pkg.get("productName") or "vengaicode-generated-app"
slug = re.sub(r"[^a-z0-9]", "", name.lower()) or "generatedapp"
app_id = f"com.vengaicode.{slug}"

cfg["appId"] = app_id
cfg["appName"] = name

with open(CAPACITOR_CONFIG_PATH, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2)

print(f"Updated {CAPACITOR_CONFIG_PATH}: appId={app_id} appName={name}")
