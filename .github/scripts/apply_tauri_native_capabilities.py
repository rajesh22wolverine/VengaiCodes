"""Wire up native capabilities for a Tauri v1 build (Windows and Linux share
this script — both templates use the same allowlist/Cargo-feature model).

Run from the `build/` working directory, after update_tauri_config.py and
before `npm install`. Reads the native_capabilities list the backend
detected from the project's own requirements out of ../project_files.json.

Writes a Tauri/browser-API-backed implementation of each detected
capability's helper module under src/native/*.js, using the SAME function
names/signatures as the Capacitor-backed Android implementation in
apply_native_capabilities.py — see the comment on
NATIVE_CAPABILITY_DESCRIPTIONS in codegen.py for why. Camera and geolocation
need no Tauri-side changes at all (WebView2/WebKitGTK expose the standard
browser getUserMedia/Geolocation APIs directly); push notifications,
offline storage, and share need a matching tauri.conf.json allowlist entry
plus Cargo.toml feature flag, patched in below.

HONEST LIMITATION: Tauri v1 has no remote push (FCM/APNs-style) concept at
all, so "push_notifications" here means LOCAL OS notifications only, not
server-triggered alerts. And Windows/Linux have no native OS share sheet
exposed by Tauri v1 — "share" falls back to copying to the clipboard, the
closest real desktop equivalent.
"""
import json
import os
import re

PROJECT_FILES_PATH = "../project_files.json"
NATIVE_DIR = "src/native"
TAURI_CONF_PATH = "src-tauri/tauri.conf.json"
CARGO_TOML_PATH = "src-tauri/Cargo.toml"

# capability -> list of (allowlist key, allowlist value, cargo feature) —
# None/empty means no Tauri-side config change needed (pure browser API). A
# list (not a single tuple) because "filesystem" below needs BOTH a "dialog"
# and an "fs" entry, and because two capabilities can both touch the same
# allowlist key ("fs", shared with offline_storage) — see the merge in the
# main loop below, which unions rather than overwrites.
CAPABILITY_TAURI_CONFIG = {
    "camera": [],
    "geolocation": [],
    "push_notifications": [("notification", {"all": True}, "notification-all")],
    "offline_storage": [("fs", {"all": True, "scope": ["$APPDATA/*", "$APPDATA/**"]}, "fs-all")],
    "share": [("clipboard", {"all": True}, "clipboard-all")],
    # Arbitrary user-chosen folders (a music library import, a local log
    # viewer, ...) live anywhere on disk, not under a fixed app-owned
    # directory like offline_storage's $APPDATA — so the fs scope has to be
    # wide open rather than anchored to a path variable. "dialog-open" is
    # the native OS folder picker; without it there is no way for the
    # generated app to ask the user for a path at all on desktop.
    # "path" (audioDir/documentDir/etc.) resolves the OS-standard media
    # folders scanDevice() checks on the system drive — see HELPER_FILES
    # below.
    "filesystem": [
        ("dialog", {"open": True}, "dialog-open"),
        ("fs", {"all": True, "scope": ["**"]}, "fs-all"),
        ("path", {"all": True}, "path-all"),
    ],
}

