# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Gin Backend Adapter
#  ai/codegen/backend/gin.py — Gin + GORM (SQLite). The simplest of the
#  12 backend adapters: Go's package-based visibility means handler
#  functions just need to start with an uppercase letter to be
#  importable from main.go — no separate "pub"-style annotation needed
#  the way Rust required (see actix.py/axum.py's session history),
#  since PascalCase naming and exported visibility are the same thing
#  in Go.
#
#  2026-09-21: added a real "graphql" api_style using graphql-go/graphql
#  (confirmed current v0.8.1 via its own GitHub release while writing
#  this, not guessed) — deliberately NOT gqlgen, despite gqlgen being
#  the more commonly recommended Go GraphQL library: gqlgen is codegen-
#  based (`gqlgen generate` reads a schema + config and WRITES stub
#  resolver files you then fill in), a build-time step that doesn't fit
#  this pipeline's "one AI call produces one complete, final source
#  file" model the way graphql-go/graphql's plain code-first API does —
#  same reasoning that ruled out a codegen tool for any other backend
#  here. The mounting handler (parse {query, variables} JSON, call
#  graphql.Do(), encode the response) is hand-written rather than
#  pulling in the separate graphql-go-handler package, keeping the
#  dependency surface to one real, actively maintained library.
# ═══════════════════════════════════════════════════════════════

import re

from app.ai import db_schema
from app.ai.codegen.types import (
    BackendAdapter,
    FileResult,
    ModelCtx,
    RoutesCtx,
    WiringCtx,
)
from app.ai.codegen_shared import (
    GROQ_FILE_MAX_TOKENS,
    GeneratedFile,
    _pascal,
    _slug,
    generate_text_validated,
)


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

    prompt = f"""Write ONE complete, real Go GORM model struct for the "{table_name}" table of this app.

Table purpose: {ctx.table.get("purpose", "")}
{db_schema.describe_table_for_prompt(ctx.table, ctx.all_tables or [ctx.table])}

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

    content, issue = await generate_text_validated(
        prompt,
        "go",
        GROQ_FILE_MAX_TOKENS,
        user=ctx.user,
        db=ctx.db,
        context=ctx.shared_context(),
    )
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

    prompt = f"""Write ONE complete, real Go file implementing every API endpoint below for this app, as Gin handler factory functions.

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

    content, issue = await generate_text_validated(
        prompt,
        "go",
        GROQ_FILE_MAX_TOKENS,
        user=ctx.user,
        db=ctx.db,
        context=ctx.shared_context(),
    )
    return [
        (
            GeneratedFile(
                path="backend/handlers/api.go",
                language="go",
                content=content,
                description="Gin handlers implementing all API endpoints against the real models",
            ),
            issue,
        )
    ]


async def _graphql_routes(ctx: RoutesCtx) -> list[FileResult]:
    module_name = _module_name(ctx.project_name)
    operations_text = "\n".join(
        f"- (originally {e.get('method')} {e.get('path')}): {e.get('purpose')}"
        for e in ctx.endpoints
    )
    models_text = ", ".join(
        f'{_pascal(t.get("name", "Item"))} (import "{module_name}/models")'
        for t in ctx.tables
    )

    prompt = f"""Write ONE complete, real graphql-go/graphql schema file for this app, covering every capability below.

Available GORM models to use: {models_text}

Capabilities to expose as GraphQL fields (each was originally described as a REST endpoint — turn
each GET-shaped one into a Query field, and each POST/PUT/PATCH/DELETE-shaped one into a Mutation
field, choosing clear, idiomatic lowercase GraphQL field/argument names from its purpose):
{operations_text}

Requirements:
- Package declaration: `package graphql`. Import `"github.com/graphql-go/graphql"` and
  `"gorm.io/gorm"`.
- Define one real `graphql.NewObject(graphql.ObjectConfig{{...}})` per model above, with one
  `graphql.Fields` entry per real column — `Type: graphql.String`/`graphql.Int`/`graphql.Boolean`/
  `graphql.Float` matching the model's real Go field types. Use lowercase GraphQL field names
  (e.g. Go field `Title` -> GraphQL field `title`) — graphql-go's default resolver matches these
  case-insensitively against the struct field name, so do NOT write a `Resolve` function for
  these per-column fields, only for the top-level Query/Mutation fields below.
- Define `func NewSchema(db *gorm.DB) (graphql.Schema, error) {{ ... }}` as the ONLY exported
  entry point. Inside it, build a `queryType := graphql.NewObject(...)` with one field per read
  capability, and (ONLY if at least one write capability exists) a
  `mutationType := graphql.NewObject(...)` with one field per write capability.
- Each Query/Mutation field's `Resolve: func(p graphql.ResolveParams) (interface{{}}, error) {{
  ... }}` MUST do a real read/write against `db` (GORM methods: `db.Find(&results)`,
  `db.First(&result, id)`, `db.Create(&input)`, etc.), returning the REAL model struct(s) from
  models/ directly (e.g. `return tasks, nil` where `tasks []models.Task`) — never hardcoded/fake
  data. Read arguments via `p.Args["argName"]` (type-assert as needed, e.g.
  `p.Args["id"].(string)`).
- Return `graphql.NewSchema(graphql.SchemaConfig{{Query: queryType, Mutation: mutationType}})` (omit
  `Mutation:` entirely if you defined no Mutation type).
- Implement the actual behavior implied by the key features and user stories above.
- No placeholders or TODOs — every field's resolver must be fully implemented.

Return ONLY the raw Go code for this one file (package decl + imports + type/schema construction).
No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(
        prompt,
        "go",
        GROQ_FILE_MAX_TOKENS,
        user=ctx.user,
        db=ctx.db,
        context=ctx.shared_context(),
    )
    return [
        (
            GeneratedFile(
                path=_GRAPHQL_SCHEMA_PATH,
                language="go",
                content=content,
                description="graphql-go/graphql schema implementing every capability against the real models",
            ),
            issue,
        )
    ]


ROUTES_BUILDERS = {"rest": _rest_routes, "graphql": _graphql_routes}


async def generate_routes(ctx: RoutesCtx) -> list[FileResult]:
    return await ROUTES_BUILDERS[ctx.api_style](ctx)


_GRAPHQL_SCHEMA_PATH = "backend/graphql/schema.go"


def _is_graphql(ctx: WiringCtx) -> bool:
    return any(f.path == _GRAPHQL_SCHEMA_PATH for f in ctx.routes_files)


_METHOD_TO_GIN = {
    "GET": "GET",
    "POST": "POST",
    "PUT": "PUT",
    "DELETE": "DELETE",
    "PATCH": "PATCH",
}


def _build_main_go(
    module_name: str, endpoints: list[dict], model_files: list[GeneratedFile]
) -> str:
    struct_names = [f.path.split("/")[-1].removesuffix(".go") for f in model_files]
    struct_names_pascal = [_pascal(s) for s in struct_names]
    automigrate_args = ", ".join(f"&models.{name}{{}}" for name in struct_names_pascal)
    routes = "\n".join(
        f'\tr.{_METHOD_TO_GIN.get(e.get("method", "GET").upper(), "GET")}("{_gin_path(e.get("path", "/"))}", '
        f"handlers.{_view_name(e.get('method', 'GET'), e.get('path', '/'))}(db))"
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


def _go_mod(module_name: str, graphql: bool) -> str:
    # Version confirmed via graphql-go/graphql's own GitHub release at
    # the time this was written.
    graphql_dep = "\n\tgithub.com/graphql-go/graphql v0.8.1" if graphql else ""
    return f"""module {module_name}

