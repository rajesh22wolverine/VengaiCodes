# ═══════════════════════════════════════════════════════════════
#  VengaiCode — SwiftUI Frontend Adapter
#  ai/codegen/frontend/swiftui.py — Third "native" (non-web) frontend.
#
#  2026-09-21: now ships a REAL, CI-verified Xcode project, not just
#  loose files. A hand-authored .xcodeproj (its project.pbxproj is a
#  quasi-binary plist graph, not clean text like package.json) is still
#  out of scope — but XcodeGen (github.com/yonaskolb/XcodeGen) solves
#  exactly this: a small, fully-text project.yml spec that XcodeGen
#  turns into a real .xcodeproj deterministically. manifest_files() below
#  emits that project.yml (plus the Info.plist properties XcodeGen
#  generates the plist from); .github/workflows/build-swiftui-project.yml
#  runs `xcodegen generate` + `xcodebuild build -destination 'generic/
#  platform=iOS Simulator'` on a macos-latest runner (free — public repo)
#  to prove the generated app actually compiles, then ships the real
#  project (source + generated .xcodeproj) as the download.
#
#  HONEST REMAINING GAP: CI proves a *simulator* build compiles —
#  CODE_SIGNING_ALLOWED=NO, no signing identity involved. A signed,
#  device-installable .ipa needs the end user's own Apple Developer
#  account/certificates, which VengaiCode has no access to and can't
#  fabricate; that step stays manual (see setup_commands()).
# ═══════════════════════════════════════════════════════════════

from app.ai.codegen.types import FileResult, FrontendAdapter, ScreenCtx, WiringCtx
from app.ai.codegen_shared import (
    GROQ_FILE_MAX_TOKENS,
    NATIVE_CAPABILITY_DESCRIPTIONS,
    GeneratedFile,
    _pascal,
    build_design_guidance_block,
    build_endpoints_block,
    generate_text_validated,
)


def _app_name(project_name: str) -> str:
    """Xcode-safe target/scheme/app name — alphanumeric only, so it's
    always a valid Swift identifier AND a valid Xcode target name.
    Shared by every place that needs to agree on the same name (the
    @main App struct, project.yml's target/scheme, the bundle id)."""
    return "".join(ch for ch in project_name.title() if ch.isalnum()) or "GeneratedApp"


async def generate_screen(ctx: ScreenCtx) -> FileResult:
    screen_name = ctx.screen.get("name", "Screen")
    struct_name = f"{_pascal(screen_name)}View"
    endpoints_text = build_endpoints_block(ctx.endpoints, ctx.api_style)
    # `URLSession.shared.data(from:)` (the REST bullet below) is GET-only
    # — it can't send a request body, so it can't express a GraphQL POST.
    fetch_bullet = (
        "- Real state via `@State` properties. Fetch data with EXACTLY this async pattern inside "
        '`.task { ... }`: build `var request = URLRequest(url: url); request.httpMethod = "POST"; '
        'request.setValue("application/json", forHTTPHeaderField: "Content-Type"); '
        "request.httpBody = try JSONEncoder().encode(GraphQLRequestBody(query: ..., variables: ...))`, "
        "then `let (data, _) = try await URLSession.shared.data(for: request)` then "
        "`let decoded = try JSONDecoder().decode(SomeType.self, from: data)` — do not invent a "
        "different URLSession method signature (no completion-handler closures). Define a small "
        "`Encodable GraphQLRequestBody` struct with `query`/`variables` fields in this file."
        if ctx.api_style == "graphql"
        else "- Real state via `@State` properties. Fetch data with EXACTLY this async pattern inside "
        "`.task { ... }`: `let (data, _) = try await URLSession.shared.data(from: url)` then "
        "`let decoded = try JSONDecoder().decode(SomeType.self, from: data)` — do not invent a "
        "different URLSession method signature (no completion-handler closures)."
    )

    capabilities_text = "\n".join(
        f"- {NATIVE_CAPABILITY_DESCRIPTIONS[c]}"
        for c in ctx.native_capabilities
        if c in NATIVE_CAPABILITY_DESCRIPTIONS
    )
    native_section = (
        f"\nNative device features available to this app (use the real iOS/Swift API for each, "
        f"not a web substitute):\n{capabilities_text}\n"
        if capabilities_text
        else ""
    )
    design_guidance = build_design_guidance_block(
        ctx.design_style, ctx.color_palette, ctx.typography, ctx.screen.get("modules")
    )

    prompt = f"""Write ONE complete, real SwiftUI View struct implementing the "{screen_name}" screen of this app.

Screen purpose: {ctx.screen.get("purpose", "")}

API endpoints this screen can call:
{endpoints_text}
{native_section}{design_guidance}
Requirements:
- Struct name: {struct_name}, conforming to `View`, with a `var body: some View`.
{fetch_bullet}
- You MUST define every `Decodable` struct you reference directly in THIS file, with fields
  matching the API response shape — never reference an undefined type. Do not reference any
  other view, function, or helper not defined in this one file.
- Use only real, existing SwiftUI view/modifier names (VStack, List, TextField, Button,
  ProgressView, etc.) — do not invent modifiers that don't exist in SwiftUI.
- No placeholder text or TODO comments, this must be fully implemented.
- If a visual style/color palette/typography is specified above, reflect it in your layout —
  approximate palette hex codes with `Color(red:green:blue:)` computed from the hex value.

Return ONLY the raw Swift code for this one file (imports + the Decodable model(s) it needs +
the View struct). No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(
        prompt,
        "swift",
        GROQ_FILE_MAX_TOKENS,
        user=ctx.user,
        db=ctx.db,
        context=ctx.shared_context(),
    )
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
        f"            {s}()\n"
        f'                .tabItem {{ Label("{s.removesuffix("View")}", systemImage: "{i + 1}.circle") }}'
        for i, s in enumerate(struct_names)
    )
    app_name = _app_name(project_name)

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


# XcodeGen (https://github.com/yonaskolb/XcodeGen) project spec. Kept as an
# f-string, not a YAML library call, deliberately: this project has no YAML
# writer dependency anywhere else and the shape here is fixed/small enough
# that hand-formatted YAML is safe (no user-controlled strings need escaping
# — app_name is already alphanumeric-only via _app_name()).
#
# CODE_SIGNING_ALLOWED: NO + info.properties (no checked-in Info.plist) are
# both deliberate: CI builds for the simulator only (see module header), and
# XcodeGen generates Info.plist itself from `properties` when the file at
# `info.path` doesn't exist — one less hand-authored plist to get wrong.
# NSAllowsArbitraryLoads is set because a generated app's backend URL could
# be plain-HTTP local dev (e.g. Tauri's own http://localhost:8000 default) —
# without it, iOS's App Transport Security silently blocks every request.
_PROJECT_YML_TEMPLATE = """name: {app_name}
options:
  bundleIdPrefix: com.vengaicode.generated
  deploymentTarget:
    iOS: "16.0"
