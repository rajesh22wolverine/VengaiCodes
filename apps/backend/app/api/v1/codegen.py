# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Code Generation API Routes (Sprint 6, updated)
#  api/v1/codegen.py — Generate a REAL, working implementation from
#  approved architecture — one dedicated AI call per model/route/
#  screen file (each gets its own full token budget instead of many
#  files sharing one small JSON response), then a final wiring pass
#  (main.py, App.jsx, package.json, etc.) that stitches them into an
#  installable, startable project.
# ═══════════════════════════════════════════════════════════════

import ast
import json
import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.orchestrator import AIError, generate_text
from app.api.v1.auth import get_current_active_user
from app.core.database import get_db
from app.core.naming import slugify_app_name
from app.models.project import Project, SDLCPhase
from app.models.user import User

logger = logging.getLogger("vengaicode.codegen")
router = APIRouter()


# ─── Schemas ───
class GenerateCodeRequest(BaseModel):
    project_id: str


class GeneratedFile(BaseModel):
    path: str
    language: str
    content: str
    description: str


class CodeGenResult(BaseModel):
    summary: str
    files: list[GeneratedFile]


class GenerateCodeResponse(BaseModel):
    success: bool = True
    codegen: CodeGenResult


class ApproveCodeRequest(BaseModel):
    project_id: str
    approved: bool = True


# ─── Constants ───
#
# One big JSON call asking for every file used to mean each file's
# share of the output budget shrank as the app grew, which is why
# generated projects always looked like a thin skeleton. Every model,
# route, and screen file below now gets its OWN AI call and its own
# full token budget, so a 3-screen app and a 15-screen app both get
# fully-implemented files instead of the second one getting starved.
GROQ_FILE_MAX_TOKENS = 6000
GROQ_WIRING_MAX_TOKENS = 4000


def _requirements_context(requirements: dict) -> str:
    frd = requirements.get("frd", {}) if requirements else {}
    if not frd:
        return ""

    features = frd.get("key_features", [])
    stories = frd.get("user_stories", [])
    features_text = "\n".join(f"- {f}" for f in features)
    stories_text = "\n".join(f"- {s}" for s in stories)

    return f"""
Problem this app solves: {frd.get('problem_statement', '')}
Target users: {frd.get('target_users', '')}

Key features (implement the REAL logic for each of these — not a stub):
{features_text}

User stories (the code must actually satisfy these, not just render placeholder UI):
{stories_text}
"""


def _slug(name: str) -> str:
    """Turn a table/screen display name into a safe snake_case identifier."""
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", name or "item").strip("_").lower()
    return cleaned or "item"


def _pascal(name: str) -> str:
    return "".join(word.capitalize() for word in re.split(r"[^a-zA-Z0-9]+", name) if word) or "Item"


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
# HONEST STATUS: Python files get a real syntax check via ast.parse(). JS/JSX
# files don't — there's no JSX-aware parser available server-side without
# adding a Node dependency, so this is a cheap heuristic (balanced delimiters
# catches truncated output from hitting the token cap; a placeholder scan
# catches the AI ignoring "no placeholders/TODOs"). It will not catch every
# broken JS file, but it catches the failure modes actually seen from
# single-shot LLM generation.
def validate_generated_content(language: str, content: str) -> str | None:
    """Returns a problem description, or None if the file looks OK."""
    if not content.strip():
        return "empty response"

    if language == "python":
        try:
            ast.parse(content)
        except SyntaxError as e:
            return f"invalid Python syntax: {e}"
        return None

    if language == "javascript":
        opens = sum(content.count(c) for c in "{([")
        closes = sum(content.count(c) for c in "})]")
        if opens != closes:
            return f"unbalanced braces/brackets ({opens} open vs {closes} close — likely truncated)"
        if "TODO" in content or "```" in content:
            return "contains leftover TODO markers or markdown code fences"
        return None

    return None


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


# ─── Per-file generation (models, routes, screens) ───
async def generate_model_file(project_name: str, table: dict, requirements_text: str) -> tuple[GeneratedFile, str | None]:
    table_name = table.get("name", "Item")
    prompt = f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Write ONE complete, real SQLAlchemy model file for the "{table_name}" table of this app.

App: {project_name}
{requirements_text}
Table purpose: {table.get('purpose', '')}
Fields: {', '.join(table.get('key_fields', []))}

