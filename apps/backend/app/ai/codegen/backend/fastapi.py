# ═══════════════════════════════════════════════════════════════
#  VengaiCode — FastAPI Backend Adapter
#  ai/codegen/backend/fastapi.py — Model/routes generation moved
#  verbatim from the old codegen.py's default branches. No behavior
#  change from the pre-adapter version.
#
#  2026-09-21: added a real "graphql" api_style using Strawberry
#  (strawberry-graphql[fastapi], mounted via strawberry.fastapi.
#  GraphQLRouter at /graphql — both confirmed against Strawberry's
#  current docs while writing this, not guessed). _is_graphql() detects
#  which style was actually generated from the routes file's own path
#  since WiringCtx carries no api_style field by design (see its
#  docstring) — REST and GraphQL never write to the same path, so this
#  is unambiguous.
# ═══════════════════════════════════════════════════════════════

from app.ai.codegen.manifests.requirements_txt import build_requirements_txt
from app.ai.codegen.types import BackendAdapter, FileResult, ModelCtx, RoutesCtx, WiringCtx
from app.ai.codegen_shared import GROQ_FILE_MAX_TOKENS, GeneratedFile, _slug, generate_text_validated


async def generate_model(ctx: ModelCtx) -> FileResult:
    table_name = ctx.table.get("name", "Item")

    prompt = f"""Write ONE complete, real SQLAlchemy model file for the "{table_name}" table of this app.

Table purpose: {ctx.table.get('purpose', '')}
Fields: {', '.join(ctx.table.get('key_fields', []))}

Requirements:
- Real column types, constraints (nullable, unique, defaults) matching the fields above.
- Implement any validation, computed properties, or relationships implied by the key
  features / user stories above — not a bare column list.
- Use SQLAlchemy declarative style importing Base from "app.core.database".
- No placeholders or TODOs — every field and method must be fully implemented.

Return ONLY the raw Python code for this one file. No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(
        prompt, "python", GROQ_FILE_MAX_TOKENS,
        user=ctx.user, db=ctx.db, context=ctx.shared_context(),
    )
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

    prompt = f"""Write ONE complete, real FastAPI routes file implementing every API endpoint below for this app.

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

    content, issue = await generate_text_validated(
        prompt, "python", GROQ_FILE_MAX_TOKENS,
        user=ctx.user, db=ctx.db, context=ctx.shared_context(),
    )
    return [(
        GeneratedFile(
            path="backend/routes/api.py",
            language="python",
            content=content,
            description="FastAPI routes implementing all API endpoints against the real models",
        ),
        issue,
    )]


