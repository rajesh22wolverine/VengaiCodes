# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Actix-web Backend Adapter
#  ai/codegen/backend/actix.py — actix-web + sqlx (SQLite).
#
#  2026-09-21: added a real "graphql" api_style using async-graphql +
#  async-graphql-actix-web. Every version/pattern here was verified by
#  actually compiling and running a real actix-web + async-graphql
#  server against a real sqlx pool while writing this (not guessed) —
#  including the ctx.data::<sqlx::SqlitePool>() resolver pattern, which
#  is exactly what generate_screen's own prompt tells the AI to use.
#  GraphQL output types are deliberately separate structs from the
#  sqlx::FromRow models in models/*.rs (SimpleObject vs FromRow are two
#  different derives serving two different concerns — persistence vs.
#  GraphQL wire shape — same separation FastAPI/Django's GraphQL
#  adapters already use).
# ═══════════════════════════════════════════════════════════════

from app.ai.codegen.backend import rust_common
from app.ai.codegen.types import BackendAdapter, FileResult, RoutesCtx, WiringCtx
from app.ai.codegen_shared import (
    GROQ_FILE_MAX_TOKENS,
    GeneratedFile,
    _pascal,
    generate_text_validated,
)

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

    prompt = f"""Write ONE complete, real actix-web handlers file implementing every API endpoint below for this app.

Already-generated data structs to import and use:
{model_imports}

Database tables, created at startup by exactly this SQL (use these table and column names):
{rust_common.schema_sql_for_prompt(ctx.tables)}

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

    content, issue = await generate_text_validated(
        prompt,
        "rust",
        GROQ_FILE_MAX_TOKENS,
        user=ctx.user,
        db=ctx.db,
        context=ctx.shared_context(),
    )
    return [
        (
            GeneratedFile(
                path="backend/src/handlers.rs",
                language="rust",
                content=content,
                description="actix-web handlers implementing all API endpoints against the real database",
            ),
            issue,
        )
    ]


async def _graphql_routes(ctx: RoutesCtx) -> list[FileResult]:
    operations_text = "\n".join(
        f"- (originally {e.get('method')} {e.get('path')}): {e.get('purpose')}"
        for e in ctx.endpoints
    )
    tables_text = ", ".join(
        f"{_pascal(t.get('name', 'Item'))} (table `{t.get('name', 'item').lower()}s`)"
        for t in ctx.tables
    )

    prompt = f"""Write ONE complete, real async-graphql schema file for this app, covering every capability below.

Tables available (real SQLite tables, already created): {tables_text}

