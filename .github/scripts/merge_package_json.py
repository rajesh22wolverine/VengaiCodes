"""Merge a generated project's package.json into the Tauri template's package.json.

Run from the `build/` working directory. Keeps the template's build tooling
(vite, tauri CLI, tailwind, scripts) while taking the generated app's own
dependencies and metadata, so injection of a generated frontend can't
accidentally drop the devDependencies the rest of the workflow needs.
"""
import json
import os

GENERATED_PATH = "package.json"
TEMPLATE_PATH = os.environ.get(
    "TEMPLATE_PACKAGE_JSON_PATH", "../templates/tauri-windows/package.json"
)

if not os.path.exists(GENERATED_PATH):
    import shutil

    shutil.copy(TEMPLATE_PATH, GENERATED_PATH)
    print("No generated package.json found — used template package.json as-is")
    raise SystemExit(0)

generated = json.load(open(GENERATED_PATH, "r", encoding="utf-8"))
template = json.load(open(TEMPLATE_PATH, "r", encoding="utf-8"))

merged = dict(template)
merged["name"] = generated.get("name") or template.get("name")
merged["version"] = generated.get("version") or template.get("version")

merged_deps = dict(template.get("dependencies", {}))
merged_deps.update(generated.get("dependencies", {}))
merged["dependencies"] = merged_deps

merged_dev_deps = dict(generated.get("devDependencies", {}))
merged_dev_deps.update(template.get("devDependencies", {}))
merged["devDependencies"] = merged_dev_deps

merged["scripts"] = template.get("scripts", {})

with open(GENERATED_PATH, "w", encoding="utf-8") as f:
    json.dump(merged, f, indent=2)

print(
    f"Merged package.json: {len(merged_deps)} dependencies, "
    f"{len(merged_dev_deps)} devDependencies"
)
