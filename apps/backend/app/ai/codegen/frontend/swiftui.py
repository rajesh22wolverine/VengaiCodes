# ═══════════════════════════════════════════════════════════════
#  VengaiCode — SwiftUI Frontend Adapter
#  ai/codegen/frontend/swiftui.py — Third "native" (non-web) frontend,
#  and deliberately the most minimal wiring of the three.
#
#  HONEST SCOPE: no manifest file is generated at all — no Package.swift.
#  A Swift Package Manager manifest is what you'd open with `swift build`/
#  `swift package`, which does NOT produce a runnable iOS app; a real
#  SwiftUI iOS app needs an actual .xcodeproj/.xcworkspace with an
#  Info.plist and asset catalog, which can't be reliably hand-authored
#  as text the way a package.json or pubspec.yaml can. So this ships
#  loose .swift source files (including a real `@main` App struct) and
#  a README instructing the user to create a new Xcode SwiftUI-lifecycle
#  iOS App project and copy these files in — Xcode's own project wizard
#  IS the real "manifest step" here, not a checked-in file.
# ═══════════════════════════════════════════════════════════════

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
    struct_name = f"{_pascal(screen_name)}View"
    endpoints_text = "\n".join(
        f"- {e.get('method')} {e.get('path')}: {e.get('purpose')}" for e in ctx.endpoints
    )

    capabilities_text = "\n".join(
        f"- {NATIVE_CAPABILITY_DESCRIPTIONS[c]}" for c in ctx.native_capabilities if c in NATIVE_CAPABILITY_DESCRIPTIONS
    )
    native_section = (
        f"\nNative device features available to this app (use the real iOS/Swift API for each, "
        f"not a web substitute):\n{capabilities_text}\n"
        if capabilities_text
        else ""
    )

    prompt = f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Write ONE complete, real SwiftUI View struct implementing the "{screen_name}" screen of this app.

App: {ctx.project_name}
{ctx.requirements_text}
Screen purpose: {ctx.screen.get('purpose', '')}

API endpoints this screen can call:
{endpoints_text}
{native_section}
Requirements:
- Struct name: {struct_name}, conforming to `View`, with a `var body: some View`.
- Real state via `@State` properties. Fetch data with EXACTLY this async pattern inside
  `.task {{ ... }}`: `let (data, _) = try await URLSession.shared.data(from: url)` then
  `let decoded = try JSONDecoder().decode(SomeType.self, from: data)` — do not invent a different
  URLSession method signature (no completion-handler closures).
- You MUST define every `Decodable` struct you reference directly in THIS file, with fields
  matching the API response shape — never reference an undefined type. Do not reference any
  other view, function, or helper not defined in this one file.
- Use only real, existing SwiftUI view/modifier names (VStack, List, TextField, Button,
  ProgressView, etc.) — do not invent modifiers that don't exist in SwiftUI.
- No placeholder text or TODO comments, this must be fully implemented.

Return ONLY the raw Swift code for this one file (imports + the Decodable model(s) it needs +
the View struct). No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(prompt, "swift", GROQ_FILE_MAX_TOKENS)
    return GeneratedFile(
        path=f"frontend/{struct_name}.swift",
        language="swift",
        content=content,
        description=f"Screen implementing {screen_name}",
    ), issue


def _screen_struct_from_path(file: GeneratedFile) -> str:
    return file.path.split("/")[-1].removesuffix(".swift")


def _build_app_swift(project_name: str, struct_names: list[str]) -> str:
    tab_items = "\n".join(
        f'            {s}()\n'
        f'                .tabItem {{ Label("{s.removesuffix("View")}", systemImage: "{i + 1}.circle") }}'
        for i, s in enumerate(struct_names)
    )
    app_name = "".join(ch for ch in project_name.title() if ch.isalnum()) or "GeneratedApp"

    if len(struct_names) > 1:
        root_view = f"""struct RootView: View {{
    var body: some View {{
        TabView {{
{tab_items}
        }}
    }}
}}
"""
        root_ref = "RootView()"
    else:
        root_view = ""
        root_ref = f"{struct_names[0]}()"

    return f"""import SwiftUI

{root_view}
@main
struct {app_name}App: App {{
    var body: some Scene {{
        WindowGroup {{
            {root_ref}
        }}
    }}
}}
"""


def setup_commands(project_name: str) -> list[str]:
    return [
        "# Requires Xcode (macOS only). No Package.swift/xcodeproj is generated —",
        "# create the project shell in Xcode, then copy these files in:",
        "# 1. Open Xcode -> File -> New -> Project -> iOS -> App",
        f'#    Product Name: "{project_name}", Interface: SwiftUI, Language: Swift',
        "# 2. Delete the default ContentView.swift Xcode generated",
        "# 3. Drag every .swift file from this folder into the Xcode project navigator",
        "# 4. Build and run (Cmd+R) on a simulator or device",
    ]


def entry_point_files(ctx: WiringCtx) -> list[GeneratedFile]:
    struct_names = [_screen_struct_from_path(f) for f in ctx.screen_files] or ["HomeView"]
    return [
        GeneratedFile(
            path=f"frontend/{''.join(ch for ch in ctx.project_name.title() if ch.isalnum()) or 'GeneratedApp'}App.swift",
            language="swift",
            content=_build_app_swift(ctx.project_name, struct_names),
            description="SwiftUI app entry point — renders every generated screen as a tab",
        ),
    ]


ADAPTER = FrontendAdapter(
    key="swiftui",
    label="SwiftUI",
    supported_languages=("swift",),
    generate_screen=generate_screen,
    entry_point_files=entry_point_files,
    setup_commands=setup_commands,
)
