# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Testing API Routes (Sprint 7, updated)
#  api/v1/testing.py — Let the user choose a testing framework,
#  generate test file stubs (auto-generated + user-requested custom
#  modules) in that framework's style, ACTUALLY RUN them via a
#  GitHub Actions workflow (run-tests.yml, same repository_dispatch
#  + poll-status + download-artifact pattern as the Windows/Linux/
#  Android packaging pipelines), and — on failure — let Baby Tiger
#  attempt a bounded number of automatic fixes before handing control
#  back to the user.
#
#  HONEST SCOPE: only frameworks that can run headlessly in CI are
#  offered (pytest/unittest, Jest/Vitest + Testing Library) — E2E
#  frameworks like Playwright/Cypress need a fully running deployed
#  app, which the "starter skeleton" codegen output can't reliably
#  provide, so they're intentionally excluded here. DB-dependent
#  backend tests get a best-effort ephemeral Postgres service
#  container in CI; if the generated skeleton doesn't actually wire
#  up DATABASE_URL/migrations, those specific tests may still fail
#  for reasons auto-fix can't resolve. Auto-fix is capped at
#  MAX_AUTO_FIX_ATTEMPTS with a manual override on the frontend so
#  the user is never stuck.
# ═══════════════════════════════════════════════════════════════

import io
import json
import logging
import zipfile
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.orchestrator import AIError, generate_text
from app.api.v1.auth import get_current_active_user
from app.ai.codegen_shared import strip_code_fences, validate_generated_content
from app.config import settings
from app.core.database import get_db
from app.models.project import Project, SDLCPhase
from app.models.user import User

logger = logging.getLogger("vengaicode.testing")
router = APIRouter()

GITHUB_API = "https://api.github.com"
TEST_WORKFLOW_FILE = "run-tests.yml"
TEST_RESULTS_ARTIFACT_NAME = "test-results"
MAX_AUTO_FIX_ATTEMPTS = 3


# ─── Schemas ───
class GenerateTestsRequest(BaseModel):
    project_id: str
    frontend_framework: str | None = None
    backend_framework: str | None = None


class GeneratedTestFile(BaseModel):
    path: str
    language: str
    content: str
    description: str
    tests_what: str  # which generated file/endpoint this test targets
    framework: str = ""
    source: str = "auto"  # "auto" (initial batch) | "custom" (user-requested module)


class TestPlanResult(BaseModel):
    summary: str
    test_files: list[GeneratedTestFile]
    coverage_notes: str  # honest note on what IS and ISN'T covered


class GenerateTestsResponse(BaseModel):
    success: bool = True
    testing: TestPlanResult


class ApproveTestsRequest(BaseModel):
    project_id: str
    approved: bool = True


class CustomModuleRequest(BaseModel):
    project_id: str
    description: str


class FrameworkOptions(BaseModel):
    detected_stack: str
    options: list[str]
    recommended: str


class TestFrameworksResponse(BaseModel):
    success: bool = True
    frontend: FrameworkOptions
    backend: FrameworkOptions
    selected: dict[str, str] | None = None


class RunTestsRequest(BaseModel):
    project_id: str


class TestRunStatusResponse(BaseModel):
    success: bool = True
    status: str  # "not_started" | "queued" | "in_progress" | "completed" | "failed"
    run_url: str | None = None
    conclusion: str | None = None  # "success" | "failure" | None


class TestFailure(BaseModel):
    file: str
    test_name: str
    message: str


class TestRunResults(BaseModel):
    passed: int = 0
    failed: int = 0
    total: int = 0
    failures: list[TestFailure] = []


class TestRunResultsResponse(BaseModel):
    success: bool = True
    results: TestRunResults
    all_tests_passed: bool


class AutoFixRequest(BaseModel):
    project_id: str


class AutoFixResponse(BaseModel):
    success: bool = True
    attempts: int
    max_attempts_reached: bool = False
    fixed_files: list[str] = []
    message: str


