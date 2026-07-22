"""Configure Android release signing for the Flutter build, if the 4
keystore secrets are present.

Run from `build/` (the `flutter create`-scaffolded project root), after
`flutter create` has generated android/app/build.gradle(.kts) — this
script only ever writes NEW files plus one idempotent appended line, same
non-regex-patching approach as apply_android_signing.py (Capacitor) and
apply_android_signing_compose.py (Jetpack Compose). Same 4 secrets as
those two pipelines — one keystore, reusable across all three.

Detects whether Flutter scaffolded a Groovy (build.gradle) or Kotlin DSL
(build.gradle.kts) app-module build file rather than assuming one —
Flutter's own default has changed across versions and no Flutter SDK is
available in this dev environment to pin down which the CI runner's
installed version will produce.

No-ops if the secrets aren't configured — Flutter's own scaffold already
signs debug builds with its bundled debug keystore, so `flutter build apk`
(debug) works with zero configuration either way.
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

_KTS_PATH = "android/app/build.gradle.kts"
_GROOVY_PATH = "android/app/build.gradle"

# minifyEnabled/isMinifyEnabled forced off for the same reason as the other
# two pipelines: R8 shrinking without app-specific keep rules can break
# reflection-based code (JSON parsing, plugin bridges) at RUNTIME rather
# than build time.
if os.path.exists(_KTS_PATH):
    build_gradle_path = _KTS_PATH
    signing_path = "android/app/signing.gradle.kts"
    apply_line = 'apply(from = "signing.gradle.kts")'
    signing_content = """android {
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
elif os.path.exists(_GROOVY_PATH):
    build_gradle_path = _GROOVY_PATH
    signing_path = "android/app/signing.gradle"
    apply_line = "apply from: 'signing.gradle'"
    signing_content = """android {
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
else:
    print(f"Neither {_GROOVY_PATH} nor {_KTS_PATH} found — did `flutter create` run first? Skipping signing.")
    raise SystemExit(0)

with open(signing_path, "w", encoding="utf-8") as f:
    f.write(signing_content)

with open(build_gradle_path, "r", encoding="utf-8") as f:
    build_gradle = f.read()

if apply_line not in build_gradle:
    with open(build_gradle_path, "w", encoding="utf-8") as f:
        f.write(build_gradle.rstrip() + "\n\n" + apply_line + "\n")

print(f"Release signing configured ({build_gradle_path}) — building a signed release APK")