# Same function names/signatures as the Capacitor implementation in
# apply_native_capabilities.py — screens import these by name without
# knowing which platform will end up building them.
HELPER_FILES = {
    "camera": (
        "camera.js",
        """// Desktop cameras are accessed via the standard browser getUserMedia API —
// WebView2 (Windows) / WebKitGTK (Linux) expose this directly, no
// Tauri-specific allowlist or Cargo feature needed.
export async function takePhoto() {
  const stream = await navigator.mediaDevices.getUserMedia({ video: true });
  const video = document.createElement('video');
  video.srcObject = stream;
  await video.play();
  await new Promise((resolve) => { video.onloadeddata = resolve; });

  const canvas = document.createElement('canvas');
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  canvas.getContext('2d').drawImage(video, 0, 0);

  stream.getTracks().forEach((track) => track.stop());
  return canvas.toDataURL('image/png');
}
""",
    ),
    "geolocation": (
        "geolocation.js",
        """// Desktop geolocation is the standard browser Geolocation API, backed by
// the OS's own location services — no Tauri-specific wiring needed.
export function getCurrentPosition() {
  return new Promise((resolve, reject) => {
    navigator.geolocation.getCurrentPosition(
      (position) => resolve({
        latitude: position.coords.latitude,
        longitude: position.coords.longitude,
      }),
      (error) => reject(error)
    );
  });
}
""",
    ),
    "push_notifications": (
        "pushNotifications.js",
        """// Desktop "push notifications" are local OS toast notifications only —
// Tauri v1 has no remote push (FCM/APNs-style) support. Requires the
// "notification" allowlist entry + "notification-all" Cargo feature.
import { isPermissionGranted, requestPermission } from '@tauri-apps/api/notification';

export async function registerPushNotifications() {
  let granted = await isPermissionGranted();
  if (!granted) {
    const permission = await requestPermission();
    granted = permission === 'granted';
  }
  return granted;
}
""",
    ),
    "offline_storage": (
        "offlineStorage.js",
        """// Persists to a JSON file in the app's data directory via Tauri's fs API —
// requires the "fs" allowlist entry + "fs-all" Cargo feature.
import { readTextFile, writeTextFile, createDir, exists, BaseDirectory } from '@tauri-apps/api/fs';

const STORE_FILE = 'vengaicode-store.json';

async function readStore() {
  const fileExists = await exists(STORE_FILE, { dir: BaseDirectory.AppData });
  if (!fileExists) return {};
  const contents = await readTextFile(STORE_FILE, { dir: BaseDirectory.AppData });
  return JSON.parse(contents);
}

export async function getLocal(key) {
  const store = await readStore();
  return store[key] ?? null;
}

export async function setLocal(key, value) {
  await createDir('', { dir: BaseDirectory.AppData, recursive: true });
  const store = await readStore();
  store[key] = value;
  await writeTextFile(STORE_FILE, JSON.stringify(store), { dir: BaseDirectory.AppData });
}
""",
    ),
    "share": (
        "share.js",
        """// Windows/Linux have no native OS share sheet exposed by Tauri v1 — the
// closest real desktop equivalent is copying to the clipboard. Requires
// the "clipboard" allowlist entry + "clipboard-all" Cargo feature.
import { writeText } from '@tauri-apps/api/clipboard';

export async function shareContent({ title, text, url }) {
  const parts = [title, text, url].filter(Boolean);
  await writeText(parts.join('\\n'));
  return true;
}
""",
    ),
    "filesystem": (
        "filesystem.js",
        """// Desktop builds ship the frontend only (see inject_frontend_files.py —
// nothing under backend/ survives packaging), so scanning either a
// user-chosen folder or the whole device has to happen entirely through
// Tauri's own dialog + fs + path APIs, not a backend call. Requires the
// "dialog" + "fs" + "path" allowlist entries and the "dialog-open" +
// "fs-all" + "path-all" Cargo features.
import { open } from '@tauri-apps/api/dialog';
import { exists, readDir } from '@tauri-apps/api/fs';
import { audioDir, documentDir, downloadDir, pictureDir, videoDir, homeDir } from '@tauri-apps/api/path';

export async function pickFolder() {
  const selected = await open({ directory: true, multiple: false });
  return selected ?? null;
}

async function listFilesAt(folderPath, extensions) {
  const wanted = extensions.map((ext) => ext.toLowerCase());
  const matches = (name) =>
    !wanted.length || wanted.some((ext) => name?.toLowerCase().endsWith(ext));

  const files = [];
  const walk = (entries) => {
    for (const entry of entries) {
      if (entry.children) {
        walk(entry.children);
      } else if (matches(entry.name)) {
        files.push({ name: entry.name, path: entry.path });
      }
    }
  };
  walk(await readDir(folderPath, { recursive: true }));
  return files;
}

export async function listFiles(folderPath, extensions = []) {
  return listFilesAt(folderPath, extensions);
}

// Scans every OS-standard media folder on the system drive, PLUS the
// same-named folders on every other drive/mount it finds — NOT a full
// recursive walk of every directory on every drive. That would take
// minutes to hours on a real disk and hit permission-denied errors
// constantly on system folders (C:\\Windows, C:\\Program Files, /proc,
// /sys) — this is deliberately scoped the way real desktop media apps
// (iTunes, Windows Media Player) scope a "scan my computer" feature,
// not an exhaustive filesystem crawl.
//
// The drive-letter and /media,/mnt checks below are unconditional on
// both platforms rather than OS-detected: on Linux, "D:\\" etc. simply
// never exists() and the checks no-op; on Windows, /media and /mnt
// simply fail to readDir() and get caught below. That is simpler and
// more robust than trying to sniff the OS first.
export async function scanDevice(extensions = []) {
  const roots = new Set();

  for (const dirFn of [audioDir, documentDir, downloadDir, videoDir, pictureDir, homeDir]) {
    try {
      roots.add(await dirFn());
    } catch {
      // not resolvable on this OS/config — skip
    }
  }

  // Other Windows drives — same-named media folders only, never the
  // drive root itself (that would reintroduce the exhaustive-scan
  // problem this function exists to avoid).
  for (const letter of 'CDEFGHIJKLMNOPQRSTUVWXYZ') {
    const drive = `${letter}:\\\\`;
    let driveExists = false;
    try {
      driveExists = await exists(drive);
    } catch {
      driveExists = false;
    }
    if (!driveExists) continue;
    for (const folder of ['Music', 'Videos', 'Documents', 'Downloads', 'Pictures']) {
      const candidate = `${drive}${folder}`;
      try {
        if (await exists(candidate)) roots.add(candidate);
      } catch {
        // inaccessible — skip
      }
    }
  }

  // Linux externally-mounted volumes commonly show up as one level of
  // subdirectories under /media/<user> or /mnt — add each mount point
  // found there as its own root (scanned recursively below), rather
  // than assuming a media-folder naming convention that removable
  // drives rarely follow.
  for (const base of ['/media', '/mnt']) {
    try {
      const entries = await readDir(base, { recursive: false });
      for (const entry of entries) {
        if (entry.path) roots.add(entry.path);
        if (entry.children) {
          for (const nested of entry.children) {
            if (nested.path) roots.add(nested.path);
          }
        }
      }
    } catch {
      // not present on this OS — skip
    }
  }

  const seenPaths = new Set();
  const allFiles = [];
  for (const root of roots) {
    let rootExists = false;
    try {
      rootExists = await exists(root);
    } catch {
      rootExists = false;
    }
    if (!rootExists) continue;

    try {
      for (const file of await listFilesAt(root, extensions)) {
        if (!seenPaths.has(file.path)) {
          seenPaths.add(file.path);
          allFiles.push(file);
        }
      }
    } catch {
      // permission denied or transient — skip this root, keep going
    }
  }
  return allFiles;
}
""",
    ),
}


