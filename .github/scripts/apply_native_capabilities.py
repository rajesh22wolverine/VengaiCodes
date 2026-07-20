"""Wire up native-capability Capacitor plugins for an Android build.

Run from the `build/` working directory, after merge_package_json.py and
before `npm install`. Reads the native_capabilities list the backend
detected from the project's own requirements (see detect_native_capabilities
in apps/backend/app/api/v1/codegen.py) out of ../project_files.json.

Writes the ACTUAL Capacitor-backed implementation of each detected
capability's helper module (frontend/src/native/*.js is intentionally never
baked into the AI-generated file set — see the comment on
NATIVE_CAPABILITY_DESCRIPTIONS in codegen.py — because the same generated
project can be packaged for Android, Windows, or Linux independently, and
each platform needs a different implementation behind the same import
path/function names. This script provides the Android one;
apply_tauri_native_capabilities.py provides the Windows/Linux one).

Also adds the matching @capacitor/* plugin dependency, pinned to ^5.0.0 to
match the template's @capacitor/core@^5.7.0 — a v7 plugin (Capacitor's
current major upstream) mixed with a v5 core breaks `npx cap sync`.
"""
import json
import os

PROJECT_FILES_PATH = "../project_files.json"
PACKAGE_JSON_PATH = "package.json"
NATIVE_DIR = "src/native"

PLUGIN_VERSIONS = {
    "camera": ("@capacitor/camera", "^5.0.0"),
    "push_notifications": ("@capacitor/push-notifications", "^5.0.0"),
    "geolocation": ("@capacitor/geolocation", "^5.0.0"),
    "offline_storage": ("@capacitor/preferences", "^5.0.0"),
    "share": ("@capacitor/share", "^5.0.0"),
}

# Same function names/signatures as the Tauri/Windows/Linux implementation
# in apply_tauri_native_capabilities.py — screens import these by name
# without knowing which platform will end up building them.
HELPER_FILES = {
    "camera": (
        "camera.js",
        """import { Camera, CameraResultType, CameraSource } from '@capacitor/camera';

export async function takePhoto() {
  const photo = await Camera.getPhoto({
    resultType: CameraResultType.Uri,
    source: CameraSource.Prompt,
    quality: 80,
  });
  return photo.webPath;
}
""",
    ),
    "push_notifications": (
        "pushNotifications.js",
        """import { PushNotifications } from '@capacitor/push-notifications';

export async function registerPushNotifications() {
  const permission = await PushNotifications.requestPermissions();
  if (permission.receive !== 'granted') {
    return false;
  }
  await PushNotifications.register();
  return true;
}
""",
    ),
    "geolocation": (
        "geolocation.js",
        """import { Geolocation } from '@capacitor/geolocation';

export async function getCurrentPosition() {
  const position = await Geolocation.getCurrentPosition();
  return {
    latitude: position.coords.latitude,
    longitude: position.coords.longitude,
  };
}
""",
    ),
    "offline_storage": (
        "offlineStorage.js",
        """import { Preferences } from '@capacitor/preferences';

export async function getLocal(key) {
  const { value } = await Preferences.get({ key });
  return value ? JSON.parse(value) : null;
}

export async function setLocal(key, value) {
  await Preferences.set({ key, value: JSON.stringify(value) });
}
""",
    ),
    "share": (
        "share.js",
        """import { Share } from '@capacitor/share';

export async function shareContent({ title, text, url }) {
  await Share.share({ title, text, url });
}
""",
    ),
}

with open(PROJECT_FILES_PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

capabilities = data.get("native_capabilities", [])
if not capabilities:
    print("No native capabilities detected for this project — skipping plugin injection")
    raise SystemExit(0)

with open(PACKAGE_JSON_PATH, "r", encoding="utf-8") as f:
    pkg = json.load(f)

deps = pkg.setdefault("dependencies", {})
added_plugins = []
written_files = []

os.makedirs(NATIVE_DIR, exist_ok=True)
for capability in capabilities:
    plugin = PLUGIN_VERSIONS.get(capability)
    if plugin:
        name, version = plugin
        deps[name] = version
        added_plugins.append(name)

    helper = HELPER_FILES.get(capability)
    if helper:
        filename, content = helper
        with open(os.path.join(NATIVE_DIR, filename), "w", encoding="utf-8") as f:
            f.write(content)
        written_files.append(filename)

with open(PACKAGE_JSON_PATH, "w", encoding="utf-8") as f:
    json.dump(pkg, f, indent=2)

print(f"Added native capability plugins: {', '.join(added_plugins) if added_plugins else '(none matched)'}")
print(f"Wrote native helper files: {', '.join(written_files) if written_files else '(none matched)'}")
