"""Rename the built APK to reflect the project's app name.

Run from the `build/` working directory, after the Gradle/Flutter/Godot
build. The build tool always names its output something generic
(app-debug.apk, app-release.apk, build.apk) regardless of applicationId
or app label, so without this step the artifact a user downloads
carries no trace of what they named their app.

APK_GLOB defaults to the Capacitor pipeline's nested `android/` layout
(build-android-installer.yml, where `npx cap add android` creates that
subfolder). The native Compose/Flutter/Godot pipelines pass a different
glob via the APK_GLOB env var, since their Gradle/build root IS build/
itself — no extra `android/` nesting.
"""
import glob
import json
import os
import re

PROJECT_FILES_PATH = "../project_files.json"
APK_GLOB = os.environ.get("APK_GLOB", "android/app/build/outputs/apk/**/*.apk")


def safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^\w\s-]", "", name or "").strip()
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned[:50] or "vengaicode_app"


project_name = "vengaicode_app"
if os.path.exists(PROJECT_FILES_PATH):
    try:
        fetched = json.load(open(PROJECT_FILES_PATH, "r", encoding="utf-8")).get("project_name")
        project_name = fetched or project_name
    except (json.JSONDecodeError, OSError):
        pass

safe_name = safe_filename(project_name)

apks = glob.glob(APK_GLOB, recursive=True)
if not apks:
    print("No APK found to rename")
    raise SystemExit(0)

for apk_path in apks:
    directory = os.path.dirname(apk_path)
    new_path = os.path.join(directory, f"{safe_name}.apk")
    os.rename(apk_path, new_path)
    print(f"Renamed {apk_path} -> {new_path}")