def patch_tauri_conf(needed_allowlist: dict) -> None:
    if not needed_allowlist or not os.path.exists(TAURI_CONF_PATH):
        return
    with open(TAURI_CONF_PATH, "r", encoding="utf-8") as f:
        conf = json.load(f)
    allowlist = conf.setdefault("tauri", {}).setdefault("allowlist", {})
    allowlist.update(needed_allowlist)
    with open(TAURI_CONF_PATH, "w", encoding="utf-8") as f:
        json.dump(conf, f, indent=2)


def patch_cargo_toml(needed_features: list) -> None:
    if not needed_features or not os.path.exists(CARGO_TOML_PATH):
        return
    with open(CARGO_TOML_PATH, "r", encoding="utf-8") as f:
        cargo_toml = f.read()

    pattern = re.compile(r'(tauri = \{ version = "1\.5", features = \[)([^\]]*)(\]\s*\})')
    match = pattern.search(cargo_toml)
    if not match:
        print(f"WARNING: could not find the tauri dependency line in {CARGO_TOML_PATH} — skipping feature patch")
        return

    existing = [feat.strip().strip('"') for feat in match.group(2).split(",") if feat.strip()]
    merged = existing + [feat for feat in needed_features if feat not in existing]
    features_str = ", ".join(f'"{feat}"' for feat in merged)
    new_line = f"{match.group(1)}{features_str}{match.group(3)}"
    cargo_toml = cargo_toml[: match.start()] + new_line + cargo_toml[match.end() :]

    with open(CARGO_TOML_PATH, "w", encoding="utf-8") as f:
        f.write(cargo_toml)


with open(PROJECT_FILES_PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

capabilities = data.get("native_capabilities", [])
if not capabilities:
    print("No native capabilities detected for this project — skipping Tauri capability wiring")
    raise SystemExit(0)

os.makedirs(NATIVE_DIR, exist_ok=True)
written_files = []
needed_allowlist = {}
needed_features = []

for capability in capabilities:
    helper = HELPER_FILES.get(capability)
    if helper:
        filename, content = helper
        with open(os.path.join(NATIVE_DIR, filename), "w", encoding="utf-8") as f:
            f.write(content)
        written_files.append(filename)

    for allowlist_key, allowlist_value, cargo_feature in CAPABILITY_TAURI_CONFIG.get(capability) or []:
        existing = needed_allowlist.get(allowlist_key)
        if isinstance(existing, dict) and isinstance(allowlist_value, dict):
            # Two capabilities sharing an allowlist key (e.g. "fs" for both
            # offline_storage and filesystem) must union, not overwrite —
            # otherwise whichever capability is processed last silently
            # drops the other's scope/flags.
            merged = {**existing, **allowlist_value}
            if isinstance(existing.get("scope"), list) and isinstance(allowlist_value.get("scope"), list):
                merged["scope"] = sorted(set(existing["scope"]) | set(allowlist_value["scope"]))
            needed_allowlist[allowlist_key] = merged
        else:
            needed_allowlist[allowlist_key] = allowlist_value
        if cargo_feature not in needed_features:
            needed_features.append(cargo_feature)

patch_tauri_conf(needed_allowlist)
patch_cargo_toml(needed_features)

print(f"Wrote native helper files: {', '.join(written_files) if written_files else '(none matched)'}")
print(f"Tauri allowlist entries added: {', '.join(needed_allowlist.keys()) if needed_allowlist else '(none)'}")
print(f"Cargo features added: {', '.join(needed_features) if needed_features else '(none)'}")