targets:
  {app_name}:
    type: application
    platform: iOS
    sources:
      - path: .
        excludes:
          - "project.yml"
          - "*.md"
    info:
      path: Info.plist
      properties:
        CFBundleDisplayName: {app_name}
        UILaunchScreen: {{}}
        NSAppTransportSecurity:
          NSAllowsArbitraryLoads: true
    settings:
      base:
        PRODUCT_BUNDLE_IDENTIFIER: com.vengaicode.generated.{bundle_suffix}
        SWIFT_VERSION: "5.0"
        TARGETED_DEVICE_FAMILY: "1,2"
        MARKETING_VERSION: "1.0.0"
        CURRENT_PROJECT_VERSION: "1"
        GENERATE_INFOPLIST_FILE: NO
        CODE_SIGN_STYLE: Manual
        CODE_SIGNING_REQUIRED: NO
        CODE_SIGNING_ALLOWED: NO
        DEVELOPMENT_TEAM: ""
schemes:
  {app_name}:
    build:
      targets:
        {app_name}: all
    run:
      config: Debug
"""


def _project_yml(project_name: str) -> str:
    app_name = _app_name(project_name)
    return _PROJECT_YML_TEMPLATE.format(
        app_name=app_name, bundle_suffix=app_name.lower()
    )


def manifest_files(ctx: WiringCtx) -> list[GeneratedFile]:
    return [
        GeneratedFile(
            path="frontend/project.yml",
            language="yaml",
            content=_project_yml(ctx.project_name),
            description=(
                "XcodeGen spec — run `xcodegen generate` to produce a real .xcodeproj "
                "(also what CI runs to verify this builds)"
            ),
        ),
    ]


def setup_commands(project_name: str) -> list[str]:
    app_name = _app_name(project_name)
    return [
        "cd frontend",
        "# Requires Xcode (macOS only) + XcodeGen: brew install xcodegen",
        "xcodegen generate",
        f'open "{app_name}.xcodeproj"',
        "# Build and run (Cmd+R) on a simulator or a signed device/team.",
        "# CI already verified a simulator build compiles — see the Packaging",
        "# screen's 'iOS (Xcode Project)' card. A signed, device-installable",
        "# .ipa needs your own Apple Developer account — Xcode's Signing &",
        "# Capabilities tab, not something this pipeline can produce for you.",
    ]


def entry_point_files(ctx: WiringCtx) -> list[GeneratedFile]:
    struct_names = [_screen_struct_from_path(f) for f in ctx.screen_files] or [
        "HomeView"
    ]
    return [
        GeneratedFile(
            path=f"frontend/{_app_name(ctx.project_name)}App.swift",
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
    manifest_files=manifest_files,
    entry_point_files=entry_point_files,
    setup_commands=setup_commands,
)