They are created at startup by exactly this SQL (use these table and column names, and Rust types
that decode each column's SQL type: TEXT -> String, INTEGER -> i64, REAL -> f64, BOOLEAN -> bool):
{rust_common.schema_sql_for_prompt(ctx.tables)}

Capabilities to expose as GraphQL fields (each was originally described as a REST endpoint — turn
each GET-shaped one into a Query field, and each POST/PUT/PATCH/DELETE-shaped one into a Mutation
field, choosing clear, idiomatic GraphQL field/argument names from its purpose):
{operations_text}

Requirements:
- `use async_graphql::{{Context, Object, SimpleObject, InputObject}};` and `use sqlx::Row;`.
- Define one real `#[derive(SimpleObject)] pub struct XOutput {{ ... }}` per table above (GraphQL
  output shape — pub fields, real types matching the table's real columns), plus any
  `#[derive(InputObject)] pub struct XInput {{ ... }}` a mutation's arguments need. These are
  SEPARATE from any sqlx::FromRow struct elsewhere — do not import or reuse one.
- `pub struct Query;` with `#[Object] impl Query {{ ... }}` — one `async fn` per read capability,
  each taking `&self, ctx: &Context<'_>` (plus any real arguments) and returning
  `async_graphql::Result<...>`. Get the database pool via
  `let pool = ctx.data::<sqlx::SqlitePool>()?;` then do a REAL query
  (`sqlx::query(...).fetch_all(pool).await?` / `.fetch_one(pool).await?`), building the output
  struct(s) field-by-field from each row via `row.try_get::<T, _>("column")?` — never return
  hardcoded/fake data.
- `pub struct Mutation;` with `#[Object] impl Mutation {{ ... }}` — one `async fn` per write
  capability, same `ctx: &Context<'_>` + pool pattern, doing a real `sqlx::query(...).execute(pool)
  .await?`. If there are NO write capabilities above, define exactly one trivial field:
  `async fn ping(&self) -> bool {{ true }}` — Mutation must always exist and have at least one
  field, even when unused.
- For not-found/invalid-input cases, return `Err(async_graphql::Error::new("..."))` with a clear
  message.
- Implement the actual behavior implied by the key features and user stories above.
- No placeholders or TODOs — every field/resolver must be fully implemented.

Return ONLY the raw Rust code for this one file (imports + output/input structs + Query + Mutation).
No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(
        prompt,
        "rust",
        GROQ_FILE_MAX_TOKENS,
        user=ctx.user,
        db=ctx.db,
        context=ctx.shared_context(),
    )
    return [
        (
            GeneratedFile(
                path=_GRAPHQL_SCHEMA_PATH,
                language="rust",
                content=content,
                description="async-graphql schema implementing every capability against the real database",
            ),
            issue,
        )
    ]


ROUTES_BUILDERS = {"rest": _rest_routes, "graphql": _graphql_routes}


async def generate_routes(ctx: RoutesCtx) -> list[FileResult]:
    return await ROUTES_BUILDERS[ctx.api_style](ctx)


_GRAPHQL_SCHEMA_PATH = "backend/src/schema.rs"


def _is_graphql(ctx: WiringCtx) -> bool:
    return any(f.path == _GRAPHQL_SCHEMA_PATH for f in ctx.routes_files)


def _cargo_toml(project_name: str, graphql: bool) -> str:
    from app.core.naming import slugify_app_name

    graphql_deps = (
        '\nasync-graphql = "7.2.1"\nasync-graphql-actix-web = "7.2.1"'
        if graphql
        else ""
    )
    return f"""[package]
name = "{slugify_app_name(project_name).replace("-", "_")}"
version = "0.1.0"
edition = "2021"

[dependencies]
actix-web = "4"
tokio = {{ version = "1", features = ["full"] }}
serde = {{ version = "1", features = ["derive"] }}
serde_json = "1"
sqlx = {{ version = "0.7", features = ["runtime-tokio", "sqlite"] }}{graphql_deps}
"""


def _build_main_rs(endpoints: list[dict], tables: list[dict]) -> str:
    create_tables = rust_common.create_tables_block(tables)
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


# GraphiQL served on GET /graphql, real queries/mutations on POST /graphql —
# same shape as the actix.py header documents was actually compiled and run.
def _build_main_rs_graphql(tables: list[dict]) -> str:
    create_tables = rust_common.create_tables_block(tables)

    return f"""use actix_web::{{guard, web, App, HttpResponse, HttpServer}};
use async_graphql::{{EmptySubscription, Schema}};
use async_graphql_actix_web::{{GraphQLRequest, GraphQLResponse}};
use sqlx::sqlite::SqlitePoolOptions;

mod models;
mod schema;

use schema::{{Mutation, Query}};

type AppSchema = Schema<Query, Mutation, EmptySubscription>;

async fn graphql_handler(schema: web::Data<AppSchema>, req: GraphQLRequest) -> GraphQLResponse {{
    schema.execute(req.into_inner()).await.into()
}}

async fn graphiql() -> HttpResponse {{
    HttpResponse::Ok()
        .content_type("text/html; charset=utf-8")
        .body(async_graphql::http::GraphiQLSource::build().endpoint("/graphql").finish())
}}

#[actix_web::main]
async fn main() -> std::io::Result<()> {{
    let pool = SqlitePoolOptions::new()
        .connect("sqlite://app.db?mode=rwc")
        .await
        .expect("failed to connect to database");

{create_tables}

    let schema: AppSchema = Schema::build(Query, Mutation, EmptySubscription)
        .data(pool.clone())
        .finish();

    HttpServer::new(move || {{
        App::new()
            .app_data(web::Data::new(schema.clone()))
            .service(web::resource("/graphql").guard(guard::Post()).to(graphql_handler))
            .service(web::resource("/graphql").guard(guard::Get()).to(graphiql))
    }})
    .bind(("127.0.0.1", 8080))?
    .run()
    .await
}}
"""


# Migrations mode (the deterministic generator only — see
# rust_common.migrations_main_rs): the tables come from src/migrate.rs,
# every table's routes from routes::configure, and the screens' cross-origin
# calls (a packaged app's window isn't the API's origin) are allowed.
_MIGRATIONS_SERVE = """    HttpServer::new(move || {
        App::new()
            .wrap(Cors::permissive())
            .app_data(web::Data::new(pool.clone()))
            .route("/", web::get().to(root))
            .configure(routes::configure)
    })
    .bind(("127.0.0.1", port))?
    .run()
    .await"""

_MIGRATIONS_ROOT = """async fn root() -> HttpResponse {
    HttpResponse::Ok().json(serde_json::json!({ "message": ROOT_MESSAGE }))
}
"""


def manifest_files(ctx: WiringCtx, migrations: bool = False) -> list[GeneratedFile]:
    content = (
        rust_common.migrations_cargo_toml(
            ctx.project_name, ['actix-cors = "0.7"', 'actix-web = "4"']
        )
        if migrations
        else _cargo_toml(ctx.project_name, _is_graphql(ctx))
    )
    return [
        GeneratedFile(
            path="backend/Cargo.toml",
            language="text",
            content=content,
            description="Rust dependency manifest",
        )
    ]


def entry_point_files(ctx: WiringCtx, migrations: bool = False) -> list[GeneratedFile]:
    if migrations:
        # models/mod.rs and routes/mod.rs come with the models (codegen_rust).
        return [
            GeneratedFile(
                path="backend/src/main.rs",
                language="rust",
                content=rust_common.migrations_main_rs(
                    ctx.project_name,
                    [
                        "use actix_cors::Cors;",
                        "use actix_web::{web, App, HttpResponse, HttpServer};",
                    ],
                    "#[actix_web::main]",
                    " -> std::io::Result<()>",
                    _MIGRATIONS_SERVE,
                    _MIGRATIONS_ROOT,
                ),
                description="actix-web entry point — applies pending migrations, then serves every table's routes",
            )
        ]
    main_rs = (
        _build_main_rs_graphql(ctx.tables)
        if _is_graphql(ctx)
        else _build_main_rs(ctx.endpoints, ctx.tables)
    )
    return [
        GeneratedFile(
            path="backend/src/main.rs",
            language="rust",
            content=main_rs,
            description="actix-web entry point — connects the DB, creates tables, wires every handler/resolver",
        ),
        GeneratedFile(
            path="backend/src/models/mod.rs",
            language="rust",
            content=rust_common.models_mod_rs(ctx.model_files),
            description="Aggregates every generated data struct",
        ),
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