Requirements:
- Real column types, constraints (nullable, unique, defaults) matching the fields above.
- Implement any validation, computed properties, or relationships implied by the key
  features / user stories above — not a bare column list.
- Use SQLAlchemy declarative style importing Base from "app.core.database".
- No placeholders or TODOs — every field and method must be fully implemented.

Return ONLY the raw Python code for this one file. No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(prompt, "python", GROQ_FILE_MAX_TOKENS)
    return GeneratedFile(
        path=f"backend/models/{_slug(table_name)}.py",
        language="python",
        content=content,
        description=f"SQLAlchemy model for {table_name}",
    ), issue


async def generate_routes_file(project_name: str, endpoints: list, tables: list, requirements_text: str) -> tuple[GeneratedFile, str | None]:
    endpoints_text = "\n".join(
        f"- {e.get('method')} {e.get('path')}: {e.get('purpose')}" for e in endpoints
    )
    model_imports = "\n".join(
        f"- backend/models/{_slug(t.get('name', 'item'))}.py defines the {t.get('name')} model"
        for t in tables
    )

    prompt = f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Write ONE complete, real FastAPI routes file implementing every API endpoint below for this app.

App: {project_name}
{requirements_text}
Available models to import and use:
{model_imports}

API endpoints to implement:
{endpoints_text}

Requirements:
- Each endpoint MUST do real reads/writes against the SQLAlchemy models via a database
  session (assume an async session dependency `get_db` importable from "app.core.database").
- Implement real validation and correct HTTP status codes for error cases (404 for missing
  records, 400/422 for bad input, etc.) — do not return hardcoded/fake JSON.
- Implement the actual behavior implied by the key features and user stories above.
- Use a FastAPI APIRouter named `router`.
- No placeholders or TODOs — every endpoint must be fully implemented.

Return ONLY the raw Python code for this one file. No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(prompt, "python", GROQ_FILE_MAX_TOKENS)
    return GeneratedFile(
        path="backend/routes/api.py",
        language="python",
        content=content,
        description="FastAPI routes implementing all API endpoints against the real models",
    ), issue


async def generate_screen_file(
    project_name: str,
    screen: dict,
    endpoints: list,
    requirements_text: str,
    use_o3de: bool,
    native_capabilities: list[str] | None = None,
) -> tuple[GeneratedFile, str | None]:
    screen_name = screen.get("name", "Screen")
    component_name = _pascal(screen_name)
    endpoints_text = "\n".join(
        f"- {e.get('method')} {e.get('path')}: {e.get('purpose')}" for e in endpoints
    )

    if use_o3de:
        prompt = f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Write ONE complete O3DE scene/script stub implementing the "{screen_name}" scene of this app.

App: {project_name}
{requirements_text}
Scene purpose: {screen.get('purpose', '')}

Implement the real behavior described above for this scene — no placeholders.
Return ONLY the raw file content. No markdown fences, no explanation, no JSON."""
    else:
        available_capabilities = native_capabilities or []
        capabilities_text = "\n".join(
            f"- {NATIVE_CAPABILITY_DESCRIPTIONS[c]}" for c in available_capabilities if c in NATIVE_CAPABILITY_DESCRIPTIONS
        )
        native_section = (
            f"\nNative device features available to this app (import and use where relevant to "
            f"this screen's user stories — do not fake this functionality with browser-only "
            f"substitutes):\n{capabilities_text}\n"
            if capabilities_text
            else ""
        )

        prompt = f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Write ONE complete, real React functional component for the "{screen_name}" screen of this app.

App: {project_name}
{requirements_text}
Screen purpose: {screen.get('purpose', '')}

API endpoints this screen can call:
{endpoints_text}
{native_section}
Requirements:
- Component name: {component_name} (default export).
- Fetch real data from the relevant API endpoints above (use `fetch`), handle loading and
  error states, and implement the actual feature/user-story behavior for this screen — real
  form handling, real list rendering from the API response, real interactions.
- Style exclusively with Tailwind CSS utility classes via `className`. No inline styles,
  no other CSS frameworks, no separate CSS file.
- No placeholders or TODOs — this screen must be fully implemented, not static mockup content.

Return ONLY the raw JSX/JS code for this one file. No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(prompt, "javascript", GROQ_FILE_MAX_TOKENS)
    return GeneratedFile(
        path=f"frontend/src/screens/{component_name}.jsx",
        language="javascript",
        content=content,
        description=f"Screen implementing {screen_name}",
    ), issue


# ─── Final wiring pass — stitches the real files above into a runnable project ───
def build_wiring_prompt(
    project_name: str,
    tech_stack: dict,
    model_files: list[GeneratedFile],
    routes_file: GeneratedFile | None,
    screen_files: list[GeneratedFile],
    use_o3de: bool,
) -> str:
    model_list = ", ".join(f.path for f in model_files) or "(none)"
    screen_components = ", ".join(_pascal(f.path.split("/")[-1].removesuffix(".jsx")) for f in screen_files)
    screen_paths = ", ".join(f.path for f in screen_files) or "(none)"

    if use_o3de:
        return f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Generate the wiring/config files for an O3DE project.

App: {project_name}
Scene files already generated: {screen_paths}

Generate a JSON object with EXACTLY these fields (no markdown, no extra text, just valid JSON):
{{
  "summary": "2-3 sentences on the project structure",
  "files": [
    {{"path": "...", "language": "...", "content": "...", "description": "..."}}
  ]
}}

Include the O3DE project/workspace config files and a README_SETUP.md with exact setup commands.
Return ONLY valid JSON, nothing else."""

    return f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Generate ONLY the wiring/config files needed to make an already-implemented project installable and runnable. The real model/route/screen logic already exists — do not reimplement it, just wire it up correctly.

