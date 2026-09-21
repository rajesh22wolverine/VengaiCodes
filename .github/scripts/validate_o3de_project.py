"""Deep structural validation for a per-project GENERATED O3DE scaffold.

Distinct from validate_o3de_template.py, which checks the static
templates/o3de/ scaffold committed to this repo. This script checks the
AI-generated output for one user's project (app/ai/codegen/o3de.py),
run from package-o3de-project.yml against build/ after
extract/inject_frontend_files.py has written it out.

The previous version of this check (still true, kept here) only asked
"does this parse as JSON, does it have ContainerEntity/Entities". This
adds the checks that actually catch a broken O3DE prefab a human would
hit in the Editor:
  - project.json's required fields are the right TYPE, not just present
    (a Groq/Anthropic-authored JSON structure occasionally drifts a list
    into a string or vice versa — real O3DE parses the file, this catches
    the broken cases before the user does).
  - every component's "Id" field matches the numeric id embedded in its
    own "Component_[<id>]" key. This is the exact invariant o3de.py's
    _new_component() docstring documents fixing a real bug in (mismatched
    ids used to be generated separately for the key vs. the field) — CI
    now enforces it stays fixed instead of relying on manual review.
  - every ScriptEditorComponent's ScriptAsset.assetHint points at a real
    .lua file that exists under Scripts/ in this same build. A dangling
    hint is a broken Script component the Editor can't resolve even with
    the manual one-time re-link step documented in README_O3DE_SETUP.md.
  - EditorEntitySortComponent's "Child Entity Order" only references
    entity keys that actually exist in Entities (catches an orphaned
    ordering list pointing at an entity that was never written).
  - every .lua file under Scripts/ is referenced by at least one entity
    (printed as a WARNING, not a failure — an unwired-but-valid script
    isn't structurally broken, just unused).

Still does NOT open a real O3DE Editor or Asset Processor — see this
repo's package-o3de-project.yml header for why (needs the real engine,
tens of GB, not available on a hosted runner). This is the ceiling of
what's verifiable without one.
"""
import json
import re
import sys
from pathlib import Path

BUILD_ROOT = Path("build")

REQUIRED_PROJECT_JSON_FIELDS = {
    "project_name": str,
    "product_name": str,
    "version": str,
    "executable_name": str,
    "modules": list,
    "project_id": str,
    "display_name": str,
    "icon_path": str,
    "external_subdirectories": list,
    "gem_names": list,
}

_PROJECT_ID_RE = re.compile(r"^\{[0-9A-Fa-f-]{36}\}$")
_COMPONENT_KEY_RE = re.compile(r"^Component_\[(\d+)\]$")

errors: list[str] = []
warnings: list[str] = []


def check_project_json() -> None:
    path = BUILD_ROOT / "project.json"
    if not path.is_file():
        errors.append(f"missing {path}")
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        errors.append(f"invalid JSON in {path}: {e}")
        return
    print(f"valid JSON: {path}")

    for field, expected_type in REQUIRED_PROJECT_JSON_FIELDS.items():
        if field not in data:
            errors.append(f"{path} is missing required field: {field}")
        elif not isinstance(data[field], expected_type):
            errors.append(
                f"{path}.{field} should be {expected_type.__name__}, "
                f"got {type(data[field]).__name__}"
            )

    project_id = data.get("project_id")
    if isinstance(project_id, str) and not _PROJECT_ID_RE.match(project_id):
        errors.append(
            f"{path}.project_id doesn't look like a real O3DE GUID "
            f"(expected '{{XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}}'): {project_id!r}"
        )


