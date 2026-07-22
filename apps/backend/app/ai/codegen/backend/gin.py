# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Gin Backend Adapter
#  ai/codegen/backend/gin.py — Gin + GORM (SQLite). The simplest of the
#  12 backend adapters: Go's package-based visibility means handler
#  functions just need to start with an uppercase letter to be
#  importable from main.go — no separate "pub"-style annotation needed
#  the way Rust required (see actix.py/axum.py's session history),
#  since PascalCase naming and exported visibility are the same thing
#  in Go.
# ═══════════════════════════════════════════════════════════════

import re

from app.ai.codegen.types import BackendAdapter, FileResult, ModelCtx, RoutesCtx, WiringCtx
from app.ai.codegen_shared import GROQ_FILE_MAX_TOKENS, GeneratedFile, _pascal, _slug, generate_text_validated


def _view_name(method: str, path: str) -> str:
    return _pascal(f"{method}_{path.strip('/')}") or "Root"


def _gin_path(path: str) -> str:
    """'/tasks/{id}' -> '/tasks/:id' (Gin's route-param syntax)."""
    return "/" + re.sub(r"\{(\w+)\}", r":\1", path.strip("/"))


def _module_name(project_name: str) -> str:
    from app.core.naming import slugify_app_name

    return slugify_app_name(project_name).replace("-", "")


async def generate_model(ctx: ModelCtx) -> FileResult:
    table_name = ctx.table.get("name", "Item")
    struct_name = _pascal(table_name)

    prompt = f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Write ONE complete, real Go GORM model struct for the "{table_name}" table of this app.

App: {ctx.project_name}
{ctx.requirements_text}
Table purpose: {ctx.table.get('purpose', '')}
Fields: {', '.join(ctx.table.get('key_fields', []))}

Requirements:
- Package declaration: `package models`
- Struct name: {struct_name}, with `ID uint \\`json:"id" gorm:"primaryKey"\\`` plus real
  exported fields (PascalCase, correct Go types) matching the fields above, each with a
  `json:"..."` tag (snake_case or camelCase JSON key) and appropriate `gorm:"..."` tag
  (e.g. `gorm:"not null"` for required fields).
- Implement any validation logic implied by the key features / user stories above as a real
  method on {struct_name} (e.g. `func (t *{struct_name}) Validate() error`), not a placeholder.
- No placeholders or TODOs — every field and method must be fully implemented.

Return ONLY the raw Go code for this one file. No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(prompt, "go", GROQ_FILE_MAX_TOKENS)
    return GeneratedFile(
        path=f"backend/models/{_slug(table_name)}.go",
        language="go",
        content=content,
        description=f"GORM model for {table_name}",
    ), issue


async def _rest_routes(ctx: RoutesCtx) -> list[FileResult]:
    module_name = _module_name(ctx.project_name)
    endpoints_text = "\n".join(
        f"- {e.get('method')} {e.get('path')}: {e.get('purpose')} "
        f"(exported function name: `{_view_name(e.get('method', 'GET'), e.get('path', '/'))}`)"
        for e in ctx.endpoints
    )
    models_text = ", ".join(_pascal(t.get("name", "Item")) for t in ctx.tables)

    prompt = f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Write ONE complete, real Go file implementing every API endpoint below for this app, as Gin handler factory functions.

App: {ctx.project_name}
{ctx.requirements_text}
Available GORM models to use (import "{module_name}/models"): {models_text}

API endpoints to implement (use the EXACT function name given for each — main.go registers
these exact names as routes):
{endpoints_text}

Requirements:
- Package declaration: `package handlers`
- Every endpoint is a function with this EXACT shape: `func {{ExactName}}(db *gorm.DB) gin.HandlerFunc {{
  return func(c *gin.Context) {{ ... }} }}` — a factory function taking the DB and returning the
  real Gin handler closure.
