# ═══════════════════════════════════════════════════════════════
#  VengaiCode — package.json Template Builder
#  ai/codegen/manifests/package_json.py — Deterministic package.json
#  construction shared by every JS/TS frontend and backend adapter.
#  Never AI-authored: a known-good, version-pinned dict serialized with
#  json.dumps can't produce invalid JSON the way asking an LLM to
#  freehand a manifest can.
# ═══════════════════════════════════════════════════════════════

import json


def build_package_json(
    name: str,
    scripts: dict[str, str],
    dependencies: dict[str, str],
    dev_dependencies: dict[str, str] | None = None,
) -> str:
    pkg: dict = {
        "name": name,
        "version": "0.1.0",
        "private": True,
        "scripts": scripts,
        "dependencies": dependencies,
    }
    if dev_dependencies:
        pkg["devDependencies"] = dev_dependencies
    return json.dumps(pkg, indent=2) + "\n"
