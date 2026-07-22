# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Svelte Frontend Adapter
#  ai/codegen/frontend/svelte.py — Targets classic Svelte 4 component
#  syntax (not Svelte 5 runes), matching the most broadly-known/stable
#  form of the framework for reliable single-shot generation.
# ═══════════════════════════════════════════════════════════════

from app.ai.codegen.manifests.package_json import build_package_json
from app.ai.codegen.types import FileResult, FrontendAdapter, ScreenCtx, WiringCtx
from app.ai.codegen_shared import (
    GROQ_FILE_MAX_TOKENS,
    NATIVE_CAPABILITY_DESCRIPTIONS,
    GeneratedFile,
    _pascal,
    generate_text_validated,
)


async def generate_screen(ctx: ScreenCtx) -> FileResult:
    screen_name = ctx.screen.get("name", "Screen")
    component_name = _pascal(screen_name)
    endpoints_text = "\n".join(
        f"- {e.get('method')} {e.get('path')}: {e.get('purpose')}" for e in ctx.endpoints
    )

    capabilities_text = "\n".join(
        f"- {NATIVE_CAPABILITY_DESCRIPTIONS[c]}" for c in ctx.native_capabilities if c in NATIVE_CAPABILITY_DESCRIPTIONS
    )
    native_section = (
        f"\nNative device features available to this app (import and use where relevant to "
        f"this screen's user stories — do not fake this functionality with browser-only "
        f"substitutes):\n{capabilities_text}\n"
        if capabilities_text
        else ""
    )

    prompt = f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Write ONE complete, real Svelte component (classic Svelte 4 syntax, NOT Svelte 5 runes) for the "{screen_name}" screen of this app.

App: {ctx.project_name}
{ctx.requirements_text}
Screen purpose: {ctx.screen.get('purpose', '')}

API endpoints this screen can call:
{endpoints_text}
{native_section}
Requirements:
- Use a `<script>` block with classic reactive `let` variables — no runes ($state, $derived, etc).
- Fetch real data from the relevant API endpoints above (use `fetch`), handle loading and
  error states, and implement the actual feature/user-story behavior for this screen — real
  form handling, real list rendering from the API response, real interactions.
- Style exclusively with Tailwind CSS utility classes in the markup. No inline styles,
  no other CSS frameworks, no `<style>` block.
- No placeholders or TODOs — this screen must be fully implemented, not static mockup content.

Return ONLY the raw .svelte file content. No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(prompt, "javascript", GROQ_FILE_MAX_TOKENS)
    return GeneratedFile(
        path=f"frontend/src/screens/{component_name}.svelte",
        language="javascript",
        content=content,
        description=f"Screen implementing {screen_name}",
    ), issue


def _screen_import_name(file: GeneratedFile) -> str:
    return file.path.split("/")[-1].rsplit(".", 1)[0]


def _build_app_svelte(names: list[str]) -> str:
    imports = "\n".join(f"import {n} from './screens/{n}.svelte';" for n in names)
    entries = ",\n".join(f"    {{ name: '{n}', component: {n} }}" for n in names)
    script = "<script>\n" + imports + "\n\n  const screens = [\n" + entries + "\n  ];\n  let active = 0;\n</script>"
    template = (
        "\n\n<div class=\"min-h-screen flex flex-col\">\n"
        "  {#if screens.length > 1}\n"
        '    <nav class="flex gap-2 p-3 border-b border-gray-200">\n'
        "      {#each screens as s, i}\n"
        "        <button\n"
        "          on:click={() => (active = i)}\n"
        "          class=\"px-3 py-1.5 rounded text-sm font-medium {active === i ? 'bg-black text-white' : 'bg-gray-100 text-gray-700'}\"\n"
        "        >\n"
        "          {s.name}\n"
        "        </button>\n"
        "      {/each}\n"
        "    </nav>\n"
        "  {/if}\n"
        '  <main class="flex-1">\n'
        "    <svelte:component this={screens[active].component} />\n"
        "  </main>\n"
        "</div>\n"
    )
    return script + template


_MAIN_JS = """import App from './App.svelte';

const app = new App({
  target: document.getElementById('app'),
});

export default app;
"""

_INDEX_CSS = "@tailwind base;\n@tailwind components;\n@tailwind utilities;\n"

_TAILWIND_CONFIG = """/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./index.html", "./src/**/*.{svelte,js}"],
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
import { svelte } from '@sveltejs/vite-plugin-svelte';

export default defineConfig({
  plugins: [svelte()],
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
        dependencies={},
        dev_dependencies={
            "svelte": "^4.2.9",
            "vite": "^5.1.0",
            "@sveltejs/vite-plugin-svelte": "^3.0.2",
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
        GeneratedFile(path="frontend/src/main.js", language="javascript", content=_MAIN_JS, description="Svelte entry point"),
        GeneratedFile(path="frontend/src/App.svelte", language="javascript", content=_build_app_svelte(names), description="Renders every generated screen"),
        GeneratedFile(path="frontend/src/index.css", language="css", content=_INDEX_CSS, description="Tailwind directives"),
        GeneratedFile(path="frontend/tailwind.config.js", language="javascript", content=_TAILWIND_CONFIG, description="Tailwind config"),
        GeneratedFile(path="frontend/postcss.config.js", language="javascript", content=_POSTCSS_CONFIG, description="PostCSS config"),
    ]


def setup_commands(project_name: str) -> list[str]:
    return ["cd frontend", "npm install", "npm run dev"]


ADAPTER = FrontendAdapter(
    key="svelte",
    label="Svelte",
    supported_languages=("javascript",),
    generate_screen=generate_screen,
    manifest_files=manifest_files,
    entry_point_files=entry_point_files,
    setup_commands=setup_commands,
)
