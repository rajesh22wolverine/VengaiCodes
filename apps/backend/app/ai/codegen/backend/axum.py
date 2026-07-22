# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Axum Backend Adapter
#  ai/codegen/backend/axum.py — axum + sqlx (SQLite). Shares its model
#  struct generation with actix.py via rust_common.py (a plain serde/
#  sqlx struct is identical either way); routes/wiring are axum-
#  specific since its router API (State extractor, .route().get().post()
#  chaining) differs meaningfully from actix's macro-attribute style.
# ═══════════════════════════════════════════════════════════════

import re
from collections import defaultdict

from app.ai.codegen.backend import rust_common
from app.ai.codegen.types import BackendAdapter, FileResult, RoutesCtx, WiringCtx
from app.ai.codegen_shared import GROQ_FILE_MAX_TOKENS, GeneratedFile, _pascal, generate_text_validated

generate_model = rust_common.generate_model


def _axum_path(path: str) -> str:
    """'/tasks/{id}' -> '/tasks/:id' (axum's route-param syntax)."""
    return "/" + re.sub(r"\{(\w+)\}", r":\1", path.strip("/"))


async def _rest_routes(ctx: RoutesCtx) -> list[FileResult]:
    endpoints_text = "\n".join(
        f"- {e.get('method')} {e.get('path')}: {e.get('purpose')} "
        f"(function name: `{rust_common.view_name(e.get('method', 'GET'), e.get('path', '/'))}`)"
        for e in ctx.endpoints
    )
    model_imports = "\n".join(
        f"- crate::models::{t.get('name', 'item').lower()}::{{{_pascal(t.get('name', 'Item'))}, {_pascal(t.get('name', 'Item'))}Input}}"
        for t in ctx.tables
    )

    prompt = f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Write ONE complete, real axum handlers file implementing every API endpoint below for this app.

App: {ctx.project_name}
{ctx.requirements_text}
Already-generated data structs to import and use:
{model_imports}

API endpoints to implement (use the EXACT function name given for each — main.rs registers
these exact names on the router):
{endpoints_text}

Requirements:
- Every handler function MUST be declared `pub async fn ...` (not just `async fn`) — main.rs
  calls these functions as `handlers::function_name` from a different module, which requires
  `pub` visibility in Rust or the project won't compile.
- Each handler function's EXACT signature must start with `State(pool): State<sqlx::SqlitePool>`
  as its first extractor argument (`use axum::extract::State;`), followed by
  `Path(id): Path<i64>` (`use axum::extract::Path;`) for any path parameter, followed by
  `Json(input): Json<...Input>` (`use axum::Json;`) for POST/PUT bodies.
- Each handler MUST do real reads/writes via `sqlx::query_as`/`sqlx::query` against the real
  SQLite tables (table names are the pluralized, lowercased struct names, e.g. `Task` -> table
  `tasks`) — do not return hardcoded/fake JSON.
- Return `Result<Json<...>, axum::http::StatusCode>` (or `Result<(axum::http::StatusCode,
  Json<...>), axum::http::StatusCode>` when you need a non-200 success status), mapping real
  error cases to the correct `StatusCode` (NOT_FOUND, BAD_REQUEST, etc.).
- Implement the actual behavior implied by the key features and user stories above.
- No placeholders or TODOs — every handler must be fully implemented.

Return ONLY the raw Rust code for this one file (imports + each handler function, no `mod`/
`fn main`). No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(prompt, "rust", GROQ_FILE_MAX_TOKENS)
    return [(
        GeneratedFile(
            path="backend/src/handlers.rs",
            language="rust",
            content=content,
            description="axum handlers implementing all API endpoints against the real database",
        ),
        issue,
    )]


ROUTES_BUILDERS = {"rest": _rest_routes}


async def generate_routes(ctx: RoutesCtx) -> list[FileResult]:
    return await ROUTES_BUILDERS[ctx.api_style](ctx)


def _cargo_toml(project_name: str) -> str:
    from app.core.naming import slugify_app_name

    return f"""[package]
name = "{slugify_app_name(project_name).replace('-', '_')}"
version = "0.1.0"
edition = "2021"

[dependencies]
axum = "0.7"
tokio = {{ version = "1", features = ["full"] }}
serde = {{ version = "1", features = ["derive"] }}
serde_json = "1"
sqlx = {{ version = "0.7", features = ["runtime-tokio", "sqlite"] }}
"""


_METHOD_TO_AXUM_FN = {"GET": "get", "POST": "post", "PUT": "put", "DELETE": "delete", "PATCH": "patch"}


def _build_main_rs(endpoints: list[dict], tables: list[dict]) -> str:
    create_tables = "\n".join(
        f'    sqlx::query(r#"{rust_common.build_create_table_sql(t)}"#).execute(&pool).await.expect("failed to create table");'
        for t in tables
    )

    by_path: dict[str, list[dict]] = defaultdict(list)
    for e in endpoints:
        by_path[_axum_path(e.get("path", "/"))].append(e)

    route_lines = []
    for path, group in by_path.items():
        chain = "".join(
            f'.{_METHOD_TO_AXUM_FN.get(e.get("method", "GET").upper(), "get")}'
            f'(handlers::{rust_common.view_name(e.get("method", "GET"), e.get("path", "/"))})'
            for e in group
        )
        route_lines.append(f'        .route("{path}", {chain[1:]})' if chain else "")
    routes = "\n".join(line for line in route_lines if line)

    return f"""use axum::Router;
use axum::routing::{{delete, get, patch, post, put}};
use sqlx::sqlite::SqlitePoolOptions;

mod handlers;
mod models;

#[tokio::main]
async fn main() {{
    let pool = SqlitePoolOptions::new()
        .connect("sqlite://app.db?mode=rwc")
        .await
        .expect("failed to connect to database");

{create_tables}

    let app = Router::new()
{routes}
        .with_state(pool);

    let listener = tokio::net::TcpListener::bind("127.0.0.1:8080").await.unwrap();
    axum::serve(listener, app).await.unwrap();
}}
"""


def manifest_files(ctx: WiringCtx) -> list[GeneratedFile]:
    return [GeneratedFile(path="backend/Cargo.toml", language="text", content=_cargo_toml(ctx.project_name), description="Rust dependency manifest")]


def entry_point_files(ctx: WiringCtx) -> list[GeneratedFile]:
    return [
        GeneratedFile(path="backend/src/main.rs", language="rust", content=_build_main_rs(ctx.endpoints, ctx.tables), description="axum entry point — connects the DB, creates tables, wires the router"),
        GeneratedFile(path="backend/src/models/mod.rs", language="rust", content=rust_common.models_mod_rs(ctx.model_files), description="Aggregates every generated data struct"),
    ]


def setup_commands(project_name: str) -> list[str]:
    return ["cd backend", "cargo run"]


ADAPTER = BackendAdapter(
    key="axum",
    label="Axum",
    supported_languages=("rust",),
    supported_api_styles=tuple(ROUTES_BUILDERS),
    generate_model=generate_model,
    generate_routes=generate_routes,
    manifest_files=manifest_files,
    entry_point_files=entry_point_files,
    setup_commands=setup_commands,
)
