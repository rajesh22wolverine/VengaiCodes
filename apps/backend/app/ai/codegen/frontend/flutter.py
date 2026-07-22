# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Flutter Frontend Adapter
#  ai/codegen/frontend/flutter.py — First "native" (non-web) frontend.
#  Produces a real Dart/Flutter source project (pubspec.yaml + lib/),
#  not a wrapped web bundle — Flutter has its own build toolchain
#  (`flutter build apk`/`windows`/`ios`), so this never flows through
#  the Tauri/Capacitor packaging pipeline (see the category guard added
#  to packaging.py/android_packaging.py/linux_packaging.py — those only
#  handle "web" category frontends; FRONTEND_FRAMEWORKS["flutter"] is
#  "mobile", so those endpoints now 400 instead of silently mis-wrapping
#  a Dart project into a Vite build step).
# ═══════════════════════════════════════════════════════════════

import re

from app.ai.codegen.types import FileResult, FrontendAdapter, ScreenCtx, WiringCtx
from app.ai.codegen_shared import (
    GROQ_FILE_MAX_TOKENS,
    NATIVE_CAPABILITY_DESCRIPTIONS,
    GeneratedFile,
    _pascal,
    generate_text_validated,
)


def _snake(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", name or "screen").strip("_").lower()
    if cleaned and cleaned[0].isdigit():
        cleaned = f"s_{cleaned}"
    return cleaned or "screen"


async def generate_screen(ctx: ScreenCtx) -> FileResult:
    screen_name = ctx.screen.get("name", "Screen")
    class_name = f"{_pascal(screen_name)}Screen"
    endpoints_text = "\n".join(
        f"- {e.get('method')} {e.get('path')}: {e.get('purpose')}" for e in ctx.endpoints
    )

    capabilities_text = "\n".join(
        f"- {NATIVE_CAPABILITY_DESCRIPTIONS[c]}" for c in ctx.native_capabilities if c in NATIVE_CAPABILITY_DESCRIPTIONS
    )
    native_section = (
        f"\nNative device features available to this app (use the real Flutter/Dart package "
        f"for each, not a web substitute):\n{capabilities_text}\n"
        if capabilities_text
        else ""
    )

    prompt = f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Write ONE complete, real Flutter widget file implementing the "{screen_name}" screen of this app.

App: {ctx.project_name}
{ctx.requirements_text}
Screen purpose: {ctx.screen.get('purpose', '')}

API endpoints this screen can call:
{endpoints_text}
{native_section}
Requirements:
- Class name: {class_name}, a StatefulWidget (use StatelessWidget only if this screen truly has
  no dynamic state) with a `const {class_name}({{super.key}})` constructor.
- Fetch real data using the `http` package (`import 'package:http/http.dart' as http;`). The
  response body is a JSON STRING — parse it with `jsonDecode` from `dart:convert`
  (`import 'dart:convert';`), never cast `response.body` directly to a List/Map. Handle
  loading/error states, and implement the actual feature/user-story behavior for this screen —
  real form handling, real list rendering, real interactions via `setState`.
- Use Flutter's Material widgets (Scaffold, ListView, TextField, ElevatedButton, etc.) for a real,
  usable UI — no placeholder text or TODO comments, this must be fully implemented.
- Return ONLY this one widget — do not define MaterialApp or main() here.

Return ONLY the raw Dart code for this one file. No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(prompt, "dart", GROQ_FILE_MAX_TOKENS)
    return GeneratedFile(
        path=f"frontend/lib/screens/{_snake(screen_name)}_screen.dart",
        language="dart",
        content=content,
        description=f"Screen implementing {screen_name}",
    ), issue


def _screen_meta_from_path(file: GeneratedFile) -> tuple[str, str]:
    """(import path relative to lib/, class name) for a screen file."""
    stem = file.path.split("/")[-1].removesuffix(".dart")
    class_name = _pascal(stem.removesuffix("_screen")) + "Screen"
    return stem, class_name


def _build_main_dart(project_name: str, screens: list[tuple[str, str]]) -> str:
    imports = "\n".join(f"import 'screens/{stem}.dart';" for stem, _ in screens)
    names = ", ".join(f"'{_pascal(stem.removesuffix('_screen'))}'" for stem, _ in screens)
    widgets = ", ".join(cls for _, cls in screens)

    return f"""import 'package:flutter/material.dart';
{imports}

void main() {{
  runApp(const RootApp());
}}

class RootApp extends StatelessWidget {{
  const RootApp({{super.key}});

  @override
  Widget build(BuildContext context) {{
    return MaterialApp(
      title: '{project_name}',
      theme: ThemeData(useMaterial3: true, colorSchemeSeed: Colors.blue),
      home: const RootNav(),
    );
  }}
}}

class RootNav extends StatefulWidget {{
  const RootNav({{super.key}});

  @override
  State<RootNav> createState() => _RootNavState();
}}

class _RootNavState extends State<RootNav> {{
  int _active = 0;

  static final List<String> _names = [{names}];
  static final List<Widget> _screens = [{widgets}];

  @override
  Widget build(BuildContext context) {{
    return Scaffold(
      appBar: _names.length > 1
          ? PreferredSize(
              preferredSize: const Size.fromHeight(56),
              child: SafeArea(
                child: Row(
                  children: List.generate(_names.length, (i) {{
                    final active = i == _active;
                    return Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 8),
                      child: ElevatedButton(
                        style: ElevatedButton.styleFrom(
                          backgroundColor: active ? Colors.black : Colors.grey[200],
                          foregroundColor: active ? Colors.white : Colors.black87,
                        ),
                        onPressed: () => setState(() => _active = i),
                        child: Text(_names[i]),
                      ),
                    );
                  }}),
                ),
              ),
            )
          : null,
      body: _screens[_active],
    );
  }}
}}
"""


def _pubspec_yaml(package_name: str) -> str:
    return f"""name: {package_name}
description: Generated by VengaiCode.
publish_to: 'none'
version: 1.0.0+1

environment:
  sdk: '>=3.0.0 <4.0.0'

dependencies:
  flutter:
    sdk: flutter
  http: ^1.2.0

dev_dependencies:
  flutter_test:
    sdk: flutter
  flutter_lints: ^3.0.0

flutter:
  uses-material-design: true
"""


_ANALYSIS_OPTIONS = """include: package:flutter_lints/flutter.yaml
"""


def manifest_files(ctx: WiringCtx) -> list[GeneratedFile]:
    package_name = _snake(ctx.project_name) or "vengaicode_app"
    return [
        GeneratedFile(path="frontend/pubspec.yaml", language="yaml", content=_pubspec_yaml(package_name), description="Flutter package manifest"),
        GeneratedFile(path="frontend/analysis_options.yaml", language="yaml", content=_ANALYSIS_OPTIONS, description="Dart analyzer config"),
    ]


def entry_point_files(ctx: WiringCtx) -> list[GeneratedFile]:
    screens = [_screen_meta_from_path(f) for f in ctx.screen_files] or [("home_screen", "HomeScreen")]
    return [
        GeneratedFile(path="frontend/lib/main.dart", language="dart", content=_build_main_dart(ctx.project_name, screens), description="Flutter app entry point"),
    ]


def setup_commands(project_name: str) -> list[str]:
    return [
        "cd frontend",
        "flutter pub get",
        "flutter run                 # run on a connected device/emulator",
        "flutter build apk           # Android",
        "flutter build windows       # Windows desktop",
        "flutter build ios           # iOS (requires macOS + Xcode)",
    ]


ADAPTER = FrontendAdapter(
    key="flutter",
    label="Flutter",
    supported_languages=("dart",),
    generate_screen=generate_screen,
    manifest_files=manifest_files,
    entry_point_files=entry_point_files,
    setup_commands=setup_commands,
)
