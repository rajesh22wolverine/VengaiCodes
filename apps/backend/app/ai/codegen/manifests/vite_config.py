# ═══════════════════════════════════════════════════════════════
#  VengaiCode — vite.config.js Template Builder
#  ai/codegen/manifests/vite_config.py — Shared by the Vite-based
#  frontend adapters (React, Vue, Svelte). With an API proxy target, the
#  dev server forwards /api/* to the backend, so screens that call
#  relative /api/... URLs reach it in development exactly as they would
#  behind one origin in production — no CORS setup, no hard-coded host.
# ═══════════════════════════════════════════════════════════════

import json


def build_vite_config(
    plugin_import: str, plugin_call: str, api_proxy_target: str | None = None
) -> str:
    lines = [
        "import { defineConfig } from 'vite';",
        plugin_import,
        "",
        "export default defineConfig({",
        f"  plugins: [{plugin_call}],",
    ]
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
