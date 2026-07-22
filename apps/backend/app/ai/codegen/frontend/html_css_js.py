# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Plain HTML/CSS/JS Frontend Adapter
#  ai/codegen/frontend/html_css_js.py — No framework at all: each
#  screen is a vanilla ES module exporting render(container). Still
#  wrapped in a minimal Vite project (rather than truly static files)
#  so it goes through the same npm-install/dev-server/build path as
#  every other web frontend — Vite needs zero plugins for plain JS.
# ═══════════════════════════════════════════════════════════════

import re

from app.ai.codegen.manifests.package_json import build_package_json
from app.ai.codegen.types import FileResult, FrontendAdapter, ScreenCtx, WiringCtx
from app.ai.codegen_shared import (
    GROQ_FILE_MAX_TOKENS,
    NATIVE_CAPABILITY_DESCRIPTIONS,
    GeneratedFile,
    _slug,
    generate_text_validated,
)


async def generate_screen(ctx: ScreenCtx) -> FileResult:
    screen_name = ctx.screen.get("name", "Screen")
    slug = _slug(screen_name)
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

    prompt = f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Write ONE complete, real vanilla JavaScript ES module implementing the "{screen_name}" screen of this app — no framework, plain DOM APIs.

App: {ctx.project_name}
{ctx.requirements_text}
Screen purpose: {ctx.screen.get('purpose', '')}

API endpoints this screen can call:
{endpoints_text}
{native_section}
Requirements:
- Do NOT use React, Vue, Svelte, or any other framework API — no `useState`, `useEffect`, JSX,
  or imports from 'react'/'vue'/etc. This is PLAIN vanilla JavaScript: only standard DOM APIs
  (`document`, `fetch`, `addEventListener`, element properties) and ordinary local variables/
  functions for state, since there is no framework here to provide reactivity.
- Export ONE function: `export function render(container) {{ ... }}` that takes a DOM element
  and renders this screen's real UI into it (e.g. via `container.innerHTML = \\`...\\`;`), then
  re-renders by re-running the same rendering logic (e.g. a local `function draw() {{ ... }}`
  you call again) whenever the underlying data changes — there is no automatic reactivity, so
  the module itself must re-invoke its own rendering code after state changes.
- Fetch real data from the relevant API endpoints above (use `fetch`), handle loading and error
  states, and implement the actual feature/user-story behavior for this screen — real form
  handling, real list rendering from the API response, real interactions.
- Attach event listeners with `addEventListener` AFTER inserting the HTML (e.g.
  `container.querySelector(...).addEventListener('click', ...)`) — this is an ES module, so
  inline `onclick="..."` attributes in the HTML string can NOT reach module-scoped functions
  and must not be used.
- Style exclusively with Tailwind CSS utility classes in the HTML. No inline `style=` attributes,
  no other CSS frameworks, no separate CSS file for this screen.
- No placeholders or TODOs — this screen must be fully implemented, not static mockup content.

Return ONLY the raw JavaScript module content. No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(prompt, "javascript", GROQ_FILE_MAX_TOKENS)
    if issue is None and not _exports_render(content):
        # Cheap structural check the generic brace/TODO heuristic can't
        # catch: this adapter's wiring (main.js) does
        # `import { render as ... } from './screens/{slug}.js'` — a file
        # missing that exact export compiles fine but fails at runtime
        # with "render is not a function". Surface it as a validation
        # warning rather than silently shipping a broken screen.
        issue = "missing 'export function render(container)' — main.js won't be able to import this screen"
    return GeneratedFile(
        path=f"frontend/src/screens/{slug}.js",
        language="javascript",
        content=content,
        description=f"Screen implementing {screen_name}",
    ), issue


def _exports_render(content: str) -> bool:
    return bool(re.search(r"export\s+(function|const|let)\s+render\b|export\s*\{[^}]*\brender\b", content))


def _screen_slug_from_path(file: GeneratedFile) -> str:
    return file.path.split("/")[-1].removesuffix(".js")


def _title_case(slug: str) -> str:
    return " ".join(word.capitalize() for word in slug.split("_"))


def _build_main_js(slugs: list[str]) -> str:
    imports = "\n".join(f"import {{ render as render_{s} }} from './screens/{s}.js';" for s in slugs)
    screens_array = ",\n".join(f"  {{ name: '{_title_case(s)}', render: render_{s} }}" for s in slugs)
    return f"""{imports}

const screens = [
{screens_array}
];

const app = document.getElementById('app');

function renderNav(active) {{
  const nav = document.getElementById('nav');
  if (!nav) return;
  nav.innerHTML = '';
  if (screens.length <= 1) return;
  screens.forEach((s, i) => {{
    const btn = document.createElement('button');
    btn.textContent = s.name;
    btn.className =
      'px-3 py-1.5 rounded text-sm font-medium ' +
      (i === active ? 'bg-black text-white' : 'bg-gray-100 text-gray-700');
    btn.addEventListener('click', () => showScreen(i));
    nav.appendChild(btn);
  }});
}}

function showScreen(index) {{
  renderNav(index);
  const container = document.getElementById('screen');
  container.innerHTML = '';
  screens[index].render(container);
}}

document.body.innerHTML = `
  <div class="min-h-screen flex flex-col">
    <nav id="nav" class="flex gap-2 p-3 border-b border-gray-200"></nav>
    <main id="screen" class="flex-1"></main>
  </div>
`;

showScreen(0);
"""


_INDEX_CSS = "@tailwind base;\n@tailwind components;\n@tailwind utilities;\n"

_TAILWIND_CONFIG = """/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./index.html", "./src/**/*.js"],
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


def _index_html(project_name: str) -> str:
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <title>{project_name}</title>
    <link rel="stylesheet" href="/src/index.css" />
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
            "vite": "^5.1.0",
            "tailwindcss": "^3.4.1",
            "postcss": "^8.4.35",
            "autoprefixer": "^10.4.17",
        },
    )
    return [GeneratedFile(path="frontend/package.json", language="json", content=content, description="Frontend dependency manifest")]


def entry_point_files(ctx: WiringCtx) -> list[GeneratedFile]:
    slugs = [_screen_slug_from_path(f) for f in ctx.screen_files] or ["home"]
    return [
        GeneratedFile(path="frontend/index.html", language="html", content=_index_html(ctx.project_name), description="Vite HTML entry point"),
        GeneratedFile(path="frontend/src/main.js", language="javascript", content=_build_main_js(slugs), description="Renders every generated screen"),
        GeneratedFile(path="frontend/src/index.css", language="css", content=_INDEX_CSS, description="Tailwind directives"),
        GeneratedFile(path="frontend/tailwind.config.js", language="javascript", content=_TAILWIND_CONFIG, description="Tailwind config"),
        GeneratedFile(path="frontend/postcss.config.js", language="javascript", content=_POSTCSS_CONFIG, description="PostCSS config"),
    ]


def setup_commands(project_name: str) -> list[str]:
    return ["cd frontend", "npm install", "npm run dev"]


ADAPTER = FrontendAdapter(
    key="html_css_js",
    label="Plain HTML/CSS/JS",
    supported_languages=("javascript",),
    generate_screen=generate_screen,
    manifest_files=manifest_files,
    entry_point_files=entry_point_files,
    setup_commands=setup_commands,
)
