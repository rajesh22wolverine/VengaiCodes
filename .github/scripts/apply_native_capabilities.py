"""Add native-capability Capacitor plugin dependencies to package.json.

Run from the `build/` working directory, after merge_package_json.py and
before `npm install`. Reads the native_capabilities list the backend
detected from the project's own requirements (see detect_native_capabilities
in apps/backend/app/api/v1/codegen.py) out of ../project_files.json, and adds
the matching plugin package for each one.

Pinned to ^5.0.0 to match the template's @capacitor/core@^5.7.0 /
@capacitor/android@^5.7.0 — Capacitor's plugins peer-depend on a matching
major version, and mixing a newer major plugin with a v5 core/android
breaks `npx cap sync`.
"""
import json

PROJECT_FILES_PATH = "../project_files.json"
PACKAGE_JSON_PATH = "package.json"

PLUGIN_VERSIONS = {
    "camera": ("@capacitor/camera", "^5.0.0"),
    "push_notifications": ("@capacitor/push-notifications", "^5.0.0"),
    "geolocation": ("@capacitor/geolocation", "^5.0.0"),
    "offline_storage": ("@capacitor/preferences", "^5.0.0"),
    "share": ("@capacitor/share", "^5.0.0"),
}

with open(PROJECT_FILES_PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

capabilities = data.get("native_capabilities", [])
if not capabilities:
    print("No native capabilities detected for this project — skipping plugin injection")
    raise SystemExit(0)

with open(PACKAGE_JSON_PATH, "r", encoding="utf-8") as f:
    pkg = json.load(f)

deps = pkg.setdefault("dependencies", {})
added = []
for capability in capabilities:
    plugin = PLUGIN_VERSIONS.get(capability)
    if plugin:
        name, version = plugin
        deps[name] = version
        added.append(name)

with open(PACKAGE_JSON_PATH, "w", encoding="utf-8") as f:
    json.dump(pkg, f, indent=2)

print(f"Added native capability plugins: {', '.join(added) if added else '(none matched)'}")
