"""Structural validation for templates/o3de/ - CI-friendly, no engine required.

Checks that the O3DE scaffold hasn't silently broken: required files exist,
project.json/the level prefab parse as valid JSON. Does NOT attempt to
actually build or run an O3DE project - that requires a real O3DE engine
install (tens of GB, no GPU on hosted runners) and is intentionally out of
scope for hosted CI. See templates/o3de/README.md.

Lua syntax itself is checked separately in the workflow via `luac -p`
(not here) since that needs the `lua`/`luac` binary, not just Python stdlib.
"""
import json
import sys
from pathlib import Path

TEMPLATE_ROOT = Path("templates/o3de")

REQUIRED_FILES = [
    "project.json",
    "README.md",
    "build_o3de_project.sh",
    "build_o3de_project.ps1",
    "Levels/Main/Main.prefab",
    "Scripts/main.lua",
]

# Real O3DE project.json fields - see o3de.py's _project_json() and this
# module's own header for where these were confirmed (AutomatedTesting/
# project.json in the o3de/o3de repo).
REQUIRED_PROJECT_JSON_FIELDS = [
    "project_name", "product_name", "version", "executable_name",
    "modules", "project_id", "display_name", "icon_path",
    "external_subdirectories", "gem_names",
]

errors = []


def check_required_files():
    for rel_path in REQUIRED_FILES:
        path = TEMPLATE_ROOT / rel_path
        if not path.is_file():
            errors.append(f"missing required file: {path}")
        else:
            print(f"found: {path}")


def check_project_json():
    path = TEMPLATE_ROOT / "project.json"
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        errors.append(f"invalid JSON in {path}: {e}")
        return
    print(f"valid JSON: {path}")
    for field in REQUIRED_PROJECT_JSON_FIELDS:
        if field not in data:
            errors.append(f"{path} is missing required field: {field}")


def check_prefab_json(rel_path):
    path = TEMPLATE_ROOT / rel_path
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        errors.append(f"invalid JSON in {path}: {e}")
        return
    print(f"valid JSON: {path}")
    if "ContainerEntity" not in data or "Entities" not in data:
        errors.append(f"{path} is missing ContainerEntity/Entities - not a valid O3DE prefab shape")


check_required_files()
check_project_json()
check_prefab_json("Levels/Main/Main.prefab")

if errors:
    print("\nO3DE template validation FAILED:")
    for err in errors:
        print(f"  - {err}")
    sys.exit(1)

print("\nO3DE template validation passed.")