# ─── Suitable-framework detection ───
#
# Keyword-matched against the free-text tech_stack strings the architecture
# phase already generated (e.g. "FastAPI (Python) - ..."), same style as
# detect_native_capabilities() in codegen.py. Only frameworks that can
# actually run headlessly in CI are listed — see module docstring.
BACKEND_NODE_KEYWORDS = ["express", "node", "nest"]
BACKEND_PYTHON_KEYWORDS = ["fastapi", "flask", "django", "python"]
FRONTEND_VUE_KEYWORDS = ["vue"]

BACKEND_FRAMEWORK_OPTIONS = {
    "node": ["Jest + Supertest", "Mocha + Chai"],
    "python": ["pytest", "unittest"],
    "default": ["pytest", "unittest"],
}
FRONTEND_FRAMEWORK_OPTIONS = {
    "vue": ["Vitest + Vue Test Utils"],
    "react": ["Jest + React Testing Library", "Vitest + React Testing Library"],
}


def detect_suitable_test_frameworks(tech_stack: dict) -> dict:
    backend_text = (tech_stack.get("backend") or "").lower()
    frontend_text = (tech_stack.get("frontend") or "").lower()

    if any(k in backend_text for k in BACKEND_NODE_KEYWORDS):
        backend_options = BACKEND_FRAMEWORK_OPTIONS["node"]
    elif any(k in backend_text for k in BACKEND_PYTHON_KEYWORDS):
        backend_options = BACKEND_FRAMEWORK_OPTIONS["python"]
    else:
        backend_options = BACKEND_FRAMEWORK_OPTIONS["default"]

    frontend_options = (
        FRONTEND_FRAMEWORK_OPTIONS["vue"]
        if any(k in frontend_text for k in FRONTEND_VUE_KEYWORDS)
        else FRONTEND_FRAMEWORK_OPTIONS["react"]
    )

    return {"backend": backend_options, "frontend": frontend_options}


# ─── Prompt builders ───
def build_testing_prompt(
    project_name: str,
    architecture: dict,
    codegen: dict,
    backend_framework: str,
    frontend_framework: str,
) -> str:
    endpoints = architecture.get("api_endpoints", [])
    files = codegen.get("files", [])

    endpoints_text = "\n".join(
        f"- {e.get('method')} {e.get('path')}: {e.get('purpose')}"
        for e in endpoints
    )
    files_text = "\n".join(
        f"- {f.get('path')} ({f.get('language')}): {f.get('description')}"
        for f in files
    )

    return f"""You are Baby Tiger 🐯, VengaiCode's AI testing assistant. Based on this app's approved architecture and generated starter code, write TEST FILE STUBS — not full test suites, just well-structured starting points.

App: {project_name}

API endpoints:
{endpoints_text}

Generated files:
{files_text}

Write backend tests using {backend_framework} conventions EXACTLY (e.g. pytest uses bare
`assert` statements and fixtures; unittest uses `self.assertEqual` inside a `unittest.TestCase`
subclass). Write frontend tests using {frontend_framework} conventions EXACTLY (e.g. Jest uses
`jest.mock`; Vitest uses `vi.mock` and `import {{ describe, it, expect, vi }} from 'vitest'`).

These files get ACTUALLY EXECUTED in CI afterward, so file paths must follow discovery
conventions exactly:
- EVERY backend test file path MUST be "backend/tests/test_<name>.py" (pytest's default
  discovery pattern — it will not find files that don't start with "test_").
- EVERY frontend test file path MUST end in ".test.jsx" or ".test.js" and live under
  "frontend/src/" (e.g. "frontend/src/screens/Home.test.jsx") — this is the default
  discovery pattern for both Jest and Vitest.

Generate a JSON object with EXACTLY these fields (no markdown, no extra text, just valid JSON):
{{
  "summary": "2-3 sentences on what test coverage was generated and its purpose",
  "test_files": [
    {{
      "path": "backend/tests/test_example.py",
      "language": "python",
      "content": "# actual test code in the requested framework's style, 15-40 lines, syntactically valid",
      "description": "1 sentence describing what this test file covers",
      "tests_what": "the file or endpoint this targets, e.g. 'POST /api/workouts'",
      "framework": "the exact framework this file was written for, e.g. '{backend_framework}' or '{frontend_framework}'"
    }}
  ],
  "coverage_notes": "1-2 honest sentences on what these test stubs DO cover and what they DON'T (e.g. happy-path only, no edge cases, no auth failure cases, not yet runnable without a live database)"
}}

Rules:
- Generate ONE test file per API endpoint, covering the basic happy-path request/response shape
- Generate ONE test file for frontend components covering 2-3 key components
- Keep each file concise — 15-40 lines
- Be honest in coverage_notes about the limitations

Respond with ONLY the JSON object, nothing else."""