async def _graphql_routes(ctx: RoutesCtx) -> list[FileResult]:
    model_imports = "\n".join(
        f"- backend/models/{_slug(t.get('name', 'item'))}.py defines the {t.get('name')} model"
        for t in ctx.tables
    )
    operations_text = "\n".join(
        f"- (originally {e.get('method')} {e.get('path')}): {e.get('purpose')}"
        for e in ctx.endpoints
    )

    prompt = f"""Write ONE complete, real Strawberry GraphQL schema file for this app, covering every capability below.

Available models to import and use:
{model_imports}

Capabilities to expose as GraphQL fields (each was originally described as a REST endpoint — turn
each GET-shaped one into a Query field, and each POST/PUT/PATCH/DELETE-shaped one into a Mutation
field, choosing clear, idiomatic GraphQL field/argument names from its purpose):
{operations_text}

Requirements:
- `import strawberry` and open your own database session per-resolver — `from app.core.database
  import AsyncSessionLocal`, then `async with AsyncSessionLocal() as session:` inside each
  resolver. Do NOT rely on FastAPI's `Depends()` — Strawberry resolvers never receive it.
- Define one real `@strawberry.type` output type per model above, with fields matching the
  model's real columns, plus any `@strawberry.input` type a mutation's arguments need.
- Define `class Query:` (decorated `@strawberry.type`) with one `@strawberry.field async def ...`
  method per read capability. ONLY if at least one write capability exists, also define
  `class Mutation:` (decorated `@strawberry.type`) with one `@strawberry.mutation async def ...`
  method per write capability.
- Each resolver MUST do a real read/write against the SQLAlchemy models via the session — never
  return hardcoded/fake data. Raise `Exception("...")` with a clear message for not-found/invalid
  cases (Strawberry turns this into a real GraphQL error for the client).
- Implement the actual behavior implied by the key features and user stories above.
- End the file with `schema = strawberry.Schema(query=Query, mutation=Mutation)` if you defined a
  Mutation type, otherwise `schema = strawberry.Schema(query=Query)`.
- No placeholders or TODOs — every field/method must be fully implemented.

Return ONLY the raw Python code for this one file. No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(
        prompt, "python", GROQ_FILE_MAX_TOKENS,
        user=ctx.user, db=ctx.db, context=ctx.shared_context(),
    )
    return [(
        GeneratedFile(
            path=_GRAPHQL_SCHEMA_PATH,
            language="python",
            content=content,
            description="Strawberry GraphQL schema implementing every capability against the real models",
        ),
        issue,
    )]


# Keys here are this adapter's actual implemented capability — ADAPTER's
# supported_api_styles below is derived from this dict's keys, never
# hand-maintained separately, so stack_matrix.py's claim and this
# adapter's real capability can't silently drift apart.
ROUTES_BUILDERS = {"rest": _rest_routes, "graphql": _graphql_routes}


async def generate_routes(ctx: RoutesCtx) -> list[FileResult]:
    return await ROUTES_BUILDERS[ctx.api_style](ctx)


_GRAPHQL_SCHEMA_PATH = "backend/routes/schema.py"


def _is_graphql(ctx: WiringCtx) -> bool:
    """Detects which api_style was actually generated from the routes
    file's own path — WiringCtx deliberately carries no api_style field
    (see its docstring), so this reads the one thing that's already
    deterministic: _rest_routes/_graphql_routes never write to the same
    path, so the presence of one is unambiguous."""
    return any(f.path == _GRAPHQL_SCHEMA_PATH for f in ctx.routes_files)


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


def _build_main_py(project_name: str, model_files: list[GeneratedFile], graphql: bool) -> str:
    model_imports = "\n".join(f"import {_model_import_name(f)}  # noqa: F401 — registers the table with Base.metadata" for f in model_files)
    if graphql:
        router_import = """from routes.schema import schema
from strawberry.fastapi import GraphQLRouter

graphql_app = GraphQLRouter(schema)"""
        router_mount = 'app.include_router(graphql_app, prefix="/graphql")'
    else:
        router_import = "from routes.api import router as api_router"
        router_mount = "app.include_router(api_router)"

    return f"""from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.database import Base, engine
{model_imports}
{router_import}

app = FastAPI(title="{project_name}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

{router_mount}


@app.on_event("startup")
async def _create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@app.get("/")
def root():
    return {{"message": "{project_name} API is running"}}
"""


def manifest_files(ctx: WiringCtx) -> list[GeneratedFile]:
    packages = [
        "fastapi==0.109.2",
        "uvicorn[standard]==0.27.1",
        "sqlalchemy[asyncio]==2.0.27",
        "aiosqlite==0.19.0",
        "pydantic==2.6.1",
        "python-multipart==0.0.7",
        # Pure-Python, zero dependencies, no C extension (verified: PyPI
        # ships it as a single py3-none-any wheel) — safe to include
        # unconditionally rather than threading a domain flag into
        # WiringCtx, which is deliberately domain-blind (see its
        # docstring in codegen/types.py). Lets DOMAIN_BACKEND_EXTRAS in
        # codegen_shared.py tell a music-player app's model/routes
        # prompts to read real ID3/audio tags via mutagen instead of
        # guessing from the filename, without gambling on an import that
        # was never actually added to the manifest.
        "mutagen==1.48.1",
    ]
    if _is_graphql(ctx):
        # Version confirmed live on PyPI at the time this was written —
        # see PyPI's own release history if this ever needs bumping.
        packages.append("strawberry-graphql[fastapi]==0.327.7")
    content = build_requirements_txt(packages)
    return [GeneratedFile(path="backend/requirements.txt", language="text", content=content, description="Backend Python dependencies")]


def entry_point_files(ctx: WiringCtx) -> list[GeneratedFile]:
    return [
        GeneratedFile(path="backend/app/core/database.py", language="python", content=_DATABASE_PY, description="Async SQLAlchemy engine/session setup"),
        GeneratedFile(
            path="backend/main.py",
            language="python",
            content=_build_main_py(ctx.project_name, ctx.model_files, _is_graphql(ctx)),
            description="FastAPI entry point",
        ),
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
