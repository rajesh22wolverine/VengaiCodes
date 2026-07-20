"""Configure Android release signing if the 4 keystore secrets are present.

Run from the `build/` working directory, after `npx cap add android` (the
step that first generates android/app/build.gradle from Capacitor's own
template — this script only ever writes NEW files plus one idempotent
appended line, it never regex-patches that generated file).

No-ops if the secrets aren't configured — today's assembleDebug fallback
stays untouched. See the "Enabling signed release builds" comment block in
build-android-installer.yml for how to actually generate and set these.
"""
import base64
import os

KEYSTORE_BASE64 = os.environ.get("ANDROID_KEYSTORE_BASE64", "")
KEYSTORE_PASSWORD = os.environ.get("ANDROID_KEYSTORE_PASSWORD", "")
KEY_ALIAS = os.environ.get("ANDROID_KEY_ALIAS", "")
KEY_PASSWORD = os.environ.get("ANDROID_KEY_PASSWORD", "")

if not all([KEYSTORE_BASE64, KEYSTORE_PASSWORD, KEY_ALIAS, KEY_PASSWORD]):
    print("Release signing secrets not fully configured — building an unsigned debug APK instead")
    raise SystemExit(0)

KEYSTORE_PATH = "android/app/release.keystore"
with open(KEYSTORE_PATH, "wb") as f:
    f.write(base64.b64decode(KEYSTORE_BASE64))

# Reopens the `android { buildTypes { release { ... } } }` block Capacitor
# already generated — Groovy DSL's NamedDomainObjectContainer lets a second
# applied file reconfigure an existing named block, so this doesn't need to
# patch build.gradle's contents. Passwords are read via System.getenv() at
# Gradle-build time so no plaintext secret ever touches disk — only the
# decoded keystore binary does. minifyEnabled is forced off defensively:
# R8 shrinking without Capacitor-specific keep rules breaks its
# reflection-based plugin bridge at RUNTIME, not build time, which would be
# a much nastier failure to debug than a one-line safeguard costs.
SIGNING_GRADLE = """android {
    signingConfigs {
        release {
            storeFile file("release.keystore")
            storePassword System.getenv("ANDROID_KEYSTORE_PASSWORD")
            keyAlias System.getenv("ANDROID_KEY_ALIAS")
            keyPassword System.getenv("ANDROID_KEY_PASSWORD")
        }
    }
    buildTypes {
        release {
            signingConfig signingConfigs.release
            minifyEnabled false
        }
    }
}
"""
with open("android/app/signing.gradle", "w", encoding="utf-8") as f:
    f.write(SIGNING_GRADLE)

BUILD_GRADLE_PATH = "android/app/build.gradle"
with open(BUILD_GRADLE_PATH, "r", encoding="utf-8") as f:
    build_gradle = f.read()

apply_line = "apply from: 'signing.gradle'"
if apply_line not in build_gradle:
    with open(BUILD_GRADLE_PATH, "w", encoding="utf-8") as f:
        f.write(build_gradle.rstrip() + "\n\n" + apply_line + "\n")

print("Release signing configured — building a signed release APK")
