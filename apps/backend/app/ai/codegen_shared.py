# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Shared Code Generation Helpers
#  ai/codegen_shared.py — File/text helpers, content validation, and
#  native-capability detection shared by the codegen adapter registry
#  (app/ai/codegen/frontend/*, app/ai/codegen/backend/*) and by
#  api/v1/testing.py. Lives under app/ai/ (not app/api/v1/) specifically
#  so the per-framework adapter modules can import it without creating
#  an app.api.v1.codegen <-> app.ai.codegen circular import.
# ═══════════════════════════════════════════════════════════════

import ast
import json
import logging
import re
from typing import Callable, Optional

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.orchestrator import generate_text
from app.core.naming import slugify_app_name
from app.models.user import User

logger = logging.getLogger("vengaicode.codegen")

# One big JSON call asking for every file used to mean each file's
# share of the output budget shrank as the app grew, which is why
# generated projects always looked like a thin skeleton. Every model,
# route, and screen file gets its OWN AI call and its own full token
# budget, so a 3-screen app and a 15-screen app both get fully-
# implemented files instead of the second one getting starved.
GROQ_FILE_MAX_TOKENS = 6000
GROQ_WIRING_MAX_TOKENS = 4000


class GeneratedFile(BaseModel):
    path: str
    language: str
    content: str
    description: str


def _slug(name: str) -> str:
    """Turn a table/screen display name into a safe snake_case identifier."""
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", name or "item").strip("_").lower()
    return cleaned or "item"


def _pascal(name: str) -> str:
    return "".join(word.capitalize() for word in re.split(r"[^a-zA-Z0-9]+", name) if word) or "Item"


# Android/Java package segments can't start with a digit or be a reserved
# word (e.g. project "3D Notes" -> "3dnotes" is an invalid applicationId;
# "Class Tracker" -> "class" collides with the keyword). Shared by every
# adapter that emits a real Android applicationId/package (Jetpack Compose,
# Godot's package/unique_name) — mirrors the same list the Capacitor CI
# script (.github/scripts/update_capacitor_config.py) keeps independently,
# since that one runs as a standalone CI script with no import access to
# this module.
JAVA_RESERVED_WORDS = {
    "abstract", "assert", "boolean", "break", "byte", "case", "catch", "char",
    "class", "const", "continue", "default", "do", "double", "else", "enum",
    "extends", "final", "finally", "float", "for", "goto", "if", "implements",
    "import", "instanceof", "int", "interface", "long", "native", "new",
    "package", "private", "protected", "public", "return", "short", "static",
    "strictfp", "super", "switch", "synchronized", "this", "throw", "throws",
    "transient", "try", "void", "volatile", "while", "true", "false", "null",
}


def android_package_segment(name: str) -> str:
    """A single package-path segment safe to use in an Android applicationId."""
    slug = re.sub(r"[^a-z0-9]", "", (name or "").lower())
    if not slug:
        return "generatedapp"
    if slug[0].isdigit() or slug in JAVA_RESERVED_WORDS:
        return f"app{slug}"
    return slug