App: {project_name}
Backend: {tech_stack.get('backend', 'FastAPI + Python')}
Frontend: {tech_stack.get('frontend', 'React + TypeScript')}

Already-generated backend model files (import these into main.py): {model_list}
Already-generated routes file (mount its `router` in main.py): {routes_file.path if routes_file else '(none)'}
Already-generated screen components (import these EXACT names into App.jsx from their EXACT
paths below, and render them): {screen_components or 'Home'}
Screen file paths: {screen_paths}

Generate a JSON object with EXACTLY these fields (no markdown, no extra text, just valid JSON):
{{
  "summary": "2-3 sentences on what was generated and how to run it",
  "files": [
    {{"path": "...", "language": "...", "content": "...", "description": "..."}}
  ]
}}

Required files:
1. "backend/main.py" — real FastAPI entry point importing every model file above and mounting
   the routes router, startable with `uvicorn main:app --reload`.
2. "backend/requirements.txt" — every Python package needed, pinned reasonably.
3. "frontend/src/main.jsx" — Vite entry point:
   import React from 'react';
   import ReactDOM from 'react-dom/client';
   import App from './App';
   import './index.css';
   ReactDOM.createRoot(document.getElementById('root')).render(<App />);
4. "frontend/src/App.jsx" — imports EVERY screen component listed above by its EXACT name from
   its EXACT path and renders them (simple conditional/state-based navigation is fine).
5. "frontend/package.json" — "name" set to a lowercase-hyphenated slug of "{project_name}",
   react, react-dom, vite, @vitejs/plugin-react, tailwindcss, postcss, autoprefixer, with a
   "dev" script running "vite".
6. "frontend/src/index.css" — the three Tailwind directives, nothing else.
7. "frontend/tailwind.config.js" — minimal config with `content` covering frontend/src.
8. "frontend/postcss.config.js" — includes tailwindcss and autoprefixer.
9. "README_SETUP.md" — exact, copy-pasteable terminal commands to install and run both halves.

