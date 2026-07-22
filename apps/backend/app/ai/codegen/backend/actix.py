# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Actix-web Backend Adapter
#  ai/codegen/backend/actix.py — actix-web + sqlx (SQLite).
# ═══════════════════════════════════════════════════════════════

from app.ai.codegen.backend import rust_common
from app.ai.codegen.types import BackendAdapter, FileResult, RoutesCtx, WiringCtx
from app.ai.codegen_shared import GROQ_FILE_MAX_TOKENS, GeneratedFile, _pascal, generate_text_validated

generate_model = rust_common.generate_model


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

    prompt = f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Write ONE complete, real actix-web handlers file implementing every API endpoint below for this app.

App: {ctx.project_name}
{ctx.requirements_text}
Already-generated data structs to import and use:
{model_imports}

API endpoints to implement (use the EXACT function name given for each — main.rs registers
these exact names as services):
{endpoints_text}

Requirements:
- Every handler function MUST be declared `pub async fn ...` (not just `async fn`) — main.rs
  registers these functions as `handlers::function_name` from a different module, which requires
  `pub` visibility in Rust or the project won't compile.
- Use actix-web's attribute macros exactly matching each endpoint's HTTP method and path, e.g.
  `#[get("/tasks/{{id}}")]` — path parameters use actix's `web::Path<...>` extractor.
- Each handler MUST take `pool: web::Data<sqlx::SqlitePool>` and do real reads/writes via
  `sqlx::query_as`/`sqlx::query` against the real SQLite tables (table names are the pluralized,
  lowercased struct names, e.g. `Task` -> table `tasks`) — do not return hardcoded/fake JSON.
- Return `impl Responder`, using `HttpResponse::Ok().json(...)`, `HttpResponse::NotFound()`,
  `HttpResponse::BadRequest()` etc. with correct status codes for error cases.
- Implement the actual behavior implied by the key features and user stories above.
- No placeholders or TODOs — every handler must be fully implemented.

Return ONLY the raw Rust code for this one file (imports + `use actix_web::{{get, post, put,
delete, web, HttpResponse, Responder}};` + each `#[route_macro]` handler function). No markdown
fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(prompt, "rust", GROQ_FILE_MAX_TOKENS)
    return [(
        GeneratedFile(
            path="backend/src/handlers.rs",
            language="rust",
            content=content,
            description="actix-web handlers implementing all API endpoints against the real database",
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
actix-web = "4"
tokio = {{ version = "1", features = ["full"] }}
serde = {{ version = "1", features = ["derive"] }}
serde_json = "1"
sqlx = {{ version = "0.7", features = ["runtime-tokio", "sqlite"] }}
"""


def _build_main_rs(endpoints: list[dict], tables: list[dict]) -> str:
    create_tables = "\n".join(
        f'    sqlx::query(r#"{rust_common.build_create_table_sql(t)}"#).execute(&pool).await.expect("failed to create table");'
        for t in tables
    )
    services = "\n".join(
        f"            .service(handlers::{rust_common.view_name(e.get('method', 'GET'), e.get('path', '/'))})"
        for e in endpoints
    )

    return f"""use actix_web::{{web, App, HttpServer}};
use sqlx::sqlite::SqlitePoolOptions;

mod handlers;
mod models;

#[actix_web::main]
async fn main() -> std::io::Result<()> {{
    let pool = SqlitePoolOptions::new()
        .connect("sqlite://app.db?mode=rwc")
        .await
        .expect("failed to connect to database");

{create_tables}

    HttpServer::new(move || {{
        App::new()
            .app_data(web::Data::new(pool.clone()))
{services}
    }})
    .bind(("127.0.0.1", 8080))?
    .run()
    .await
}}
"""


def manifest_files(ctx: WiringCtx) -> list[GeneratedFile]:
    return [GeneratedFile(path="backend/Cargo.toml", language="text", content=_cargo_toml(ctx.project_name), description="Rust dependency manifest")]


def entry_point_files(ctx: WiringCtx) -> list[GeneratedFile]:
    return [
        GeneratedFile(path="backend/src/main.rs", language="rust", content=_build_main_rs(ctx.endpoints, ctx.tables), description="actix-web entry point — connects the DB, creates tables, registers every handler"),
        GeneratedFile(path="backend/src/models/mod.rs", language="rust", content=rust_common.models_mod_rs(ctx.model_files), description="Aggregates every generated data struct"),
    ]


def setup_commands(project_name: str) -> list[str]:
    return ["cd backend", "cargo run"]


ADAPTER = BackendAdapter(
    key="actix",
    label="Actix",
    supported_languages=("rust",),
    supported_api_styles=tuple(ROUTES_BUILDERS),
    generate_model=generate_model,
    generate_routes=generate_routes,
    manifest_files=manifest_files,
    entry_point_files=entry_point_files,
    setup_commands=setup_commands,
)
