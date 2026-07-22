# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Angular Frontend Adapter
#  ai/codegen/frontend/angular.py — Targets Angular 18 standalone
#  components (no NgModule) with an inline template+styles per
#  component, so one AI call still produces exactly one file, matching
#  every other adapter's "one screen = one file" pattern. The
#  angular.json/tsconfig manifests below are copied from a REAL
#  `npx @angular/cli new` scaffold (not guessed) — Angular fundamentally
#  needs its own compiler/builder (@angular-devkit/build-angular), not a
#  generic bundler config like Vite, so getting this exactly right
#  matters more here than for any other web frontend.
# ═══════════════════════════════════════════════════════════════

import re

from app.ai.codegen.manifests.package_json import build_package_json
from app.ai.codegen.types import FileResult, FrontendAdapter, ScreenCtx, WiringCtx
from app.ai.codegen_shared import (
    GROQ_FILE_MAX_TOKENS,
    NATIVE_CAPABILITY_DESCRIPTIONS,
    GeneratedFile,
    _pascal,
    generate_text_validated,
)


def _kebab(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", name or "screen").strip("-").lower()
    return cleaned or "screen"


async def generate_screen(ctx: ScreenCtx) -> FileResult:
    screen_name = ctx.screen.get("name", "Screen")
    kebab = _kebab(screen_name)
    class_name = f"{_pascal(screen_name)}Component"
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

    prompt = f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Write ONE complete, real Angular STANDALONE component (Angular 17+ style — `standalone: true`, inline `template` and `styles`, NO separate .html/.css files, NO NgModule) for the "{screen_name}" screen of this app.

App: {ctx.project_name}
{ctx.requirements_text}
Screen purpose: {ctx.screen.get('purpose', '')}

API endpoints this screen can call:
{endpoints_text}
{native_section}
Requirements:
- Class name: {class_name} (exported), selector: 'app-{kebab}'.
- @Component({{ selector: 'app-{kebab}', standalone: true, imports: [CommonModule] (add FormsModule too if
  this screen has a form using ngModel), template: `...`, styles: [] }}).
- Implement OnInit and fetch real data using the native `fetch` API inside ngOnInit(), tracking
  loading/error state as class properties. Implement the actual feature/user-story behavior for
  this screen — real form handling, real list rendering, real interactions. Use *ngIf/*ngFor in
  the template for conditional/list rendering (classic Angular control flow, not the newer @if/@for
  syntax, for broader version compatibility).
- Style exclusively with Tailwind CSS utility classes in the inline template. No separate CSS file.
- No placeholders or TODOs — this screen must be fully implemented, not static mockup content.

Return ONLY the raw TypeScript file content (imports + @Component decorator + class). No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(prompt, "typescript", GROQ_FILE_MAX_TOKENS)
    return GeneratedFile(
        path=f"frontend/src/app/screens/{kebab}.component.ts",
        language="typescript",
        content=content,
        description=f"Screen implementing {screen_name}",
    ), issue


def _screen_kebab_from_path(file: GeneratedFile) -> str:
    return file.path.split("/")[-1].removesuffix(".component.ts")


def _build_app_component_ts(kebabs: list[str]) -> str:
    imports = "\n".join(f"import {{ {_pascal(k)}Component }} from './screens/{k}.component';" for k in kebabs)
    import_names = ", ".join(f"{_pascal(k)}Component" for k in kebabs)
    tags = "\n".join(f'        <app-{k} *ngIf="active === {i}"></app-{k}>' for i, k in enumerate(kebabs))
    screens_array = ", ".join(f"{{ name: '{_pascal(k)}' }}" for k in kebabs)

    return (
        "import { Component } from '@angular/core';\n"
        "import { CommonModule } from '@angular/common';\n"
        + imports + "\n\n"
        "@Component({\n"
        "  selector: 'app-root',\n"
        "  standalone: true,\n"
        f"  imports: [CommonModule, {import_names}],\n"
        "  template: `\n"
        '    <div class="min-h-screen flex flex-col">\n'
        '      <nav *ngIf="screens.length > 1" class="flex gap-2 p-3 border-b border-gray-200">\n'
        "        <button\n"
        '          *ngFor="let s of screens; let i = index"\n'
        '          (click)="active = i"\n'
        "          [class]=\"'px-3 py-1.5 rounded text-sm font-medium ' + (active === i ? 'bg-black text-white' : 'bg-gray-100 text-gray-700')\"\n"
        "        >\n"
        "          {{ s.name }}\n"
        "        </button>\n"
        "      </nav>\n"
        '      <main class="flex-1">\n'
        + tags + "\n"
        "      </main>\n"
        "    </div>\n"
        "  `,\n"
        "})\n"
        "export class AppComponent {\n"
        f"  screens = [{screens_array}];\n"
        "  active = 0;\n"
        "}\n"
    )


_MAIN_TS = """import { bootstrapApplication } from '@angular/platform-browser';
import { appConfig } from './app/app.config';
import { AppComponent } from './app/app.component';

bootstrapApplication(AppComponent, appConfig).catch((err) => console.error(err));
"""

_APP_CONFIG_TS = """import { ApplicationConfig, provideZoneChangeDetection } from '@angular/core';

export const appConfig: ApplicationConfig = {
  providers: [provideZoneChangeDetection({ eventCoalescing: true })],
};
"""

_STYLES_CSS = "@tailwind base;\n@tailwind components;\n@tailwind utilities;\n"

_TAILWIND_CONFIG = """/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{html,ts}"],
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

# Verified against a REAL `npx @angular/cli@18 new` scaffold, not guessed —
# Angular's own compiler options (experimentalDecorators, etc.) are strict
# enough that hand-guessing this file risks a build that silently can't
# compile @Component decorators at all.
_TSCONFIG_JSON = """{
  "compileOnSave": false,
  "compilerOptions": {
    "outDir": "./dist/out-tsc",
    "strict": true,
    "noImplicitOverride": true,
    "noPropertyAccessFromIndexSignature": true,
    "noImplicitReturns": true,
    "noFallthroughCasesInSwitch": true,
    "skipLibCheck": true,
    "isolatedModules": true,
    "esModuleInterop": true,
    "sourceMap": true,
    "declaration": false,
    "experimentalDecorators": true,
    "moduleResolution": "bundler",
    "importHelpers": true,
    "target": "ES2022",
    "module": "ES2022",
    "lib": ["ES2022", "dom"]
  },
  "angularCompilerOptions": {
    "enableI18nLegacyMessageIdFormat": false,
    "strictInjectionParameters": true,
    "strictInputAccessModifiers": true,
    "strictTemplates": true
  }
}
"""

_TSCONFIG_APP_JSON = """{
  "extends": "./tsconfig.json",
  "compilerOptions": {
    "outDir": "./out-tsc/app",
    "types": []
  },
  "files": ["src/main.ts"],
  "include": ["src/**/*.d.ts"]
}
"""


def _angular_json(project_name: str) -> str:
    return f"""{{
  "$schema": "./node_modules/@angular/cli/lib/config/schema.json",
  "version": 1,
  "cli": {{ "packageManager": "npm" }},
  "newProjectRoot": "projects",
  "projects": {{
    "{project_name}": {{
      "projectType": "application",
      "schematics": {{}},
      "root": "",
      "sourceRoot": "src",
      "prefix": "app",
      "architect": {{
        "build": {{
          "builder": "@angular-devkit/build-angular:application",
          "options": {{
            "outputPath": "dist/{project_name}",
            "index": "src/index.html",
            "browser": "src/main.ts",
            "polyfills": ["zone.js"],
            "tsConfig": "tsconfig.app.json",
            "assets": [],
            "styles": ["src/styles.css"],
            "scripts": []
          }},
          "configurations": {{
            "production": {{ "outputHashing": "all" }},
            "development": {{ "optimization": false, "extractLicenses": false, "sourceMap": true }}
          }},
          "defaultConfiguration": "development"
        }},
        "serve": {{
          "builder": "@angular-devkit/build-angular:dev-server",
          "configurations": {{
            "production": {{ "buildTarget": "{project_name}:build:production" }},
            "development": {{ "buildTarget": "{project_name}:build:development" }}
          }},
          "defaultConfiguration": "development"
        }}
      }}
    }}
  }}
}}
"""


def _index_html(project_name: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{project_name}</title>
  <base href="/">
  <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body>
  <app-root></app-root>
</body>
</html>
"""


