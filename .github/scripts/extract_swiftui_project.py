"""Extract a generated SwiftUI project's files into build/, flat.

Run from the repo root (where project_files.json was fetched to). Unlike
inject_frontend_files.py (which merges generated files INTO a checked-in
Tauri template, protecting the template's own build-tooling config), a
SwiftUI project has no template to merge into — app/ai/codegen/frontend/
swiftui.py's manifest_files()/entry_point_files() already produced every
file the project needs (the .swift screens, the @main App struct, and a
real XcodeGen project.yml), so this just writes them out.
"""
import json
import os

with open("project_files.json", "r", encoding="utf-8") as f:
    data = json.load(f)

files = data.get("files", [])
written = 0

for file_entry in files:
    path = file_entry.get("path", "")
    content = file_entry.get("content", "")

    if not path.startswith("frontend/"):
        continue

    relative_path = path[len("frontend/"):]
    target_path = os.path.join("build", relative_path)
    os.makedirs(os.path.dirname(target_path) or ".", exist_ok=True)

    with open(target_path, "w", encoding="utf-8") as out:
        out.write(content)
    written += 1

if written == 0:
    raise SystemExit("No frontend/ files found in project_files.json — nothing to build.")

print(f"Extracted {written} SwiftUI project files into build/")
