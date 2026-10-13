# ═══════════════════════════════════════════════════════════════
#  VengaiCode — vite.config.js Template Builder
#  ai/codegen/manifests/vite_config.py — Shared by the Vite-based
#  frontend adapters (React, Vue, Svelte, and plain HTML/JS, which needs
#  no plugin). With an API proxy target, the
#  dev server forwards /api/* to the backend, so screens that call
#  relative /api/... URLs reach it in development exactly as they would
#  behind one origin in production — no CORS setup, no hard-coded host.
# ═══════════════════════════════════════════════════════════════

import json


def build_vite_config(
    plugin_import: str | None,
    plugin_call: str | None,
    api_proxy_target: str | None = None,
) -> str:
    """plugin_import / plugin_call: the framework's Vite plugin, or None
    for a project Vite builds without one."""
    lines = ["import { defineConfig } from 'vite';"]
    if plugin_import:
        lines.append(plugin_import)
    lines += ["", "export default defineConfig({"]
    if plugin_call:
        lines.append(f"  plugins: [{plugin_call}],")
    if api_proxy_target:
        lines += [
            "  server: {",
            "    // Development only: send /api/* to the backend (set VITE_API_PROXY to override).",
            "    proxy: {",
            "      '/api': {",
            f"        target: process.env.VITE_API_PROXY || {json.dumps(api_proxy_target)},",
            "        changeOrigin: true,",
            "      },",
            "    },",
            "  },",
        ]
    lines += ["});", ""]
    return "\n".join(lines)
