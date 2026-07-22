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
from typing import Callable

from pydantic import BaseModel

from app.ai.orchestrator import generate_text
from app.core.naming import slugify_app_name

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
# are unlocked as their adapters land.
_BRACE_HEURISTIC_LANGUAGES = {
    "javascript", "typescript", "csharp", "rust", "go", "kotlin", "swift", "dart", "php",
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


async def generate_text_validated(prompt: str, language: str, max_tokens: int) -> tuple[str, str | None]:
    """Call generate_text(), validate the result, and retry once with the
    specific problem appended to the prompt if validation fails."""
    result = await generate_text(prompt, max_tokens=max_tokens)
    content = strip_code_fences(result["text"])
    issue = validate_generated_content(language, content)

    if issue:
        retry_prompt = (
            f"{prompt}\n\nYour previous attempt was rejected: {issue}. "
            f"Return the corrected, COMPLETE file only — no truncation, "
            f"no markdown fences, no explanation."
        )
        result = await generate_text(retry_prompt, max_tokens=max_tokens)
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
