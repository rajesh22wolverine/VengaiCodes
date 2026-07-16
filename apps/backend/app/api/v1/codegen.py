# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Code Generation API Routes (Sprint 6, updated)
#  api/v1/codegen.py — Generate a runnable starter code skeleton
#  from approved architecture. Now REQUIRES entry-point wiring
#  files (main.jsx, App.jsx, package.json, main.py, etc.) so the
#  output is actually installable and startable, not just fragments.
# ═══════════════════════════════════════════════════════════════

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.orchestrator import AIError, generate_text
from app.api.v1.auth import get_current_active_user
from app.core.database import get_db
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


# ─── Prompt builder ───
def build_codegen_prompt(project_name: str, architecture: dict, uiux: dict) -> str:
    tech_stack = architecture.get("tech_stack", {})
    tables = architecture.get("database_tables", [])
    endpoints = architecture.get("api_endpoints", [])
    screens = uiux.get("screens", [])

    tables_text = "\n".join(
        f"- {t.get('name')}: {t.get('purpose')} (fields: {', '.join(t.get('key_fields', []))})"
        for t in tables
    )
    endpoints_text = "\n".join(
        f"- {e.get('method')} {e.get('path')}: {e.get('purpose')}"
        for e in endpoints
    )
    screen_names = [s.get("name", "Screen") for s in screens]
    screens_text = "\n".join(f"- {s.get('name')}: {s.get('purpose')}" for s in screens)
    screens_list = ", ".join(screen_names) if screen_names else "Home"

    return f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Based on this approved architecture, generate a STARTER CODE SKELETON that actually builds and runs — not isolated fragments, but a coherent project with the exact wiring files a Vite + React app needs.

App: {project_name}
Backend: {tech_stack.get('backend', 'FastAPI + Python')}
Frontend: {tech_stack.get('frontend', 'React + TypeScript')}
Database: {tech_stack.get('database', 'PostgreSQL')}

Database tables:
{tables_text}

API endpoints:
{endpoints_text}

Screens:
{screens_text}

Generate a JSON object with EXACTLY these fields (no markdown, no extra text, just valid JSON):
{{
  "summary": "2-3 sentences on what was generated and what still needs to be built",
  "files": [
    {{
      "path": "backend/models/example.py",
      "language": "python",
      "content": "# actual code here, 20-60 lines, syntactically valid",
      "description": "1 sentence describing this file"
    }}
  ]
}}

CRITICAL — these EXACT files are REQUIRED. Without them the project cannot start at all:

1. "frontend/src/main.jsx" — the Vite entry point. MUST contain exactly this pattern:
   import React from 'react';
   import ReactDOM from 'react-dom/client';
   import App from './App';
   ReactDOM.createRoot(document.getElementById('root')).render(<App />);

2. "frontend/src/App.jsx" — imports EVERY screen component listed below by its EXACT
   filename and renders them (simple conditional rendering is fine; does not need
   react-router). Import paths MUST exactly match the screen files you generate in
   step 8 below (e.g. if you generate "frontend/src/screens/Dashboard.jsx", App.jsx
   must import from "./screens/Dashboard").

3. "backend/requirements.txt" — every Python package this project needs, pinned to
   reasonable versions (fastapi, uvicorn, sqlalchemy, python-dotenv, etc.)

4. "backend/main.py" — a real FastAPI entry point that imports every generated model
   and route file, mounts them, and would actually start with `uvicorn main:app --reload`

5. "frontend/package.json" — every npm package needed (react, react-dom, vite, and
   the @vitejs/plugin-react dev dependency), with a "dev" script running "vite"

6. "README_SETUP.md" — exact, copy-pasteable terminal commands to install and run
   both backend and frontend locally

7. ONE file per database table (SQLAlchemy model, imported by backend/main.py)

8. ONE file with FastAPI route stubs covering all the API endpoints (imported by
   backend/main.py, returning placeholder JSON data)

9. ONE file PER SCREEN, using this EXACT path pattern: "frontend/src/screens/{{ScreenName}}.jsx"
   — the screens to generate are: {screens_list}
   Each MUST be a valid React functional component with a default export, and its
   filename must exactly match the name used when App.jsx imports it.

ADDITIONAL CRITICAL FILES FOR TAILWIND STYLING (FRONTEND):
10. "frontend/src/index.css" — MUST exist and contain the Tailwind directives exactly:
     @tailwind base;
     @tailwind components;
     @tailwind utilities;

11. "frontend/tailwind.config.js" — Tailwind configuration file (minimal, with `content` pointing
        to the frontend source files).

12. "frontend/postcss.config.js" — PostCSS config that includes `tailwindcss` and `autoprefixer`.

Styling rules (Tailwind-only):
- The frontend MUST be styled exclusively using Tailwind CSS utility classes via `className` in JSX.
- Do NOT create or import additional CSS files for component styles; only `frontend/src/index.css` is allowed
    for Tailwind directives and very small helper utilities if strictly necessary.
- Do NOT use inline `style={...}` or other CSS frameworks (Bootstrap, Material UI, etc.).
- `frontend/src/main.jsx` MUST include `import './index.css';` alongside React/ReactDOM/App imports.
- Include `tailwindcss`, `postcss`, and `autoprefixer` in `frontend/package.json` (devDependencies).
- Provide at least one clear example UI element using Tailwind utilities (e.g. a responsive card or button
    with `sm:`/`md:` prefixes) in the generated screens.


Rules:
- File extensions matter: React component files MUST use ".jsx", NOT ".js".
- Keep each file concise — 20-60 lines (README_SETUP.md may be longer).
- All code must be syntactically valid in its language.
- Import paths must be internally CONSISTENT across files — if App.jsx imports
    "./screens/Dashboard", the file "frontend/src/screens/Dashboard.jsx" must exist
    and export a default component named "Dashboard" (or whatever import name is used).

Frontend-specific constraints (summary):
- Generate a complete Vite + React application with `frontend/src/main.jsx` as the entry.
- `main.jsx` must import `./index.css` to enable Tailwind.
- Include `tailwind.config.js` and `postcss.config.js`, and list `tailwindcss`, `postcss`, and
    `autoprefixer` in `frontend/package.json` devDependencies.
- All visual styling must use Tailwind utility classes in `className`. Provide at least one
    representative component (button or card) demonstrating responsive utilities like `sm:`/`md:`.

Backend:
- Generate one SQLAlchemy model per database table.
- Generate one FastAPI routes file covering all API endpoints using placeholder/mock implementations.

General:
- Keep each file concise (20–60 lines).
- All code must be syntactically valid.
- Use realistic import statements.
- Return ONLY valid JSON.

Respond with ONLY the JSON object, nothing else."""


def parse_ai_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    cleaned = cleaned.strip()
    return json.loads(cleaned)


@router.post(
    "/generate",
    response_model=GenerateCodeResponse,
    summary="Generate starter code skeleton from approved architecture",
)
async def generate_code(
    payload: GenerateCodeRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Takes the approved architecture and UI/UX design and generates a
    starter code skeleton — models, API route stubs, component shells,
    plus the wiring files needed to actually install and run the project.
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

    try:
        prompt = build_codegen_prompt(project.name, architecture, uiux)
        ai_result = await generate_text(prompt)
        parsed = parse_ai_json(ai_result["text"])
        print("===== GENERATED FILES =====")
        for f in parsed.get("files", []):
            print(f["path"])
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
