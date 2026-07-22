# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Vue Frontend Adapter
#  ai/codegen/frontend/vue.py — Screen generation moved verbatim from
#  the old codegen.py generate_screen_file()'s "vue_express" branch. No
#  behavior change from the pre-adapter version — note this branch never
#  wired in native_capabilities (unlike react.py's), preserved as-is.
# ═══════════════════════════════════════════════════════════════

from app.ai.codegen.manifests.package_json import build_package_json
from app.ai.codegen.types import FileResult, FrontendAdapter, ScreenCtx, WiringCtx
from app.ai.codegen_shared import GROQ_FILE_MAX_TOKENS, GeneratedFile, _pascal, generate_text_validated


async def generate_screen(ctx: ScreenCtx) -> FileResult:
    screen_name = ctx.screen.get("name", "Screen")
    component_name = _pascal(screen_name)
    endpoints_text = "\n".join(
        f"- {e.get('method')} {e.get('path')}: {e.get('purpose')}" for e in ctx.endpoints
    )

    prompt = f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Write ONE complete, real Vue 3 Single File Component for the "{screen_name}" screen of this app.

App: {ctx.project_name}
{ctx.requirements_text}
Screen purpose: {ctx.screen.get('purpose', '')}

API endpoints this screen can call:
{endpoints_text}

Requirements:
- Use `<script setup>` composition API syntax.
- Fetch real data from the relevant API endpoints above (use `fetch`), handle loading and
  error states, and implement the actual feature/user-story behavior for this screen — real
  form handling, real list rendering from the API response, real interactions.
- Style exclusively with Tailwind CSS utility classes in the template. No inline styles,
  no other CSS frameworks, no separate CSS file.
- Structure as a proper .vue Single File Component: `<template>`, `<script setup>`, no
  `<style>` block needed since Tailwind handles styling.
- No placeholders or TODOs — this screen must be fully implemented, not static mockup content.

Return ONLY the raw .vue Single File Component content. No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(prompt, "javascript", GROQ_FILE_MAX_TOKENS)
    return GeneratedFile(
        path=f"frontend/src/screens/{component_name}.vue",
        language="javascript",
        content=content,
        description=f"Screen implementing {screen_name}",
    ), issue


def _screen_import_name(file: GeneratedFile) -> str:
    return file.path.split("/")[-1].rsplit(".", 1)[0]


def _build_app_vue(names: list[str]) -> str:
    imports = "\n".join(f"import {n} from './screens/{n}.vue';" for n in names)
    entries = ",\n".join(f"  {{ name: '{n}', component: {n} }}" for n in names)
    script = (
        "<script setup>\nimport { ref } from 'vue';\n"
        + imports
        + "\n\nconst screens = [\n"
        + entries
        + "\n];\nconst active = ref(0);\n</script>"
    )
    template = (
        "\n\n<template>\n"
        '  <div class="min-h-screen flex flex-col">\n'
        '    <nav v-if="screens.length > 1" class="flex gap-2 p-3 border-b border-gray-200">\n'
        "      <button\n"
        '        v-for="(s, i) in screens"\n'
        '        :key="s.name"\n'
        '        @click="active = i"\n'
        "        :class=\"['px-3 py-1.5 rounded text-sm font-medium', active === i ? 'bg-black text-white' : 'bg-gray-100 text-gray-700']\"\n"
        "      >\n"
        "        {{ s.name }}\n"
        "      </button>\n"
        "    </nav>\n"
        '    <main class="flex-1">\n'
        '      <component :is="screens[active].component" />\n'
        "    </main>\n"
        "  </div>\n"
        "</template>\n"
    )
    return script + template


_MAIN_JS = """import { createApp } from 'vue';
import App from './App.vue';
import './index.css';

createApp(App).mount('#app');
"""

_INDEX_CSS = "@tailwind base;\n@tailwind components;\n@tailwind utilities;\n"

_TAILWIND_CONFIG = """/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./index.html", "./src/**/*.{vue,js}"],
  theme: { extend: {} },
  plugins: [],
};
"""

_POSTCSS_CONFIG = """module.exports = {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
"""

_VITE_CONFIG = """import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

export default defineConfig({
  plugins: [vue()],
});
"""


def _index_html(project_name: str) -> str:
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <title>{project_name}</title>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.js"></script>
  </body>
</html>
"""


def manifest_files(ctx: WiringCtx) -> list[GeneratedFile]:
    from app.core.naming import slugify_app_name

    content = build_package_json(
        name=slugify_app_name(ctx.project_name),
        scripts={"dev": "vite", "build": "vite build", "preview": "vite preview"},
        dependencies={"vue": "^3.4.15"},
        dev_dependencies={
            "vite": "^5.1.0",
            "@vitejs/plugin-vue": "^5.0.3",
            "tailwindcss": "^3.4.1",
            "postcss": "^8.4.35",
            "autoprefixer": "^10.4.17",
        },
    )
    return [GeneratedFile(path="frontend/package.json", language="json", content=content, description="Frontend dependency manifest")]


def entry_point_files(ctx: WiringCtx) -> list[GeneratedFile]:
    names = [_screen_import_name(f) for f in ctx.screen_files] or ["Home"]
    return [
        GeneratedFile(path="frontend/index.html", language="html", content=_index_html(ctx.project_name), description="Vite HTML entry point"),
        GeneratedFile(path="frontend/vite.config.js", language="javascript", content=_VITE_CONFIG, description="Vite build config"),
        GeneratedFile(path="frontend/src/main.js", language="javascript", content=_MAIN_JS, description="Vue entry point"),
        GeneratedFile(path="frontend/src/App.vue", language="javascript", content=_build_app_vue(names), description="Renders every generated screen"),
        GeneratedFile(path="frontend/src/index.css", language="css", content=_INDEX_CSS, description="Tailwind directives"),
        GeneratedFile(path="frontend/tailwind.config.js", language="javascript", content=_TAILWIND_CONFIG, description="Tailwind config"),
        GeneratedFile(path="frontend/postcss.config.js", language="javascript", content=_POSTCSS_CONFIG, description="PostCSS config"),
    ]


def setup_commands(project_name: str) -> list[str]:
    return ["cd frontend", "npm install", "npm run dev"]


ADAPTER = FrontendAdapter(
    key="vue",
    label="Vue",
    supported_languages=("javascript",),
    generate_screen=generate_screen,
    manifest_files=manifest_files,
    entry_point_files=entry_point_files,
    setup_commands=setup_commands,
)