def strip_code_fences(text: str) -> str:
    """Extract raw code from an AI response that may be wrapped in markdown fences."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned


def parse_ai_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    cleaned = cleaned.strip()
    return json.loads(cleaned)


def apply_package_json_name(files: list[dict], project_name: str) -> None:
    """
    Force frontend/package.json's "name" field to match the project's
    name, regardless of what the AI picked. This is what
    merge_package_json.py later reads to set the Tauri/Capacitor
    productName and bundle id, so it has to be reliable rather than
    just prompted for.
    """
    slug = slugify_app_name(project_name)
    for f in files:
        if f.get("path") == "frontend/package.json":
            try:
                pkg = json.loads(f["content"])
            except (json.JSONDecodeError, TypeError):
                logger.warning("Could not parse AI-generated package.json to patch its name")
                return
            pkg["name"] = slug
            f["content"] = json.dumps(pkg, indent=2)
            return


# ─── Pre-packaging validation ───
#
# HONEST STATUS: Python files get a real syntax check via ast.parse().
# Most other languages don't — there's no reliable zero-install real
# parser available server-side for them, so they get a cheap heuristic
# (balanced delimiters catches truncated output from hitting the token
# cap; a placeholder scan catches the AI ignoring "no placeholders/
# TODOs"). It will not catch every broken file, but it catches the
# failure modes actually seen from single-shot LLM generation. New
# per-language tiers get added here as each adapter that emits that
# language lands (see VALIDATORS below) rather than all at once.
def _validate_python(content: str) -> str | None:
    try:
        ast.parse(content)
    except SyntaxError as e:
        return f"invalid Python syntax: {e}"
    return None


def _validate_brace_heuristic(content: str) -> str | None:
    opens = sum(content.count(c) for c in "{([")
    closes = sum(content.count(c) for c in "})]")
    if opens != closes:
        return f"unbalanced braces/brackets ({opens} open vs {closes} close — likely truncated)"
    if "TODO" in content or "```" in content:
        return "contains leftover TODO markers or markdown code fences"
    return None


# Curly-brace languages the balanced-delimiter heuristic transfers to
# directly. "javascript" is the original, already-shipped case; the rest
# are unlocked as their adapters land. "lua" doesn't use braces for
# control flow (if/then/end), but its Properties table syntax does use
# {}, so the heuristic still catches truncated-output failures there —
# listed explicitly rather than relying on VALIDATORS.get()'s fallback,
# so it reads as a reviewed decision, not an accident.
_BRACE_HEURISTIC_LANGUAGES = {
    "javascript", "typescript", "csharp", "rust", "go", "kotlin", "swift", "dart", "php", "lua",
}

VALIDATORS: dict[str, Callable[[str], str | None]] = {
    "python": _validate_python,
    **{lang: _validate_brace_heuristic for lang in _BRACE_HEURISTIC_LANGUAGES},
}


def validate_generated_content(language: str, content: str) -> str | None:
    """Returns a problem description, or None if the file looks OK."""
    if not content.strip():
        return "empty response"
    return VALIDATORS.get(language, _validate_brace_heuristic)(content)


async def generate_text_validated(
    prompt: str,
    language: str,
    max_tokens: int,
    user: Optional[User] = None,
    db: Optional[AsyncSession] = None,
) -> tuple[str, str | None]:
    """Call generate_text(), validate the result, and retry once with the
    specific problem appended to the prompt if validation fails.

    user/db are threaded straight through to generate_text() so a caller's
    BYO/portable AI config (Settings -> AI Model) is honored here too —
    every codegen adapter calls this instead of generate_text() directly.
    """
    result = await generate_text(prompt, max_tokens=max_tokens, user=user, db=db)
    content = strip_code_fences(result["text"])
    issue = validate_generated_content(language, content)

    if issue:
        retry_prompt = (
            f"{prompt}\n\nYour previous attempt was rejected: {issue}. "
            f"Return the corrected, COMPLETE file only — no truncation, "
            f"no markdown fences, no explanation."
        )
        result = await generate_text(retry_prompt, max_tokens=max_tokens, user=user, db=db)
        content = strip_code_fences(result["text"])
        issue = validate_generated_content(language, content)

    return content, issue


# ─── Native device capabilities, detected from the app's own requirements ───
#
# Keyword-matched against key_features + user_stories text (the same
# requirements_text already assembled for every codegen prompt). Only
# capabilities actually implied by the app get wired in — this is what makes
# the generated APK reflect what THIS user asked for instead of shipping a
# fixed generic plugin set to every project.
NATIVE_CAPABILITY_KEYWORDS: dict[str, list[str]] = {
    "camera": ["camera", "photo", "take a picture", "scan a", "upload an image"],
    "push_notifications": ["push notification", "notify user", "alert user when", "send a notification"],
    "geolocation": ["location", "gps", "map", "nearby", "distance from", "current position"],
    "offline_storage": ["offline", "without internet", "local storage", "works without", "sync later"],
    "share": ["share to", "share this", "share with", "social share", "invite a friend"],
}

# Interface only — the actual per-capability implementation (Capacitor on
# Android, browser APIs + Tauri allowlist APIs on Windows/Linux) is written
# at PACKAGING time by each platform's CI script (apply_native_capabilities.py
# for Android, apply_tauri_native_capabilities.py for Windows/Linux), not
# here. Every implementation exports the same function names/signatures
# described below, so the same AI-generated screen works unmodified no
# matter which platform ends up building the project — codegen only runs
# ONCE per project, but a user can trigger Android/Windows/Linux builds
# independently afterward, so this file must never bake in a
# platform-specific package import.
NATIVE_CAPABILITY_DESCRIPTIONS: dict[str, str] = {
    "camera": "Camera: import { takePhoto } from '../native/camera'; await takePhoto() returns a photo URI to display or upload — use this for any photo/image capture user story instead of a browser file input.",
    "push_notifications": "Push notifications: import { registerPushNotifications } from '../native/pushNotifications'; call it once (e.g. on mount) to register the device for push alerts.",
    "geolocation": "Geolocation: import { getCurrentPosition } from '../native/geolocation'; await getCurrentPosition() returns { latitude, longitude } — use this for any location/nearby/distance user story.",
    "offline_storage": "Offline storage: import { getLocal, setLocal } from '../native/offlineStorage'; use these to persist data locally so the screen still works without a network connection.",
    "share": "Share: import { shareContent } from '../native/share'; await shareContent({ title, text, url }) shares/copies the content — use this for any 'share to' / 'invite a friend' user story.",
}


def detect_native_capabilities(text: str) -> list[str]:
    lowered = text.lower()
    return [
        capability
        for capability, keywords in NATIVE_CAPABILITY_KEYWORDS.items()
        if any(keyword in lowered for keyword in keywords)
    ]


# ─── Unified, ordered page list (wizard screens + uploaded designs) ───
#
# api/v1/uiux.py stores two historically separate things on Project.uiux_data:
# design.screens[] (AI-generated from the wizard) and uploaded_designs[] (the
# user's own mockups). Both can now carry a real generated_html/generated_css/
# modules mockup. architecture.py and codegen.py both need the SAME merged,
# ordered view of "every page this app has" — this is that single source of
# truth, so the two phases can never disagree on the page set or its order.
def get_ordered_pages(uiux_data: Optional[dict]) -> list[dict]:
    """
    Merge design.screens and uploaded_designs into one list of page dicts
    shaped like a codegen `screen` (name, purpose, key_elements), plus
    reference_html/reference_css/modules populated from whichever saved
    mockup that page has. Ordered by design.page_order (set by the UI/UX
    editor's bulk /save endpoint) when present; otherwise screens-then-
    uploads in their stored order, i.e. exactly what every project already
    did before this field existed.
    """
    if not uiux_data:
        return []
    design = uiux_data.get("design", {}) or {}
    screens = design.get("screens", []) or []
    uploads = uiux_data.get("uploaded_designs", []) or []

    pages_by_id: dict[str, dict] = {}
    natural_order: list[str] = []

    for i, screen in enumerate(screens):
        page_id = screen.get("id") or f"screen-{i}"
        pages_by_id[page_id] = {
            "name": screen.get("name", ""),
            "purpose": screen.get("purpose", ""),
            "key_elements": screen.get("key_elements", []),
            "reference_html": screen.get("generated_html"),
            "reference_css": screen.get("generated_css"),
            "modules": screen.get("modules", []),
        }
        natural_order.append(page_id)

    for i, upload in enumerate(uploads):
        page_id = upload.get("id") or f"upload-{i}"
        pages_by_id[page_id] = {
            "name": upload.get("page_name", ""),
            "purpose": "",
            "key_elements": [],
            "reference_html": upload.get("generated_html"),
            "reference_css": upload.get("generated_css"),
            "modules": upload.get("modules", []),
        }
        natural_order.append(page_id)

    page_order = design.get("page_order") or []
    ordered_ids = [pid for pid in page_order if pid in pages_by_id]
    ordered_ids += [pid for pid in natural_order if pid not in ordered_ids]

    return [pages_by_id[pid] for pid in ordered_ids]


def build_reference_design_block(screen: dict) -> str:
    """
    If this page has a saved HTML/CSS mockup (auto-generated for a wizard
    screen, vision-converted from a user upload, or hand-edited afterward in
    the UI/UX visual editor), return a prompt block asking a markup-based
    frontend adapter (React/Vue/Angular/Svelte/plain HTML-JS) to recreate it
    faithfully instead of inventing a layout from scratch. Returns "" when
    there's nothing saved yet, so every adapter can unconditionally append
    this to its prompt without its own presence check.
    """
    html = (screen.get("reference_html") or "").strip()
    if not html:
        return ""
    css = (screen.get("reference_css") or "").strip()
    return f"""

The user has already designed and approved this exact page mockup — recreate
its structure, layout order, colors, and copy AS FAITHFULLY AS POSSIBLE using
this framework's idioms. Do not invent a different layout. Only add real
interactivity (state, event handlers, API wiring) on top of this structure.

Reference HTML:
```html
{html}
```

Reference CSS:
```css
{css}
```
"""


def build_design_guidance_block(
    design_style: Optional[str],
    color_palette: Optional[dict],
    typography: Optional[str],
    modules: Optional[list],
) -> str:
    """
    For native UI toolkits and game engines (SwiftUI, Flutter, Jetpack
    Compose, Godot, O3DE) a saved page's raw HTML/CSS can't be reused
    directly the way it can for a markup-based web frontend — but the
    app's design system (style/palette/typography) and, when this specific
    page has a saved mockup, its structural section list, both still carry
    real signal. Returns "" when there's nothing to say, so every adapter
    can unconditionally append this to its prompt.
    """
    lines = []
    if design_style:
        lines.append(f"- Visual style: {design_style}")
    if color_palette:
        palette_text = ", ".join(f"{k}: {v}" for k, v in color_palette.items())
        lines.append(f"- Color palette: {palette_text}")
    if typography:
        lines.append(f"- Typography: {typography}")
    if modules:
        lines.append(f"- This screen's structural sections, top to bottom: {', '.join(modules)}")
    if not lines:
        return ""
    return "\nMatch the app's design system:\n" + "\n".join(lines) + "\n"
