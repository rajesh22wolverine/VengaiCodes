# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Godot Engine Codegen (game frontend)
#  ai/codegen/godot.py — Like O3DE (app/ai/codegen/o3de.py), Godot pairs
#  with stack_matrix.py's "none" backend sentinel (no separate REST/
#  GraphQL/gRPC backend — a game talks to whatever HTTP endpoints it
#  needs directly), so it never fit the FrontendAdapter registry shape
#  and is dispatched from its own branch in codegen.py, same as O3DE.
#
#  UNLIKE O3DE, Godot is registered in stack_matrix.CI_BUILDABLE_GAME_
#  ENGINES: its CLI export (`godot --headless --export-release`) uses
#  pre-built export templates, not a multi-hour engine compile, so
#  both android_packaging.py AND packaging.py (Windows) can turn this
#  into a real installable build via CI — see
#  .github/workflows/build-android-game-godot.yml and
#  build-windows-game-godot.yml. ONE export_presets.cfg holds both
#  platform presets (Godot's normal convention — a project's presets
#  all live in one file), so codegen only runs once regardless of
#  which platform(s) a user ends up building.
#
#  HONEST STATUS: no Godot editor/binary is available in this
#  environment to live-verify a real export (same class of limitation
#  documented in jetpack_compose.py's header). The GDScript API calls
#  used in the screen prompt (HTTPRequest, JSON.parse_string, the
#  Control-node layout calls) and the project.godot / Main.tscn shapes
#  below are standard, stable Godot 4 patterns. export_presets.cfg's
#  field names for BOTH presets (Android: keystore/debug, keystore/
#  release, package/unique_name, architectures/arm64-v8a, gradle_build/
#  use_gradle_build; Windows Desktop: binary_format/architecture,
#  texture_format/s3tc_bptc, codesign/enable, application/product_name)
#  were cross-checked against a real, working reference project —
#  abarichello/godot-ci's test-project — rather than invented; that
#  project is also the source for the CI keystore-signing approach used
#  in the Android workflow (sed-patching keystore/release* fields,
#  never regenerating the whole file). binary_format/embed_pck is set
#  to true (unlike that reference's default of false) so a Windows
#  export produces one standalone .exe instead of an .exe+.pck pair —
#  a real, documented toggle, not an invented field. Treat
#  export_presets.cfg as the least-verified piece here — both
#  workflows' own headers repeat this caveat.
# ═══════════════════════════════════════════════════════════════

from app.ai.codegen.types import FileResult, ScreenCtx
from app.ai.codegen_shared import (
    GROQ_FILE_MAX_TOKENS,
    NATIVE_CAPABILITY_DESCRIPTIONS,
    GeneratedFile,
    _pascal,
    android_package_segment,
    generate_text_validated,
)


def _package_name(project_name: str) -> str:
    return f"com.vengaicode.generated.{android_package_segment(project_name)}"


def _class_name(screen_name: str) -> str:
    return f"{_pascal(screen_name)}Screen"


async def generate_screen(ctx: ScreenCtx) -> FileResult:
    class_name = _class_name(ctx.screen.get("name", "Screen"))
    screen_name = ctx.screen.get("name", "Screen")
    endpoints_text = "\n".join(
        f"- {e.get('method')} {e.get('path')}: {e.get('purpose')}" for e in ctx.endpoints
    )

    capabilities_text = "\n".join(
        f"- {NATIVE_CAPABILITY_DESCRIPTIONS[c]}" for c in ctx.native_capabilities if c in NATIVE_CAPABILITY_DESCRIPTIONS
    )
    native_section = (
        f"\nDevice features available (describe the gameplay/UX use in comments — Godot's own "
        f"OS/Input APIs cover these natively, no plugin needed):\n{capabilities_text}\n"
        if capabilities_text
        else ""
    )

    prompt = f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Write ONE complete, real Godot 4 GDScript file implementing the "{screen_name}" scene of this game.

Game: {ctx.project_name}
{ctx.requirements_text}
Scene purpose: {ctx.screen.get('purpose', '')}

API endpoints this scene can call:
{endpoints_text}
{native_section}
Requirements:
- First two lines MUST be exactly:
  extends Control
  class_name {class_name}
