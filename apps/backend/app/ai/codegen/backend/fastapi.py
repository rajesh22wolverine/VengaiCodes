# ═══════════════════════════════════════════════════════════════
#  VengaiCode — FastAPI Backend Adapter
#  ai/codegen/backend/fastapi.py — Model/routes generation moved
#  verbatim from the old codegen.py's default branches. No behavior
#  change from the pre-adapter version.
# ═══════════════════════════════════════════════════════════════

from app.ai.codegen.manifests.requirements_txt import build_requirements_txt
from app.ai.codegen.types import BackendAdapter, FileResult, ModelCtx, RoutesCtx, WiringCtx
from app.ai.codegen_shared import GROQ_FILE_MAX_TOKENS, GeneratedFile, _slug, generate_text_validated


async def generate_model(ctx: ModelCtx) -> FileResult:
    table_name = ctx.table.get("name", "Item")

    prompt = f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Write ONE complete, real SQLAlchemy model file for the "{table_name}" table of this app.

App: {ctx.project_name}
{ctx.requirements_text}
Table purpose: {ctx.table.get('purpose', '')}
Fields: {', '.join(ctx.table.get('key_fields', []))}

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


async def _rest_routes(ctx: RoutesCtx) -> list[FileResult]:
    endpoints_text = "\n".join(
        f"- {e.get('method')} {e.get('path')}: {e.get('purpose')}" for e in ctx.endpoints
    )
    model_imports = "\n".join(
        f"- backend/models/{_slug(t.get('name', 'item'))}.py defines the {t.get('name')} model"
        for t in ctx.tables
    )

    prompt = f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Write ONE complete, real FastAPI routes file implementing every API endpoint below for this app.

App: {ctx.project_name}
{ctx.requirements_text}
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
    return [(
        GeneratedFile(
            path="backend/routes/api.py",
            language="python",
            content=content,
            description="FastAPI routes implementing all API endpoints against the real models",
        ),
        issue,
    )]


# Keys here are this adapter's actual implemented capability — ADAPTER's
# supported_api_styles below is derived from this dict's keys, never
# hand-maintained separately, so stack_matrix.py's claim and this
# adapter's real capability can't silently drift apart.
ROUTES_BUILDERS = {"rest": _rest_routes}


async def generate_routes(ctx: RoutesCtx) -> list[FileResult]:
    return await ROUTES_BUILDERS[ctx.api_style](ctx)


# backend/models/*.py's AI prompt already tells the model to
# `from app.core.database import Base` (see generate_model above) — this
# is what makes that import resolve for real instead of dangling: a
# minimal async SQLAlchemy setup at exactly that path, SQLite by default
# so the exported project runs with zero external DB setup.
_DATABASE_PY = """from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

DATABASE_URL = "sqlite+aiosqlite:///./app.db"

Base = declarative_base()
engine = create_async_engine(DATABASE_URL)
AsyncSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
"""


def _model_import_name(file: GeneratedFile) -> str:
    return file.path.removeprefix("backend/").removesuffix(".py").replace("/", ".")


def _build_main_py(project_name: str, model_files: list[GeneratedFile]) -> str:
    model_imports = "\n".join(f"import {_model_import_name(f)}  # noqa: F401 — registers the table with Base.metadata" for f in model_files)
    return f"""from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.database import Base, engine
{model_imports}
from routes.api import router as api_router

app = FastAPI(title="{project_name}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.on_event("startup")
async def _create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@app.get("/")
def root():
    return {{"message": "{project_name} API is running"}}
"""


def manifest_files(ctx: WiringCtx) -> list[GeneratedFile]:
    content = build_requirements_txt([
        "fastapi==0.109.2",
        "uvicorn[standard]==0.27.1",
        "sqlalchemy[asyncio]==2.0.27",
        "aiosqlite==0.19.0",
        "pydantic==2.6.1",
        "python-multipart==0.0.7",
    ])
    return [GeneratedFile(path="backend/requirements.txt", language="text", content=content, description="Backend Python dependencies")]


def entry_point_files(ctx: WiringCtx) -> list[GeneratedFile]:
    return [
        GeneratedFile(path="backend/app/core/database.py", language="python", content=_DATABASE_PY, description="Async SQLAlchemy engine/session setup"),
        GeneratedFile(path="backend/main.py", language="python", content=_build_main_py(ctx.project_name, ctx.model_files), description="FastAPI entry point"),
    ]


def setup_commands(project_name: str) -> list[str]:
    return ["cd backend", "pip install -r requirements.txt", "uvicorn main:app --reload"]


ADAPTER = BackendAdapter(
    key="fastapi",
    label="FastAPI",
    supported_languages=("python",),
    supported_api_styles=tuple(ROUTES_BUILDERS),
    generate_model=generate_model,
    generate_routes=generate_routes,
    manifest_files=manifest_files,
    entry_point_files=entry_point_files,
    setup_commands=setup_commands,
)