- Each handler MUST do real reads/writes against `db` (GORM methods: `db.Find(&results)`,
  `db.First(&result, id)`, `db.Create(&input)`, etc.) — do not return hardcoded/fake JSON. Use
  `c.JSON(http.StatusOK, ...)` etc. with correct HTTP status codes for error cases (404 via
  `c.JSON(http.StatusNotFound, gin.H{{"error": "..."}})`, etc.).
- Any route param (e.g. from a path like "/tasks/{{id}}") is available via `c.Param("id")`.
- Implement the actual behavior implied by the key features and user stories above.
- No placeholders or TODOs — every function must be fully implemented.

Return ONLY the raw Go code for this one file (package decl + imports + each handler factory
function). No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(prompt, "go", GROQ_FILE_MAX_TOKENS)
    return [(
        GeneratedFile(
            path="backend/handlers/api.go",
            language="go",
            content=content,
            description="Gin handlers implementing all API endpoints against the real models",
        ),
        issue,
    )]


ROUTES_BUILDERS = {"rest": _rest_routes}


async def generate_routes(ctx: RoutesCtx) -> list[FileResult]:
    return await ROUTES_BUILDERS[ctx.api_style](ctx)


_METHOD_TO_GIN = {"GET": "GET", "POST": "POST", "PUT": "PUT", "DELETE": "DELETE", "PATCH": "PATCH"}


def _build_main_go(module_name: str, endpoints: list[dict], model_files: list[GeneratedFile]) -> str:
    struct_names = [f.path.split("/")[-1].removesuffix(".go") for f in model_files]
    struct_names_pascal = [_pascal(s) for s in struct_names]
    automigrate_args = ", ".join(f"&models.{name}{{}}" for name in struct_names_pascal)
    routes = "\n".join(
        f'\tr.{_METHOD_TO_GIN.get(e.get("method", "GET").upper(), "GET")}("{_gin_path(e.get("path", "/"))}", '
        f'handlers.{_view_name(e.get("method", "GET"), e.get("path", "/"))}(db))'
        for e in endpoints
    )

    return f"""package main

import (
\t"log"

\t"github.com/gin-gonic/gin"
\t"gorm.io/driver/sqlite"
\t"gorm.io/gorm"

\t"{module_name}/handlers"
\t"{module_name}/models"
)

func main() {{
\tdb, err := gorm.Open(sqlite.Open("app.db"), &gorm.Config{{}})
\tif err != nil {{
\t\tlog.Fatal("failed to connect to database: ", err)
\t}}

\tif err := db.AutoMigrate({automigrate_args}); err != nil {{
\t\tlog.Fatal("failed to migrate database: ", err)
\t}}

\tr := gin.Default()

{routes}

\tr.Run(":8080")
}}
"""


def _go_mod(module_name: str) -> str:
    return f"""module {module_name}

go 1.21

require (
\tgithub.com/gin-gonic/gin v1.9.1
\tgorm.io/driver/sqlite v1.5.5
\tgorm.io/gorm v1.25.7
)
"""


def manifest_files(ctx: WiringCtx) -> list[GeneratedFile]:
    return [GeneratedFile(path="backend/go.mod", language="text", content=_go_mod(_module_name(ctx.project_name)), description="Go module manifest")]


def entry_point_files(ctx: WiringCtx) -> list[GeneratedFile]:
    module_name = _module_name(ctx.project_name)
    return [
        GeneratedFile(path="backend/main.go", language="go", content=_build_main_go(module_name, ctx.endpoints, ctx.model_files), description="Gin entry point — connects the DB, auto-migrates every model, registers every route"),
    ]


def setup_commands(project_name: str) -> list[str]:
    return ["cd backend", "go mod tidy", "go run main.go"]


ADAPTER = BackendAdapter(
    key="gin",
    label="Gin",
    supported_languages=("go",),
    supported_api_styles=tuple(ROUTES_BUILDERS),
    generate_model=generate_model,
    generate_routes=generate_routes,
    manifest_files=manifest_files,
    entry_point_files=entry_point_files,
    setup_commands=setup_commands,
)
