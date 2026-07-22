# ═══════════════════════════════════════════════════════════════
#  VengaiCode — React Frontend Adapter
#  ai/codegen/frontend/react.py — Screen generation moved verbatim from
#  the old codegen.py generate_screen_file()'s default branch. No
#  behavior change from the pre-adapter version.
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

    prompt = f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Write ONE complete, real React functional component for the "{screen_name}" screen of this app.

App: {ctx.project_name}
{ctx.requirements_text}
Screen purpose: {ctx.screen.get('purpose', '')}

API endpoints this screen can call:
{endpoints_text}
{native_section}
Requirements:
- Component name: {component_name} (default export).
- Fetch real data from the relevant API endpoints above (use `fetch`), handle loading and
  error states, and implement the actual feature/user-story behavior for this screen — real
  form handling, real list rendering from the API response, real interactions.
- Style exclusively with Tailwind CSS utility classes via `className`. No inline styles,
  no other CSS frameworks, no separate CSS file.
- No placeholders or TODOs — this screen must be fully implemented, not static mockup content.

Return ONLY the raw JSX/JS code for this one file. No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(prompt, "javascript", GROQ_FILE_MAX_TOKENS)
    return GeneratedFile(
        path=f"frontend/src/screens/{component_name}.jsx",
        language="javascript",
        content=content,
        description=f"Screen implementing {screen_name}",
    ), issue


def _screen_import_name(file: GeneratedFile) -> str:
    return file.path.split("/")[-1].rsplit(".", 1)[0]


def _build_app_jsx(names: list[str]) -> str:
    imports = "\n".join(f"import {n} from './screens/{n}';" for n in names)
    entries = ",\n".join(f"  {{ name: '{n}', Component: {n} }}" for n in names)
    return f"""import {{ useState }} from 'react';
{imports}

const SCREENS = [
{entries}
];

export default function App() {{
  const [active, setActive] = useState(0);
  const Active = SCREENS[active].Component;
  return (
    <div className="min-h-screen flex flex-col">
      {{SCREENS.length > 1 && (
        <nav className="flex gap-2 p-3 border-b border-gray-200">
          {{SCREENS.map((s, i) => (
            <button
              key={{s.name}}
              onClick={{() => setActive(i)}}
              className={{`px-3 py-1.5 rounded text-sm font-medium ${{active === i ? 'bg-black text-white' : 'bg-gray-100 text-gray-700'}}`}}
            >
              {{s.name}}
            </button>
          ))}}
        </nav>
      )}}
      <main className="flex-1">
        <Active />
      </main>
    </div>
  );
}}
"""


_MAIN_JSX = """import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
"""

_INDEX_CSS = "@tailwind base;\n@tailwind components;\n@tailwind utilities;\n"

_TAILWIND_CONFIG = """/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./index.html", "./src/**/*.{js,jsx,ts,tsx}"],
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
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
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
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
"""


def manifest_files(ctx: WiringCtx) -> list[GeneratedFile]:
    from app.core.naming import slugify_app_name

    content = build_package_json(
        name=slugify_app_name(ctx.project_name),
        scripts={"dev": "vite", "build": "vite build", "preview": "vite preview"},
        dependencies={"react": "^18.2.0", "react-dom": "^18.2.0"},
        dev_dependencies={
            "vite": "^5.1.0",
            "@vitejs/plugin-react": "^4.2.1",
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
        GeneratedFile(path="frontend/src/main.jsx", language="javascript", content=_MAIN_JSX, description="React entry point"),
        GeneratedFile(path="frontend/src/App.jsx", language="javascript", content=_build_app_jsx(names), description="Renders every generated screen"),
        GeneratedFile(path="frontend/src/index.css", language="css", content=_INDEX_CSS, description="Tailwind directives"),
        GeneratedFile(path="frontend/tailwind.config.js", language="javascript", content=_TAILWIND_CONFIG, description="Tailwind config"),
        GeneratedFile(path="frontend/postcss.config.js", language="javascript", content=_POSTCSS_CONFIG, description="PostCSS config"),
    ]


def setup_commands(project_name: str) -> list[str]:
    return ["cd frontend", "npm install", "npm run dev"]


ADAPTER = FrontendAdapter(
    key="react",
    label="React",
    supported_languages=("javascript",),
    generate_screen=generate_screen,
    manifest_files=manifest_files,
    entry_point_files=entry_point_files,
    setup_commands=setup_commands,
)
