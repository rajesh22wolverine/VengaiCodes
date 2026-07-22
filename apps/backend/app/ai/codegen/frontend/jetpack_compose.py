# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Jetpack Compose Frontend Adapter
#  ai/codegen/frontend/jetpack_compose.py — Second "native" (non-web)
#  frontend. Produces a real Kotlin/Gradle Android project, not a
#  wrapped web bundle — never flows through the Tauri/Capacitor
#  packaging pipeline (category="mobile", blocked by the same guard as
#  Flutter/SwiftUI).
#
#  HONEST LIMITATION: no Android SDK/Gradle is available in this
#  environment to live-verify a real build (unlike React/Vue/Angular,
#  which WERE verified with real `npm install`/build runs — see
#  angular.py's header). The Gradle/AGP/Kotlin/Compose-compiler
#  versions below are a real, documented-compatible combination from
#  JetBrains' official Compose-Kotlin compatibility map as of Kotlin
#  1.9.22 (Compose compiler extension 1.5.8) — pinned deliberately
#  rather than left for the AI to guess, since this combination is
#  notoriously strict. Re-check that map before bumping any of these.
# ═══════════════════════════════════════════════════════════════

import re

from app.ai.codegen.types import FileResult, FrontendAdapter, ScreenCtx, WiringCtx
from app.ai.codegen_shared import (
    GROQ_FILE_MAX_TOKENS,
    NATIVE_CAPABILITY_DESCRIPTIONS,
    GeneratedFile,
    _pascal,
    android_package_segment,
    generate_text_validated,
)

_KOTLIN_VERSION = "1.9.22"
_COMPOSE_COMPILER_EXT = "1.5.8"
_AGP_VERSION = "8.2.2"
_GRADLE_VERSION = "8.4"
_COMPILE_SDK = 34
_MIN_SDK = 24
_TARGET_SDK = 34