def parse_ai_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    cleaned = cleaned.strip()
    return json.loads(cleaned)


# ═══════════════════════════════════════════════════════════════
#  GET /{project_id}/frameworks — suitable frameworks for this project
# ═══════════════════════════════════════════════════════════════
@router.get(
    "/{project_id}/frameworks",
    response_model=TestFrameworksResponse,
    summary="Get testing frameworks suitable for this project's tech stack",
)
async def get_test_frameworks(
    project_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user.id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    if not project.architecture_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Architecture must be generated before choosing a testing framework.",
        )

    tech_stack = (project.architecture_data or {}).get("architecture", {}).get("tech_stack", {})
    options = detect_suitable_test_frameworks(tech_stack)
    selected = (project.testing_data or {}).get("selected_frameworks")

    return TestFrameworksResponse(
        frontend=FrameworkOptions(
            detected_stack=tech_stack.get("frontend", ""),
            options=options["frontend"],
            recommended=options["frontend"][0],
        ),
        backend=FrameworkOptions(
            detected_stack=tech_stack.get("backend", ""),
            options=options["backend"],
            recommended=options["backend"][0],
        ),
        selected=selected,
    )


@router.post(
    "/generate",
    response_model=GenerateTestsResponse,
    summary="Generate test file stubs from approved code, in the chosen framework(s)",
)
async def generate_tests(
    payload: GenerateTestsRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Takes the approved architecture and generated code, and produces
    test file stubs in the requested (or auto-recommended) frameworks.
    Does NOT execute any code by itself — see /run for that. Calling
    this again (e.g. to switch frameworks) regenerates the auto-batch
    but preserves any user-added custom test modules.
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

    if not project.codegen_data or not project.codegen_data.get("user_approved"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Generated code must be approved before generating tests.",
        )

    architecture = (project.architecture_data or {}).get("architecture", {})
    codegen = (project.codegen_data or {}).get("codegen", {})
    tech_stack = architecture.get("tech_stack", {})

    suitable = detect_suitable_test_frameworks(tech_stack)
    backend_framework = payload.backend_framework or suitable["backend"][0]
    frontend_framework = payload.frontend_framework or suitable["frontend"][0]

    try:
        prompt = build_testing_prompt(
            project.name, architecture, codegen, backend_framework, frontend_framework
        )
        ai_result = await generate_text(prompt)
        parsed = parse_ai_json(ai_result["text"])
    except AIError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.error(f"Failed to parse AI testing response: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Baby Tiger had trouble writing your tests. Please try again! 🐯",
        )

    new_auto_files = []
    for f in parsed.get("test_files", []):
        f.setdefault("source", "auto")
        f.setdefault("framework", "")
        new_auto_files.append(GeneratedTestFile(**f))

    # Preserve any user-added custom modules across a framework regenerate.
    existing_testing = (project.testing_data or {}).get("testing", {})
    custom_files = [
        GeneratedTestFile(**f)
        for f in existing_testing.get("test_files", [])
        if f.get("source") == "custom"
    ]

    testing_result = TestPlanResult(
        summary=parsed.get("summary", ""),
        test_files=new_auto_files + custom_files,
        coverage_notes=parsed.get("coverage_notes", ""),
    )

    project.testing_data = {
        "testing": testing_result.model_dump(),
        "total_tests": len(testing_result.test_files),
        "suitable_frameworks": suitable,
        "selected_frameworks": {"backend": backend_framework, "frontend": frontend_framework},
        "user_approved": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "auto_fix_attempts": 0,
        "last_run_results": None,
        "all_tests_passed": False,
    }
    await db.commit()

    return GenerateTestsResponse(testing=testing_result)


@router.post(
    "/custom-module",
    summary="Add a user-described custom test module",
)
async def add_custom_test_module(
    payload: CustomModuleRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Lets the user describe, in their own words, what they want tested.
    Generates 1-3 focused test files for exactly that, tagged as
    "custom" so they survive future framework-switch regenerates.
    """
    if not payload.description.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Describe what you want tested.")

    result = await db.execute(
        select(Project).where(Project.id == payload.project_id, Project.user_id == user.id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    if not project.testing_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Generate the initial tests before adding custom modules.",
        )

    codegen = (project.codegen_data or {}).get("codegen", {})
    selected = project.testing_data.get("selected_frameworks", {})
    backend_framework = selected.get("backend", "pytest")
    frontend_framework = selected.get("frontend", "Jest + React Testing Library")

    files_text = "\n".join(
        f"- {f.get('path')} ({f.get('language')}): {f.get('description')}"
        for f in codegen.get("files", [])
    )

    prompt = f"""You are Baby Tiger 🐯, VengaiCode's AI testing assistant. Based on this app's generated code, write 1-3 FOCUSED test files covering EXACTLY what the user asked for below — nothing more, nothing unrelated.

App: {project.name}
User's testing request: "{payload.description}"

Generated files available:
{files_text}

Use {backend_framework} conventions for any backend test, {frontend_framework} conventions for any frontend test.

These files get ACTUALLY EXECUTED in CI afterward, so file paths must follow discovery
conventions exactly: backend test paths MUST be "backend/tests/test_<name>.py" (pytest only
discovers files starting with "test_"); frontend test paths MUST end in ".test.jsx" or
".test.js" under "frontend/src/" (the default Jest/Vitest discovery pattern).

Generate a JSON object with EXACTLY this field (no markdown, no extra text, just valid JSON):
{{
  "test_files": [
    {{
      "path": "...",
      "language": "...",
      "content": "...",
      "description": "...",
      "tests_what": "...",
      "framework": "..."
    }}
  ]
}}

Rules:
- 1 to 3 files only, each 15-40 lines
- Target specifically what the user described
- No placeholders or TODOs

Respond with ONLY the JSON object, nothing else."""

    try:
        ai_result = await generate_text(prompt)
        parsed = parse_ai_json(ai_result["text"])
    except AIError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.error(f"Failed to parse AI custom-module response: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Baby Tiger had trouble writing that test module. Please try again! 🐯",
        )

    new_files: list[GeneratedTestFile] = []
    warnings: list[str] = []
    for i, raw in enumerate(parsed.get("test_files", [])[:3]):
        language = raw.get("language", "")
        content = strip_code_fences(raw.get("content", ""))
        issue = validate_generated_content(language, content)
        if issue:
            warnings.append(f"{raw.get('path', '?')}: {issue}")

        new_files.append(GeneratedTestFile(
            path=raw.get("path") or f"tests/custom_{i}.txt",
            language=language,
            content=content,
            description=raw.get("description", ""),
            tests_what=raw.get("tests_what", payload.description),
            framework=raw.get("framework") or (backend_framework if language == "python" else frontend_framework),
            source="custom",
        ))

    if not new_files:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Baby Tiger didn't generate any test files for that request. Try rephrasing it.",
        )

    testing_data = dict(project.testing_data)
    testing_inner = dict(testing_data["testing"])
    testing_inner["test_files"] = testing_inner.get("test_files", []) + [f.model_dump() for f in new_files]
    testing_data["testing"] = testing_inner
    testing_data["total_tests"] = len(testing_inner["test_files"])
    project.testing_data = testing_data
    await db.commit()

    return {
        "success": True,
        "testing": testing_inner,
        "added_files": [f.model_dump() for f in new_files],
        "warnings": warnings,
    }


@router.get(
    "/{project_id}",
    summary="Get saved test files",
)
async def get_tests(
    project_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve previously generated test files."""
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.user_id == user.id,
        )
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    if not project.testing_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No tests generated yet.",
        )

    return {
        "success": True,
        "testing": project.testing_data.get("testing"),
        "user_approved": project.testing_data.get("user_approved", False),
        "generated_at": project.testing_data.get("generated_at"),
        "suitable_frameworks": project.testing_data.get("suitable_frameworks"),
        "selected_frameworks": project.testing_data.get("selected_frameworks"),
        "auto_fix_attempts": project.testing_data.get("auto_fix_attempts", 0),
        "last_run_results": project.testing_data.get("last_run_results"),
        "all_tests_passed": project.testing_data.get("all_tests_passed", False),
    }