def manifest_files(ctx: WiringCtx) -> list[GeneratedFile]:
    from app.core.naming import slugify_app_name

    slug = slugify_app_name(ctx.project_name)
    package_json = build_package_json(
        name=slug,
        scripts={"ng": "ng", "start": "ng serve", "build": "ng build"},
        dependencies={
            "@angular/animations": "^18.2.0",
            "@angular/common": "^18.2.0",
            "@angular/compiler": "^18.2.0",
            "@angular/core": "^18.2.0",
            "@angular/forms": "^18.2.0",
            "@angular/platform-browser": "^18.2.0",
            "@angular/platform-browser-dynamic": "^18.2.0",
            "rxjs": "~7.8.0",
            "tslib": "^2.3.0",
            "zone.js": "~0.14.10",
        },
        dev_dependencies={
            "@angular-devkit/build-angular": "^18.2.21",
            "@angular/cli": "^18.2.21",
            "@angular/compiler-cli": "^18.2.0",
            "typescript": "~5.5.2",
            "tailwindcss": "^3.4.1",
            "postcss": "^8.4.35",
            "autoprefixer": "^10.4.17",
        },
    )
    return [
        GeneratedFile(path="frontend/package.json", language="json", content=package_json, description="Frontend dependency manifest"),
        GeneratedFile(path="frontend/angular.json", language="json", content=_angular_json(slug), description="Angular CLI project config"),
        GeneratedFile(path="frontend/tsconfig.json", language="json", content=_TSCONFIG_JSON, description="Base TypeScript config"),
        GeneratedFile(path="frontend/tsconfig.app.json", language="json", content=_TSCONFIG_APP_JSON, description="App TypeScript config"),
        GeneratedFile(path="frontend/tailwind.config.js", language="javascript", content=_TAILWIND_CONFIG, description="Tailwind config"),
        GeneratedFile(path="frontend/postcss.config.js", language="javascript", content=_POSTCSS_CONFIG, description="PostCSS config"),
    ]


def entry_point_files(ctx: WiringCtx) -> list[GeneratedFile]:
    kebabs = [_screen_kebab_from_path(f) for f in ctx.screen_files] or ["home"]
    return [
        GeneratedFile(path="frontend/src/index.html", language="html", content=_index_html(ctx.project_name), description="Angular HTML entry point"),
        GeneratedFile(path="frontend/src/main.ts", language="typescript", content=_MAIN_TS, description="Angular bootstrap entry point"),
        GeneratedFile(path="frontend/src/app/app.config.ts", language="typescript", content=_APP_CONFIG_TS, description="Angular application config"),
        GeneratedFile(path="frontend/src/app/app.component.ts", language="typescript", content=_build_app_component_ts(kebabs), description="Renders every generated screen"),
        GeneratedFile(path="frontend/src/styles.css", language="css", content=_STYLES_CSS, description="Tailwind directives"),
    ]


def setup_commands(project_name: str) -> list[str]:
    return ["cd frontend", "npm install", "npm start"]


ADAPTER = FrontendAdapter(
    key="angular",
    label="Angular",
    supported_languages=("typescript",),
    generate_screen=generate_screen,
    manifest_files=manifest_files,
    entry_point_files=entry_point_files,
    setup_commands=setup_commands,
)