- Build the ENTIRE UI/scene tree in code inside `_ready()` — instantiate nodes with
  `SomeType.new()` (Label, Button, VBoxContainer, HBoxContainer, TextureRect, ColorRect,
  Sprite2D, etc. — whichever real Godot 4 node types fit this scene, 2D/3D/UI as the scene
  purpose calls for) and `add_child()` them. Do not reference an external .tscn scene file.
- For any network calls: create `var http := HTTPRequest.new()`, `add_child(http)`, connect
  `http.request_completed` to a handler `func _on_request_completed(result, response_code,
  headers, body):`, parse the response with `JSON.parse_string(body.get_string_from_utf8())`.
  Call `http.request(url)` (or with a JSON body + `["Content-Type: application/json"]` headers
  for POST/PUT) inside `_ready()` or in response to a real user action, matching this scene's
  purpose. Handle the loading state and a failed/non-200 response.
- Implement real, working gameplay/UI logic for this scene's actual purpose and the feature/
  user-story text above — real state (exported or plain `var`s), real input handling
  (`_input()`/`_process()`/button `pressed` signals as appropriate), no placeholders or TODOs.
- This file MUST be fully self-contained: do not reference any class or node defined in another
  script file. Represent any parsed JSON as plain `Dictionary`/`Array` values, and build any
  repeated/list UI (e.g. an inventory, a leaderboard) by instantiating controls in a loop
  directly inside this file — no separate item-scene dependency.

Return ONLY the raw GDScript code for this one file. No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(prompt, "gdscript", GROQ_FILE_MAX_TOKENS)
    return GeneratedFile(
        path=f"frontend/scenes/{class_name}.gd",
        language="gdscript",
        content=content,
        description=f"Scene implementing {screen_name}",
    ), issue


_PROJECT_GODOT = """; Engine configuration file.
; This file is best edited using the editor UI, not directly — these are
; the minimal keys Godot 4 needs to open and run the project headlessly.
config_version=5

[application]

config/name="{project_name}"
run/main_scene="res://Main.tscn"
config/features=PackedStringArray("4.3", "GL Compatibility")

[rendering]

renderer/rendering_method="gl_compatibility"
renderer/rendering_method.mobile="gl_compatibility"
"""

# Field names verified against a real, working reference project
# (abarichello/godot-ci's test-project export_presets.cfg) rather than
# invented — see this module's header comment. gradle_build/use_gradle_build
# is deliberately false: Godot's own pre-built export templates package the
# APK directly, so the CI runner never needs a separate Android SDK/NDK/
# Gradle toolchain — only the Godot binary + export templates (both baked
# into the barichello/godot-ci Docker image the workflow uses).
_EXPORT_PRESETS_CFG = """[preset.0]

name="Android"
platform="Android"
runnable=true
advanced_options=false
dedicated_server=false
custom_features=""
export_filter="all_resources"
include_filter=""
exclude_filter=""
export_path="build.apk"
encryption_include_filters=""
encryption_exclude_filters=""
encrypt_pck=false
encrypt_directory=false

[preset.0.options]

gradle_build/use_gradle_build=false
gradle_build/export_format=0
architectures/armeabi-v7a=false
architectures/arm64-v8a=true
architectures/x86=false
architectures/x86_64=false
version/code=1
version/name="1.0"
package/unique_name="{package_name}"
package/name="{project_name}"
package/signed=true
package/app_category=2
package/retain_data_on_uninstall=false
graphics/opengl_debug=false
screen/immersive_mode=true
screen/support_small=true
screen/support_normal=true
screen/support_large=true
screen/support_xlarge=true
user_data_backup/allow=false
permissions/internet=true
keystore/debug=""
keystore/debug_user=""
keystore/debug_password=""
keystore/release=""
keystore/release_user=""
keystore/release_password=""

[preset.1]

name="Windows Desktop"
platform="Windows Desktop"
runnable=true
advanced_options=false
dedicated_server=false
custom_features=""
export_filter="all_resources"
include_filter=""
exclude_filter=""
export_path="build.exe"
encryption_include_filters=""
encryption_exclude_filters=""
encrypt_pck=false
encrypt_directory=false
script_export_mode=2

[preset.1.options]

custom_template/debug=""
custom_template/release=""
debug/export_console_wrapper=1
binary_format/embed_pck=true
binary_format/architecture="x86_64"
binary_format/64_bits=true
texture_format/s3tc_bptc=true
texture_format/etc2_astc=false
texture_format/bptc=true
texture_format/s3tc=true
texture_format/etc=true
texture_format/etc2=true
texture_format/no_bptc_fallbacks=true
codesign/enable=false
codesign/timestamp=true
codesign/timestamp_server_url=""
codesign/digest_algorithm=1
codesign/description=""
application/modify_resources=true
application/icon=""
application/console_wrapper_icon=""
application/icon_interpolation=4
application/file_version="1.0.0"
application/product_version="1.0.0"
application/company_name=""
application/product_name="{project_name}"
application/file_description="{project_name}"
application/copyright=""
application/trademarks=""
application/export_angle=0
application/export_d3d12=0
application/d3d12_agility_sdk_multiarch=true
ssh_remote_deploy/enabled=false
"""

