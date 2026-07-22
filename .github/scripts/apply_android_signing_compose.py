"""Configure Android release signing for the Jetpack Compose native build,
if the 4 keystore secrets are present.

Run from the `build/` working directory (the Gradle project root itself for
this pipeline — no `android/` subfolder, unlike the Capacitor pipeline's
`apply_android_signing.py`, since jetpack_compose.py's codegen already
emits a complete Gradle project rooted at frontend/, not a template that
gets `cap add android`-ed afterward).

No-ops if the secrets aren't configured — assembleDebug fallback stays
untouched. Same 4 secrets as the Capacitor and Flutter pipelines
(ANDROID_KEYSTORE_BASE64/_PASSWORD, ANDROID_KEY_ALIAS, ANDROID_KEY_PASSWORD)
— one keystore, reusable across all three Android build pipelines.

KOTLIN DSL, NOT GROOVY: app/build.gradle.kts (see jetpack_compose.py's
_app_build_gradle_kts) is a .kts file, so this can't reuse
apply_android_signing.py's Groovy syntax verbatim. Kotlin DSL's
NamedDomainObjectContainer needs `create("release") { }` for a signing
config that doesn't exist by default (unlike `buildTypes`, where "release"
already exists, so that one uses `getByName`), and property assignment
uses `=` instead of Groovy's implicit setter-call style. This is the
standard, documented Android Kotlin DSL signing pattern — not invented —
but wasn't live-verified against a real Gradle run (no Android SDK/Gradle
available in this environment; see jetpack_compose.py's header for the
same caveat about its whole file).
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

KEYSTORE_PATH = "app/release.keystore"
with open(KEYSTORE_PATH, "wb") as f:
    f.write(base64.b64decode(KEYSTORE_BASE64))

# minifyEnabled forced off for the same reason as the Capacitor pipeline:
# R8 shrinking without app-specific keep rules can break reflection-based
# code (JSON parsing, coroutines) at RUNTIME rather than build time.
SIGNING_GRADLE_KTS = """android {
    signingConfigs {
        create("release") {
            storeFile = file("release.keystore")
            storePassword = System.getenv("ANDROID_KEYSTORE_PASSWORD")
            keyAlias = System.getenv("ANDROID_KEY_ALIAS")
            keyPassword = System.getenv("ANDROID_KEY_PASSWORD")
        }
    }
    buildTypes {
        getByName("release") {
            signingConfig = signingConfigs.getByName("release")
            isMinifyEnabled = false
        }
    }
}
"""
with open("app/signing.gradle.kts", "w", encoding="utf-8") as f:
    f.write(SIGNING_GRADLE_KTS)

BUILD_GRADLE_PATH = "app/build.gradle.kts"
with open(BUILD_GRADLE_PATH, "r", encoding="utf-8") as f:
    build_gradle = f.read()

apply_line = 'apply(from = "signing.gradle.kts")'
if apply_line not in build_gradle:
    with open(BUILD_GRADLE_PATH, "w", encoding="utf-8") as f:
        f.write(build_gradle.rstrip() + "\n\n" + apply_line + "\n")

print("Release signing configured — building a signed release APK")
