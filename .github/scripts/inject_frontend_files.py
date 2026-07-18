"""Inject a generated project's frontend/ files into the Tauri build template.

Run from the repo root (where project_files.json was fetched to).
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

    relative_path = path[len("frontend/") :]
    target_path = os.path.join("build", relative_path)
    os.makedirs(os.path.dirname(target_path) or ".", exist_ok=True)

    with open(target_path, "w", encoding="utf-8") as out:
        out.write(content)
    written += 1

print(f"Injected {written} frontend files into build/")