_MAIN_TSCN = """[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://Main.gd" id="1"]

[node name="Main" type="Control"]
layout_mode = 3
anchors_preset = 15
anchor_right = 1.0
anchor_bottom = 1.0
grow_horizontal = 2
grow_vertical = 2
script = ExtResource("1")
"""


def _screen_class_from_path(file: GeneratedFile) -> str:
    return file.path.split("/")[-1].removesuffix(".gd")


def _build_main_gd(class_names: list[str]) -> str:
    names_literal = ", ".join(f'"{c.removesuffix("Screen")}"' for c in class_names)
    classes_literal = ", ".join(class_names)

    return f"""extends Control

const SCREEN_NAMES: Array[String] = [{names_literal}]
const SCREEN_CLASSES: Array = [{classes_literal}]

var _body: Control


func _ready() -> void:
    set_anchors_preset(Control.PRESET_FULL_RECT)
    var root := VBoxContainer.new()
    root.set_anchors_preset(Control.PRESET_FULL_RECT)
    add_child(root)

    if SCREEN_NAMES.size() > 1:
        var tab_bar := HBoxContainer.new()
        root.add_child(tab_bar)
        for i in SCREEN_NAMES.size():
            var btn := Button.new()
            btn.text = SCREEN_NAMES[i]
            btn.pressed.connect(_show_screen.bind(i))
            tab_bar.add_child(btn)

    _body = Control.new()
    _body.size_flags_vertical = Control.SIZE_EXPAND_FILL
    _body.set_anchors_preset(Control.PRESET_FULL_RECT)
    root.add_child(_body)

    _show_screen(0)


func _show_screen(index: int) -> void:
    for child in _body.get_children():
        child.queue_free()
    var screen: Control = SCREEN_CLASSES[index].new()
    screen.set_anchors_preset(Control.PRESET_FULL_RECT)
    _body.add_child(screen)
"""


def manifest_files(project_name: str) -> list[GeneratedFile]:
    package_name = _package_name(project_name)
    return [
        GeneratedFile(
            path="frontend/project.godot",
            language="ini",
            content=_PROJECT_GODOT.format(project_name=project_name),
            description="Godot project configuration",
        ),
        GeneratedFile(
            path="frontend/export_presets.cfg",
            language="ini",
            content=_EXPORT_PRESETS_CFG.format(package_name=package_name, project_name=project_name),
            description="Android + Windows Desktop export presets (least-verified file in this pipeline — see godot.py header)",
        ),
    ]


def entry_point_files(screen_files: list[GeneratedFile]) -> list[GeneratedFile]:
    class_names = [_screen_class_from_path(f) for f in screen_files] or ["HomeScreen"]
    return [
        GeneratedFile(
            path="frontend/Main.gd",
            language="gdscript",
            content=_build_main_gd(class_names),
            description="Root scene script — switches between every generated screen",
        ),
        GeneratedFile(
            path="frontend/Main.tscn",
            language="text",
            content=_MAIN_TSCN,
            description="Root scene — attaches Main.gd, set as run/main_scene",
        ),
    ]


def setup_commands(project_name: str) -> list[str]:
    return [
        "cd frontend",
        "# Requires the Godot 4 editor installed (https://godotengine.org/download)",
        "# Open this folder as a project in Godot, or run headlessly:",
        'godot --headless --export-debug "Android" build.apk           # requires Android export templates installed',
        'godot --headless --export-debug "Windows Desktop" build.exe   # requires Windows export templates installed',
        "# Or open the project in the Godot editor and use Project > Export.",
    ]