def _check_components(entity_label: str, components: dict, valid_lua_paths: set[str]) -> None:
    if not isinstance(components, dict):
        errors.append(f"{entity_label}: Components is not an object")
        return
    for key, component in components.items():
        match = _COMPONENT_KEY_RE.match(key)
        if not match:
            errors.append(f"{entity_label}: component key '{key}' doesn't match Component_[<id>]")
            continue
        key_id = int(match.group(1))

        if "$type" not in component:
            errors.append(f"{entity_label}.{key}: missing $type")
        if "Id" not in component:
            errors.append(f"{entity_label}.{key}: missing Id field")
        elif component["Id"] != key_id:
            errors.append(
                f"{entity_label}.{key}: Id field ({component['Id']}) doesn't match "
                f"the id embedded in its own key ({key_id}) — see o3de.py's "
                f"_new_component() docstring for why this must always match"
            )

        script_type = str(component.get("$type", ""))
        if "ScriptEditorComponent" in script_type:
            script_asset = component.get("ScriptAsset", {})
            asset_hint = script_asset.get("assetHint")
            if not asset_hint:
                errors.append(f"{entity_label}.{key}: ScriptEditorComponent has no ScriptAsset.assetHint")
            elif asset_hint not in valid_lua_paths:
                errors.append(
                    f"{entity_label}.{key}: ScriptAsset.assetHint '{asset_hint}' does not "
                    f"match any .lua file actually present under Scripts/"
                )


def check_prefab(valid_lua_paths: set[str]) -> set[str]:
    """Returns the set of assetHint paths actually referenced, so the
    caller can warn about any .lua file nothing points at."""
    path = BUILD_ROOT / "Levels" / "Main" / "Main.prefab"
    referenced: set[str] = set()
    if not path.is_file():
        errors.append(f"missing {path}")
        return referenced
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        errors.append(f"invalid JSON in {path}: {e}")
        return referenced
    print(f"valid JSON: {path}")

    if "ContainerEntity" not in data or "Entities" not in data:
        errors.append(f"{path} is missing ContainerEntity/Entities — not a valid O3DE prefab shape")
        return referenced

    entities = data["Entities"]
    if not isinstance(entities, dict) or not entities:
        errors.append(f"{path}: Entities is empty or not an object — level has no content")

    container = data["ContainerEntity"]
    _check_components("ContainerEntity", container.get("Components", {}), valid_lua_paths)

    for entity_key, entity in entities.items():
        label = f"Entities.{entity_key}"
        if entity.get("Id") != entity_key:
            errors.append(f"{label}: Id field doesn't match its own dict key")
        if not entity.get("Name"):
            errors.append(f"{label}: missing/empty Name")
        components = entity.get("Components", {})
        _check_components(label, components, valid_lua_paths)
        for component in components.values():
            script_asset = component.get("ScriptAsset")
            if isinstance(script_asset, dict) and script_asset.get("assetHint"):
                referenced.add(script_asset["assetHint"])

    child_order = (
        container.get("Components", {})
        .get(next(
            (k for k, v in container.get("Components", {}).items()
             if v.get("$type") == "EditorEntitySortComponent"), ""
        ), {})
        .get("Child Entity Order", [])
    )
    for child_key in child_order:
        if child_key not in entities:
            errors.append(
                f"ContainerEntity's Child Entity Order references '{child_key}', "
                f"which doesn't exist in Entities"
            )

    return referenced


def check_scripts(referenced: set[str]) -> set[str]:
    scripts_dir = BUILD_ROOT / "Scripts"
    lua_files = sorted(scripts_dir.rglob("*.lua")) if scripts_dir.is_dir() else []
    if not lua_files:
        errors.append("no .lua files found under Scripts/")
        return set()

    valid_paths = set()
    for lua_path in lua_files:
        rel = lua_path.relative_to(BUILD_ROOT).as_posix()
        valid_paths.add(rel)
        print(f"found script: {rel}")

    for rel in valid_paths - referenced:
        warnings.append(f"Scripts/{Path(rel).name} exists but no entity's ScriptAsset references it")

    return valid_paths


# Two-pass: scripts must be enumerated before the prefab check can
# validate assetHint references against them.
_scripts_dir = BUILD_ROOT / "Scripts"
_lua_paths = {
    p.relative_to(BUILD_ROOT).as_posix()
    for p in (_scripts_dir.rglob("*.lua") if _scripts_dir.is_dir() else [])
}

check_project_json()
referenced_scripts = check_prefab(_lua_paths)
check_scripts(referenced_scripts)

if warnings:
    print("\nWarnings (non-fatal):")
    for w in warnings:
        print(f"  - {w}")

if errors:
    print("\nO3DE project validation FAILED:")
    for err in errors:
        print(f"  - {err}")
    sys.exit(1)

print("\nO3DE project validation passed.")