def _snake(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", name or "screen").strip("_").lower()
    if cleaned and cleaned[0].isdigit():
        cleaned = f"s_{cleaned}"
    return cleaned or "screen"


def _package_name(project_name: str) -> str:
    return f"com.vengaicode.generated.{android_package_segment(project_name)}"


def _package_path(package_name: str) -> str:
    return package_name.replace(".", "/")


async def generate_screen(ctx: ScreenCtx) -> FileResult:
    screen_name = ctx.screen.get("name", "Screen")
    class_name = f"{_pascal(screen_name)}Screen"
    package_name = _package_name(ctx.project_name)
    endpoints_text = "\n".join(
        f"- {e.get('method')} {e.get('path')}: {e.get('purpose')}" for e in ctx.endpoints
    )

    capabilities_text = "\n".join(
        f"- {NATIVE_CAPABILITY_DESCRIPTIONS[c]}" for c in ctx.native_capabilities if c in NATIVE_CAPABILITY_DESCRIPTIONS
    )
    native_section = (
        f"\nNative device features available to this app (use the real Android/Kotlin API for "
        f"each, not a web substitute):\n{capabilities_text}\n"
        if capabilities_text
        else ""
    )

    prompt = f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Write ONE complete, real Jetpack Compose composable function implementing the "{screen_name}" screen of this app.

App: {ctx.project_name}
{ctx.requirements_text}
Screen purpose: {ctx.screen.get('purpose', '')}

API endpoints this screen can call:
{endpoints_text}
{native_section}
Requirements:
- Package declaration: `package {package_name}.screens`
- Function signature: `@Composable\\nfun {class_name}() {{ ... }}` — a single composable, no Activity/nav code here.
- Real state via `remember {{ mutableStateOf(...) }}`, fetch real data inside `LaunchedEffect(Unit)`
  using a suspend helper that calls `java.net.URL(...).readText()` wrapped in
  `withContext(Dispatchers.IO)`, parsed with `org.json.JSONArray`/`JSONObject` (built into
  Android, no extra dependency). Handle loading/error state.
- Use Material3 composables (Column, LazyColumn, Text, Button, OutlinedTextField, etc.) for a
  real, usable UI — implement the actual feature/user-story behavior, no placeholders or TODOs.
- This file MUST be fully self-contained: do not reference any class, function, or composable
  defined in another file (no separate model classes, no helper composables like a "TaskItem" you
  haven't defined here). Represent parsed JSON as plain `Map`/`List` values or a data class you
  define in THIS file, and inline any row/item rendering directly inside this composable.

Return ONLY the raw Kotlin code for this one file (package line + imports + the composable
function). No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(prompt, "kotlin", GROQ_FILE_MAX_TOKENS)
    return GeneratedFile(
        path=f"frontend/app/src/main/java/{_package_path(package_name)}/screens/{class_name}.kt",
        language="kotlin",
        content=content,
        description=f"Screen implementing {screen_name}",
    ), issue


def _screen_class_from_path(file: GeneratedFile) -> str:
    return file.path.split("/")[-1].removesuffix(".kt")


def _build_main_activity(project_name: str, package_name: str, class_names: list[str]) -> str:
    imports = "\n".join(f"import {package_name}.screens.{c}" for c in class_names)
    names = ", ".join(f'"{c.removesuffix("Screen")}"' for c in class_names)
    when_branches = "\n".join(f"                        {i} -> {c}()" for i, c in enumerate(class_names))

    return f"""package {package_name}

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
{imports}

class MainActivity : ComponentActivity() {{
    override fun onCreate(savedInstanceState: Bundle?) {{
        super.onCreate(savedInstanceState)
        setContent {{
            MaterialTheme {{
                RootNav()
            }}
        }}
    }}
}}

@Composable
fun RootNav() {{
    var active by remember {{ mutableStateOf(0) }}
    val names = listOf({names})

    Scaffold(
        topBar = {{
            if (names.size > 1) {{
                Row(modifier = Modifier.fillMaxWidth().padding(8.dp)) {{
                    names.forEachIndexed {{ i, name ->
                        Button(
                            onClick = {{ active = i }},
                            modifier = Modifier.padding(horizontal = 4.dp),
                        ) {{ Text(name) }}
                    }}
                }}
            }}
        }}
    ) {{ padding ->
        Box(modifier = Modifier.padding(padding)) {{
            when (active) {{
{when_branches}
            }}
        }}
    }}
}}
"""


def _settings_gradle_kts(project_name: str) -> str:
    return f"""pluginManagement {{
    repositories {{
        google()
        mavenCentral()
        gradlePluginPortal()
    }}
}}
dependencyResolutionManagement {{
    repositories {{
        google()
        mavenCentral()
    }}
}}

rootProject.name = "{project_name}"
include(":app")
"""


_ROOT_BUILD_GRADLE_KTS = f"""plugins {{
    id("com.android.application") version "{_AGP_VERSION}" apply false
    id("org.jetbrains.kotlin.android") version "{_KOTLIN_VERSION}" apply false
}}
"""


def _app_build_gradle_kts(package_name: str) -> str:
    return f"""plugins {{
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}}

android {{
    namespace = "{package_name}"
    compileSdk = {_COMPILE_SDK}

    defaultConfig {{
        applicationId = "{package_name}"
        minSdk = {_MIN_SDK}
        targetSdk = {_TARGET_SDK}
        versionCode = 1
        versionName = "1.0"
    }}

    buildFeatures {{
        compose = true
    }}
    composeOptions {{
        kotlinCompilerExtensionVersion = "{_COMPOSE_COMPILER_EXT}"
    }}
    compileOptions {{
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }}
    kotlinOptions {{
        jvmTarget = "17"
    }}
    testOptions {{
        // Required for Robolectric to load real Android resources/assets
        // during `./gradlew test` — without this, Robolectric-backed
        // Compose UI tests fail to resolve resources at test time.
        unitTests {{
            isIncludeAndroidResources = true
        }}
    }}
}}

dependencies {{
    implementation(platform("androidx.compose:compose-bom:2024.02.00"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.activity:activity-compose:1.8.2")
    implementation("androidx.core:core-ktx:1.12.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.7.3")

    // Compose UI testing via Robolectric — real render/click/assert
    // testing on the JVM, no Android emulator needed.
    testImplementation(platform("androidx.compose:compose-bom:2024.02.00"))
    testImplementation("androidx.compose.ui:ui-test-junit4")
    testImplementation("org.robolectric:robolectric:4.12.2")
    testImplementation("junit:junit:4.13.2")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
}}
"""


def _android_manifest(project_name: str) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">

    <uses-permission android:name="android.permission.INTERNET" />

    <application
        android:label="{project_name}"
        android:theme="@android:style/Theme.Material.Light.NoActionBar">
        <activity
            android:name=".MainActivity"
            android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
"""


_GRADLE_WRAPPER_PROPERTIES = f"""distributionBase=GRADLE_USER_HOME
distributionPath=wrapper/dists
distributionUrl=https\\://services.gradle.org/distributions/gradle-{_GRADLE_VERSION}-bin.zip
zipStoreBase=GRADLE_USER_HOME
zipStorePath=wrapper/dists
"""

_GRADLE_PROPERTIES = """org.gradle.jvmargs=-Xmx2048m
android.useAndroidX=true
kotlin.code.style=official
"""


def manifest_files(ctx: WiringCtx) -> list[GeneratedFile]:
    package_name = _package_name(ctx.project_name)
    return [
        GeneratedFile(path="frontend/settings.gradle.kts", language="kotlin", content=_settings_gradle_kts(ctx.project_name), description="Gradle settings"),
        GeneratedFile(path="frontend/build.gradle.kts", language="kotlin", content=_ROOT_BUILD_GRADLE_KTS, description="Root Gradle build file"),
        GeneratedFile(path="frontend/gradle.properties", language="text", content=_GRADLE_PROPERTIES, description="Gradle properties"),
        GeneratedFile(path="frontend/gradle/wrapper/gradle-wrapper.properties", language="text", content=_GRADLE_WRAPPER_PROPERTIES, description="Pinned Gradle wrapper version"),
        GeneratedFile(path="frontend/app/build.gradle.kts", language="kotlin", content=_app_build_gradle_kts(package_name), description="App module Gradle build file"),
        GeneratedFile(path="frontend/app/src/main/AndroidManifest.xml", language="xml", content=_android_manifest(ctx.project_name), description="Android manifest"),
    ]


def entry_point_files(ctx: WiringCtx) -> list[GeneratedFile]:
    package_name = _package_name(ctx.project_name)
    class_names = [_screen_class_from_path(f) for f in ctx.screen_files] or ["HomeScreen"]
    main_activity = _build_main_activity(ctx.project_name, package_name, class_names)
    return [
        GeneratedFile(
            path=f"frontend/app/src/main/java/{_package_path(package_name)}/MainActivity.kt",
            language="kotlin",
            content=main_activity,
            description="Main Activity — renders every generated screen",
        ),
    ]


def setup_commands(project_name: str) -> list[str]:
    return [
        "cd frontend",
        "# Requires Android Studio or the Android SDK command-line tools installed",
        "./gradlew assembleDebug     # builds app/build/outputs/apk/debug/app-debug.apk",
        "# Or open this folder in Android Studio and click Run",
    ]


ADAPTER = FrontendAdapter(
    key="jetpack_compose",
    label="Jetpack Compose",
    supported_languages=("kotlin",),
    generate_screen=generate_screen,
    manifest_files=manifest_files,
    entry_point_files=entry_point_files,
    setup_commands=setup_commands,
)
