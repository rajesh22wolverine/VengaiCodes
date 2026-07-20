# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Shared naming helpers
#  core/naming.py — turn a user-supplied project name into safe
#  filenames (exports, installer downloads) and package identifiers
#  (package.json "name", Tauri/Capacitor app id).
# ═══════════════════════════════════════════════════════════════

import re


def safe_filename(name: str) -> str:
    """Sanitize a project name for use as a filename."""
    cleaned = re.sub(r"[^\w\s-]", "", name or "").strip()
    cleaned = re.sub(r"[\s]+", "_", cleaned)
    return cleaned[:50] or "vengaicode_project"


def slugify_app_name(name: str) -> str:
    """Sanitize a project name into an npm/package-id-safe slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return slug[:100] or "vengaicode-app"
