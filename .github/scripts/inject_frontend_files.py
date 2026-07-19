"""Inject a generated project's frontend/ files into the Tauri build template.

Run from the repo root (where project_files.json was fetched to).
"""
import json
import os

with open("project_files.json", "r", encoding="utf-8") as f:
    data = json.load(f)

files = data.get("files", [])
written = 0
skipped = 0

# Build-tooling config the template owns — it's written to match the
# template's Vite/Tauri/ESM setup (e.g. postcss.config.js is ESM because
# the template's package.json is "type": "module"). A generated app's own
# copy of these follows whatever scaffold the AI used and isn't guaranteed
# to match, so overwriting the template's version breaks the build (see
# package.json, which gets the same treatment via merge_package_json.py).
PROTECTED_FILES = {
    "package.json",
    "postcss.config.js",
    "postcss.config.cjs",
    "postcss.config.ts",
    "tailwind.config.js",
    "tailwind.config.cjs",
    "tailwind.config.ts",
    "vite.config.js",
    "vite.config.ts",
    "vite.config.mjs",
}

for file_entry in files:
    path = file_entry.get("path", "")
    content = file_entry.get("content", "")

    if not path.startswith("frontend/"):
        continue

    relative_path = path[len("frontend/") :]

    if relative_path in PROTECTED_FILES:
        skipped += 1
        continue

    target_path = os.path.join("build", relative_path)
    os.makedirs(os.path.dirname(target_path) or ".", exist_ok=True)

    with open(target_path, "w", encoding="utf-8") as out:
        out.write(content)
    written += 1

print(f"Injected {written} frontend files into build/ ({skipped} template-owned config files skipped)")