go 1.21

require (
\tgithub.com/gin-gonic/gin v1.9.1
\tgorm.io/driver/sqlite v1.5.5
\tgorm.io/gorm v1.25.7{graphql_dep}
)
"""


# The local `graphql` package (schema.go, package `graphql`) and the
# library `github.com/graphql-go/graphql` (conventionally also imported
# as `graphql`) would collide — the library import is aliased `graphqlgo`
# here so both stay unambiguous.
def _build_main_go_graphql(module_name: str, model_files: list[GeneratedFile]) -> str:
    struct_names_pascal = [
        _pascal(f.path.split("/")[-1].removesuffix(".go")) for f in model_files
    ]
    automigrate_args = ", ".join(f"&models.{name}{{}}" for name in struct_names_pascal)

    return f"""package main

import (
\t"log"
\t"net/http"

\t"github.com/gin-gonic/gin"
\tgraphqlgo "github.com/graphql-go/graphql"
\t"gorm.io/driver/sqlite"
\t"gorm.io/gorm"

\t"{module_name}/graphql"
\t"{module_name}/models"
)

type graphqlRequestBody struct {{
\tQuery     string                 `json:"query"`
\tVariables map[string]interface{{}} `json:"variables"`
}}

func main() {{
\tdb, err := gorm.Open(sqlite.Open("app.db"), &gorm.Config{{}})
\tif err != nil {{
\t\tlog.Fatal("failed to connect to database: ", err)
\t}}

\tif err := db.AutoMigrate({automigrate_args}); err != nil {{
\t\tlog.Fatal("failed to migrate database: ", err)
\t}}

\tschema, err := graphql.NewSchema(db)
\tif err != nil {{
\t\tlog.Fatal("failed to build GraphQL schema: ", err)
\t}}

\tr := gin.Default()

\tr.POST("/graphql", func(c *gin.Context) {{
\t\tvar body graphqlRequestBody
\t\tif err := c.ShouldBindJSON(&body); err != nil {{
\t\t\tc.JSON(http.StatusBadRequest, gin.H{{"error": err.Error()}})
\t\t\treturn
\t\t}}
\t\tresult := graphqlgo.Do(graphqlgo.Params{{
\t\t\tSchema:         schema,
\t\t\tRequestString:  body.Query,
\t\t\tVariableValues: body.Variables,
\t\t}})
\t\tc.JSON(http.StatusOK, result)
\t}})

\tr.Run(":8080")
}}
"""


def manifest_files(ctx: WiringCtx) -> list[GeneratedFile]:
    return [
        GeneratedFile(
            path="backend/go.mod",
            language="text",
            content=_go_mod(_module_name(ctx.project_name), _is_graphql(ctx)),
            description="Go module manifest",
        )
    ]


def entry_point_files(ctx: WiringCtx) -> list[GeneratedFile]:
    module_name = _module_name(ctx.project_name)
    main_go = (
        _build_main_go_graphql(module_name, ctx.model_files)
        if _is_graphql(ctx)
        else _build_main_go(module_name, ctx.endpoints, ctx.model_files)
    )
    return [
        GeneratedFile(
            path="backend/main.go",
            language="go",
            content=main_go,
            description="Gin entry point — connects the DB, auto-migrates every model, wires every route/resolver",
        ),
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
