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
    es_modules: bool = False,
) -> str:
    """es_modules: the package's own .js files (vite.config.js, the
    Tailwind and PostCSS configs) are ES modules, not CommonJS — which
    a config importing an ESM-only plugin has to be."""
    pkg: dict = {
        "name": name,
        "version": "0.1.0",
        "private": True,
        **({"type": "module"} if es_modules else {}),
        "scripts": scripts,
        "dependencies": dependencies,
    }
    if dev_dependencies:
        pkg["devDependencies"] = dev_dependencies
    return json.dumps(pkg, indent=2) + "\n"