# ═══════════════════════════════════════════════════════════════
#  GET /{project_id}/files — CI use only, fetches code+tests to run
# ═══════════════════════════════════════════════════════════════
@router.get(
    "/{project_id}/files",
    summary="[CI use only] Fetch generated code + tests for a test run",
)
async def get_test_run_files(
    project_id: str,
    x_build_secret: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Called BY the run-tests.yml GitHub Actions workflow, not the
    frontend — secured by a shared secret header instead of a user
    JWT, since the CI runner has no user session. Same auth pattern
    as packaging.py's GET /{project_id}/files.
    """
    if not settings.BUILD_SECRET or x_build_secret != settings.BUILD_SECRET:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid build secret.")

    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()

    if project is None or not project.codegen_data or not project.testing_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project, generated code, or tests not found.",
        )

    tech_stack = (project.architecture_data or {}).get("architecture", {}).get("tech_stack", {})

    return {
        "project_id": project_id,
        "codegen_files": project.codegen_data.get("codegen", {}).get("files", []),
        "test_files": project.testing_data.get("testing", {}).get("test_files", []),
        "tech_stack": tech_stack,
        "selected_frameworks": project.testing_data.get("selected_frameworks", {}),
    }


# ═══════════════════════════════════════════════════════════════
#  POST /run — trigger a real test run via GitHub Actions
# ═══════════════════════════════════════════════════════════════
@router.post(
    "/run",
    summary="Trigger a real test run via GitHub Actions",
)
async def trigger_test_run(
    payload: RunTestsRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    if not settings.GITHUB_TOKEN or not settings.GITHUB_REPO:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Test running is not configured yet (missing GitHub credentials).",
        )

    result = await db.execute(
        select(Project).where(Project.id == payload.project_id, Project.user_id == user.id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    if not project.codegen_data or not project.codegen_data.get("user_approved"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Generated code must be approved before running tests.",
        )
    if not project.testing_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Generate tests before running them.")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{GITHUB_API}/repos/{settings.GITHUB_REPO}/dispatches",
            headers={
                "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
            },
            json={
                "event_type": "run-tests-app",
                "client_payload": {"project_id": payload.project_id},
            },
        )

    if response.status_code != 204:
        logger.error(f"Failed to trigger test run: {response.status_code} {response.text}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to start the test run. Please try again.")

    return {"success": True, "message": "Test run started! This takes a few minutes. 🧪🐯"}


@router.get(
    "/{project_id}/run-status",
    response_model=TestRunStatusResponse,
    summary="Check the status of the most recent test run",
)
async def get_test_run_status(
    project_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user.id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    if not settings.GITHUB_TOKEN or not settings.GITHUB_REPO:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Test running is not configured yet.")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{GITHUB_API}/repos/{settings.GITHUB_REPO}/actions/workflows/{TEST_WORKFLOW_FILE}/runs",
            headers={
                "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
            },
            params={"per_page": 20},
        )

    if response.status_code != 200:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to check test run status.")

    runs = response.json().get("workflow_runs", [])
    matching = next((r for r in runs if project_id in (r.get("name") or "")), None)
    if matching is None:
        return TestRunStatusResponse(status="not_started")

    return TestRunStatusResponse(
        status=matching.get("status", "unknown"),
        conclusion=matching.get("conclusion"),
        run_url=matching.get("html_url"),
    )


@router.get(
    "/{project_id}/run-results",
    response_model=TestRunResultsResponse,
    summary="Fetch and parse the results of the most recent completed test run",
)
async def get_test_run_results(
    project_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user.id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    if not settings.GITHUB_TOKEN or not settings.GITHUB_REPO:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Test running is not configured yet.")

    async with httpx.AsyncClient(timeout=30.0) as client:
        runs_response = await client.get(
            f"{GITHUB_API}/repos/{settings.GITHUB_REPO}/actions/workflows/{TEST_WORKFLOW_FILE}/runs",
            headers={
                "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
            },
            params={"per_page": 20, "status": "completed"},
        )
        runs = runs_response.json().get("workflow_runs", [])
        matching = next((r for r in runs if project_id in (r.get("name") or "")), None)
        if matching is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No completed test run found for this project. Trigger a run first.",
            )

        run_id = matching["id"]
        artifacts_response = await client.get(
            f"{GITHUB_API}/repos/{settings.GITHUB_REPO}/actions/runs/{run_id}/artifacts",
            headers={
                "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
            },
        )
        artifacts = artifacts_response.json().get("artifacts", [])
        artifact = next((a for a in artifacts if a["name"] == TEST_RESULTS_ARTIFACT_NAME), None)
        if artifact is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Test run completed but no results artifact was found.",
            )

        zip_response = await client.get(
            f"{GITHUB_API}/repos/{settings.GITHUB_REPO}/actions/artifacts/{artifact['id']}/zip",
            headers={
                "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
            },
            follow_redirects=True,
        )

    if zip_response.status_code != 200:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to download test results.")

    try:
        with zipfile.ZipFile(io.BytesIO(zip_response.content)) as zf:
            with zf.open("test-results.json") as f:
                results_raw = json.load(f)
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as e:
        logger.error(f"Failed to parse test results artifact: {e}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Test results artifact was unreadable.")

    results = TestRunResults(
        passed=results_raw.get("passed", 0),
        failed=results_raw.get("failed", 0),
        total=results_raw.get("total", 0),
        failures=[TestFailure(**f) for f in results_raw.get("failures", [])],
    )
    all_passed = results.failed == 0 and results.total > 0

    # Reassign whole dict — required for SQLAlchemy JSON column change tracking
    testing_data = dict(project.testing_data)
    testing_data["last_run_results"] = {
        **results.model_dump(),
        "run_url": matching.get("html_url"),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    testing_data["all_tests_passed"] = all_passed
    project.testing_data = testing_data
    await db.commit()

    return TestRunResultsResponse(results=results, all_tests_passed=all_passed)


# ═══════════════════════════════════════════════════════════════
#  POST /auto-fix — bounded AI attempt to fix failing tests
# ═══════════════════════════════════════════════════════════════
@router.post(
    "/auto-fix",
    response_model=AutoFixResponse,
    summary="Let Baby Tiger attempt to fix failing tests (capped at MAX_AUTO_FIX_ATTEMPTS)",
)
async def auto_fix_tests(
    payload: AutoFixRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Project).where(Project.id == payload.project_id, Project.user_id == user.id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    if not project.testing_data or not project.testing_data.get("last_run_results"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Run the tests first before attempting a fix.")

    last_results = project.testing_data["last_run_results"]
    failures = last_results.get("failures", [])
    attempts = project.testing_data.get("auto_fix_attempts", 0)

    if not failures:
        return AutoFixResponse(attempts=attempts, message="No failures to fix.")

    if attempts >= MAX_AUTO_FIX_ATTEMPTS:
        return AutoFixResponse(
            attempts=attempts,
            max_attempts_reached=True,
            message="Baby Tiger already tried the maximum number of automatic fixes.",
        )

    codegen_files = (project.codegen_data or {}).get("codegen", {}).get("files", [])
    test_files = (project.testing_data or {}).get("testing", {}).get("test_files", [])

    def _find_file(path: str, files: list[dict]) -> dict | None:
        return next((f for f in files if f.get("path") == path), None)

    failure_lines = []
    referenced_paths: set[str] = set()
    for fail in failures[:5]:  # cap prompt size
        fail_file = fail.get("file", "")
        referenced_paths.add(fail_file)
        failure_lines.append(f"- Test '{fail.get('test_name', '?')}' in {fail_file} failed: {fail.get('message', '')}")
    failures_text = "\n".join(failure_lines)

    context_files = [
        match for path in referenced_paths
        if (match := (_find_file(path, test_files) or _find_file(path, codegen_files)))
    ]
    context_text = "\n\n".join(f"--- {f['path']} ---\n{f['content']}" for f in context_files)

    prompt = f"""You are Baby Tiger 🐯, VengaiCode's AI testing assistant. These tests failed when actually run in CI:

{failures_text}

Relevant file contents:
{context_text}

Decide whether the SOURCE code or the TEST code is wrong, and fix whichever is actually broken
(usually the source code, since the tests describe the intended behavior — but fix the test
itself if it's clearly testing the wrong thing).

Generate a JSON object with EXACTLY this field (no markdown, no extra text, just valid JSON):
{{
  "fixes": [
    {{"path": "the exact existing path being corrected", "language": "...", "content": "the FULL corrected file content"}}
  ]
}}

Rules:
- Only include files that actually need to change
- Return the COMPLETE corrected file content for each, not a diff or snippet
- No placeholders or TODOs

Respond with ONLY the JSON object, nothing else."""

    try:
        ai_result = await generate_text(prompt)
        parsed = parse_ai_json(ai_result["text"])
    except AIError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.error(f"Failed to parse AI auto-fix response: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Baby Tiger had trouble analyzing the failures. Please try again! 🐯",
        )

    fixed_paths: list[str] = []
    codegen_data = dict(project.codegen_data)
    codegen_inner = dict(codegen_data["codegen"])
    codegen_files_mut = list(codegen_inner.get("files", []))

    testing_data = dict(project.testing_data)
    testing_inner = dict(testing_data["testing"])
    test_files_mut = list(testing_inner.get("test_files", []))

    for fix in parsed.get("fixes", []):
        path = fix.get("path", "")
        content = strip_code_fences(fix.get("content", ""))
        language = fix.get("language", "")
        issue = validate_generated_content(language, content)
        if issue:
            logger.warning(f"Auto-fix produced invalid content for {path}: {issue}")
            continue

        test_idx = next((i for i, f in enumerate(test_files_mut) if f.get("path") == path), None)
        if test_idx is not None:
            test_files_mut[test_idx] = {**test_files_mut[test_idx], "content": content}
            fixed_paths.append(path)
            continue

        code_idx = next((i for i, f in enumerate(codegen_files_mut) if f.get("path") == path), None)
        if code_idx is not None:
            codegen_files_mut[code_idx] = {**codegen_files_mut[code_idx], "content": content}
            fixed_paths.append(path)

    if not fixed_paths:
        return AutoFixResponse(attempts=attempts, message="Baby Tiger couldn't identify a fix for these failures.")

    codegen_inner["files"] = codegen_files_mut
    codegen_data["codegen"] = codegen_inner
    project.codegen_data = codegen_data

    testing_inner["test_files"] = test_files_mut
    testing_data["testing"] = testing_inner
    testing_data["auto_fix_attempts"] = attempts + 1
    project.testing_data = testing_data

    await db.commit()

    return AutoFixResponse(
        attempts=attempts + 1,
        fixed_files=fixed_paths,
        message=f"Baby Tiger patched {len(fixed_paths)} file(s) — re-running tests...",
    )


@router.post(
    "/approve",
    summary="Approve tests and move to next phase",
)
async def approve_tests(
    payload: ApproveTestsRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """User approves the generated tests. Marks phase complete."""
    result = await db.execute(
        select(Project).where(
            Project.id == payload.project_id,
            Project.user_id == user.id,
        )
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    if not project.testing_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No tests to approve.",
        )

    # Reassign whole dict — required for SQLAlchemy JSON column change tracking
    testing_data = dict(project.testing_data)
    testing_data["user_approved"] = payload.approved
    testing_data["approved_at"] = datetime.now(timezone.utc).isoformat()
    project.testing_data = testing_data

    if payload.approved:
        phases = project.phases_completed or []
        if "testing" not in phases:
            phases.append("testing")
        project.phases_completed = phases
        project.progress_percent = project.get_progress_percent()
        project.current_phase = SDLCPhase.EXPORT

    await db.commit()

    return {
        "success": True,
        "message": "Tests approved! Next: Export 🐯" if payload.approved else "Feedback noted.",
        "progress_percent": project.progress_percent,
    }