Return ONLY valid JSON, nothing else."""


@router.post(
    "/generate",
    response_model=GenerateCodeResponse,
    summary="Generate a real, working implementation from approved architecture",
)
async def generate_code(
    payload: GenerateCodeRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Takes the approved architecture, UI/UX design, and original requirements
    and generates a real implementation — one dedicated AI call per model,
    routes file, and screen (each with the full requirements context and its
    own token budget), then a final wiring pass that stitches everything into
    an installable, startable project.
    """
    result = await db.execute(
        select(Project).where(
            Project.id == payload.project_id,
            Project.user_id == user.id,
        )
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    if not project.architecture_data or not project.architecture_data.get("user_approved"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Architecture must be approved before generating code.",
        )

    architecture = (project.architecture_data or {}).get("architecture", {})
    uiux = (project.uiux_data or {}).get("design", {})
    requirements = project.requirements_data or {}
    requirements_text = _requirements_context(requirements)

    tech_stack = architecture.get("tech_stack", {})
    tables = architecture.get("database_tables", [])
    endpoints = architecture.get("api_endpoints", [])
    screens = uiux.get("screens", []) or [{"name": "Home", "purpose": "Landing screen"}]
    frontend_lower = tech_stack.get("frontend", "").lower()
    use_o3de = "o3de" in frontend_lower or "open 3d engine" in frontend_lower

    frd = requirements.get("frd", {}) or {}
    native_capabilities = detect_native_capabilities(
        " ".join(frd.get("key_features", []) or []) + " " + " ".join(frd.get("user_stories", []) or [])
    ) if not use_o3de else []

    validation_warnings: list[dict] = []

    def _track(file_and_issue: tuple[GeneratedFile, str | None]) -> GeneratedFile:
        file, issue = file_and_issue
        if issue:
            validation_warnings.append({"path": file.path, "reason": issue})
        return file

    try:
        model_files = [
            _track(await generate_model_file(project.name, table, requirements_text))
            for table in tables
        ]

        routes_file = None
        if not use_o3de and endpoints:
            routes_file = _track(await generate_routes_file(project.name, endpoints, tables, requirements_text))

        screen_files = [
            _track(await generate_screen_file(project.name, screen, endpoints, requirements_text, use_o3de, native_capabilities))
            for screen in screens
        ]

        wiring_prompt = build_wiring_prompt(project.name, tech_stack, model_files, routes_file, screen_files, use_o3de)
        wiring_result = await generate_text(wiring_prompt, max_tokens=GROQ_WIRING_MAX_TOKENS)
        wiring_parsed = parse_ai_json(wiring_result["text"])

        # Deliberately NOT adding native-capability helper files here — see
        # the comment on NATIVE_CAPABILITY_DESCRIPTIONS above. Each packaging
        # workflow writes its own platform-appropriate implementation of
        # frontend/src/native/*.js at build time instead.
        real_files = model_files + ([routes_file] if routes_file else []) + screen_files
        parsed = {
            "summary": wiring_parsed.get(
                "summary",
                f"Generated {len(real_files)} real implementation files plus wiring/config.",
            ),
            "files": [f.model_dump() for f in real_files] + wiring_parsed.get("files", []),
        }
        apply_package_json_name(parsed["files"], project.name)
        print("===== GENERATED FILES =====")
        for f in parsed.get("files", []):
            print(f["path"])
        if validation_warnings:
            print(f"===== VALIDATION WARNINGS ({len(validation_warnings)}) =====")
            for w in validation_warnings:
                print(f"{w['path']}: {w['reason']}")
        print("===========================")
    except AIError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.error(f"Failed to parse AI codegen response: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Baby Tiger had trouble writing your code. Please try again! 🐯",
        )

    codegen_result = CodeGenResult(**parsed)

    project.codegen_data = {
        "codegen": codegen_result.model_dump(),
        "files_generated": len(codegen_result.files),
        "native_capabilities": native_capabilities,
        "validation_warnings": validation_warnings,
        "user_approved": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.commit()

    return GenerateCodeResponse(codegen=codegen_result)


@router.get(
    "/{project_id}",
    summary="Get saved generated code",
)
async def get_code(
    project_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve previously generated code files."""
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.user_id == user.id,
        )
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    if not project.codegen_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No code generated yet.",
        )

    return {
        "success": True,
        "codegen": project.codegen_data.get("codegen"),
        "user_approved": project.codegen_data.get("user_approved", False),
        "generated_at": project.codegen_data.get("generated_at"),
    }


@router.post(
    "/approve",
    summary="Approve generated code and move to next phase",
)
async def approve_code(
    payload: ApproveCodeRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """User approves the generated code. Marks phase complete."""
    result = await db.execute(
        select(Project).where(
            Project.id == payload.project_id,
            Project.user_id == user.id,
        )
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    if not project.codegen_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No generated code to approve.",
        )

    # Reassign whole dict — required for SQLAlchemy JSON column change tracking
    codegen_data = dict(project.codegen_data)
    codegen_data["user_approved"] = payload.approved
    codegen_data["approved_at"] = datetime.now(timezone.utc).isoformat()
    project.codegen_data = codegen_data

    if payload.approved:
        phases = project.phases_completed or []
        if "code_generation" not in phases:
            phases.append("code_generation")
        project.phases_completed = phases
        project.progress_percent = project.get_progress_percent()
        project.current_phase = SDLCPhase.TESTING

    await db.commit()

    return {
        "success": True,
        "message": "Code approved! Next: Testing 🐯" if payload.approved else "Feedback noted.",
        "progress_percent": project.progress_percent,
    }
