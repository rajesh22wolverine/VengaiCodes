# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Deterministic (no-AI) Rust backends: Actix Web and Axum
#  over sqlx + SQLite
#  ai/codegen_rust.py — The Actix and Axum backends codegen_deterministic
#  dispatches to. Everything below the web layer is the same Rust for
#  both, so it's written once: per table a model module (the row struct
#  the API answers with, the request struct, validation and the SQL),
#  plus fields.rs (request/response value types) and most of error.rs.
#  Only the route modules and the error type's response impl differ.
#
#  Follows the knowledge registry's Rust rules: the pool is shared
#  through application state, errors are one ApiError type implementing
#  the framework's response trait, serde derives for JSON, sqlx::FromRow
#  for rows, async database calls only, no .unwrap() in a handler.
#
#  Same REST surface as every other generated backend: /api/<table> and
#  /api/<table>/<id>, JSON keyed by column name, PUT changes only the
#  fields it sends (a Patch field tells "left out" from "sent as null"),
#  the database's constraint violations answered with the same sentences
#  (409 duplicate, 422 broken rule), a missing parent 422, a refused
#  delete 409. Errors are {"detail": ...}, which the screens read.
#
#  The schema is owned by the SQL migrations (migrations_sqlite, applied
#  by the app's src/migrate.rs), so the column types here are the ones
#  sqlx can decode from what those tables store — see migrations_sqlite.
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations

from app.ai import db_schema, knowledge
from app.ai.codegen_shared import GeneratedFile
from app.ai.migrations_sqlite import q

FRAMEWORKS = ("actix", "axum")

# Names a model module imports (a table whose struct would be called one
# of these is refused — see name_problems).
IMPORTED_NAMES = frozenset({"ApiError", "SqliteArguments", "SqlitePool"})
# A module can't be named these even as a raw identifier (r#…), and
# models/mod.rs is the module list itself.
_UNUSABLE_MODULES = frozenset({"self", "super", "crate", "mod"})

# Rust type of a column in the row struct (what sqlx decodes) …
_ROW_TYPE = {
    "string": "String",
    "text": "String",
    "integer": "i64",
    "float": "f64",
    "decimal": "f64",
    "boolean": "bool",
    "date": "String",
    "datetime": "fields::Timestamp",
    "json": "fields::JsonText",
}
# … and in the request struct (what serde reads and checks).
_INPUT_TYPE = {
    "string": "String",
    "text": "String",
    "integer": "i64",
    "float": "f64",
    "decimal": "fields::DecimalValue",
    "boolean": "bool",
    "date": "fields::DateValue",
    "datetime": "fields::DateTimeValue",
    "json": "serde_json::Value",
}
# Request value (an Option of the input type) -> the value bound for SQL.
_BIND = {
    "decimal": "value.map(|v| v.0)",
    "date": "value.map(|v| v.0)",
    "datetime": "value.map(|v| v.0)",
    "json": "value.map(|v| v.to_string())",
}
# A present request value (a reference) -> (bound value, displayed value).
_REF_VALUE = {
    "string": ("value.clone()", "value"),
    "text": ("value.clone()", "value"),
    "integer": ("*value", "value"),
    "float": ("*value", "value"),
    "decimal": ("value.0", "value.0"),
    "boolean": ("*value", "value"),
    "date": ("value.0.clone()", "value.0"),
    "datetime": ("value.0.clone()", "value.0"),
    "json": ("value.to_string()", "value"),
}


# ───────────────────────────────────────────────
#  Rust text helpers
# ───────────────────────────────────────────────
def rust_str(text: str) -> str:
    """A Rust string literal for user text. "TODO" is written with an
    escape (same string at runtime) so the generated-file check, which
    looks for leftover TODO markers, doesn't flag a table's name."""
    out = []
    for ch in str(text):
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20 or ch == "\x7f":
            out.append(f"\\u{{{ord(ch):x}}}")
        else:
            out.append(ch)
    return '"' + "".join(out).replace("TODO", "TOD\\u{4f}") + '"'


def rust_fmt(text: str) -> str:
    """rust_str for text used as (part of) a format! string."""
    return rust_str(str(text).replace("{", "{{").replace("}", "}}"))


def doc(text: str) -> str:
    """User text on one comment line."""
    return " ".join(str(text or "").split()).replace("TODO", "to-do")


def module_name(slug: str) -> str:
    """A table's module: its slug, raw (r#type) when that's a keyword."""
    lang = knowledge.language("rust")
    return f"r#{slug}" if lang and knowledge.is_keyword(slug, lang) else slug


def _sql(text: str) -> str:
    return rust_str(text)


def name_problems(schema: db_schema.ResolvedSchema) -> list[str]:
    problems = []
    for t in schema.tables:
        if t.slug in _UNUSABLE_MODULES:
            problems.append(
                f'The table "{t.name}" would need a Rust module named `{t.slug}`, which Rust '
                "doesn't allow — rename the table in Architecture."
            )
        for name in (t.class_name, f"{t.class_name}Input"):
            if name in IMPORTED_NAMES:
                problems.append(
                    f'The table "{t.name}" would produce a struct named {name}, a name the generated '
                    "code already uses — rename the table in Architecture."
                )
    return problems


def _base(col: dict, tables: dict) -> dict:
    """A foreign key column has the type of the column it points at."""
    fk = col.get("fk")
    if not fk:
        return col
    if fk["column"] == "id":
        return {"type": "integer", "length": None}
    return _base(tables[fk["table"]]["columns"][fk["column"]], tables)


def _restrict_message(sql_name: str, snapshot: dict) -> str:
    blockers = sorted(
        {
            other["label"]
            for other in snapshot["tables"].values()
            for col in other["columns"].values()
            if col["fk"]
            and col["fk"]["table"] == sql_name
            and col["fk"]["on_delete"] == "restrict"
        }
    )
    if blockers:
        return f"Can't delete this record: {', '.join(blockers)} still refer to it."
    return "Can't delete this record: other records still refer to it."


# ───────────────────────────────────────────────
#  models/<table>.rs — the same for both frameworks
# ───────────────────────────────────────────────
def model_file(
    t: db_schema.ResolvedTable, snapshot: dict, heading: str
) -> GeneratedFile:
    tables = snapshot["tables"]
    table = tables[t.sql_name]
    name = t.class_name
    columns = table["column_order"]
    quoted = ", ".join(q(c) for c in ["id", *columns, "created_at", "updated_at"])
    select = f"SELECT {quoted} FROM {q(t.sql_name)}"

    row = ["    pub id: i64,"]
    inputs: list[str] = []
    checks: list[str] = []
    references: list[str] = []
    assigns: list[str] = []
    needs_creating = False
    for c in columns:
        col = table["columns"][c]
        base = _base(col, tables)
        kind = base["type"]
        row_type = _ROW_TYPE[kind]
        row.append(
            f"    pub {c}: {f'Option<{row_type}>' if col['nullable'] else row_type},"
        )
        inputs += [
            '    #[serde(default, deserialize_with = "fields::present")]',
            f"    pub {c}: fields::Patch<{_INPUT_TYPE[kind]}>,",
        ]
        if not col["nullable"] and col["default"] is None:
            needs_creating = True
            checks.append(
                f"        fields::required(&self.{c}, {rust_str(c)}, creating, &mut errors);"
            )
        elif not col["nullable"]:
            checks.append(
                f"        fields::not_null(&self.{c}, {rust_str(c)}, &mut errors);"
            )
        if kind == "string" and base.get("length"):
            checks.append(
                f"        fields::max_chars(&self.{c}, {base['length']}, {rust_str(c)}, &mut errors);"
            )
        assigns += [
            f"        if let Some(value) = self.{c} {{",
            f"            columns.push({rust_str(q(c))});",
            f"            values.add({_BIND.get(kind, 'value')}).map_err(ApiError::internal)?;",
            "        }",
        ]
        if col["fk"]:
            fk = col["fk"]
            target = tables[fk["table"]]
            bind, shown = _REF_VALUE[kind]
            message = f"{c}: no row in {target['label']} has {fk['column']} "
            references += [
                f"        if let Some(Some(value)) = &self.{c} {{",
                "            let found: Option<i64> = sqlx::query_scalar("
                + _sql(f"SELECT 1 FROM {q(fk['table'])} WHERE {q(fk['column'])} = ?")
                + ")",
                f"                .bind({bind})",
                "                .fetch_optional(pool)",
                "                .await",
                "                .map_err(ApiError::from_db)?;",
                "            if found.is_none() {",
                "                return Err(ApiError::new(",
                "                    422,",
                f'                    format!({rust_fmt(message)[:-1]}{{}}.", {shown}),',
                "                ));",
                "            }",
                "        }",
            ]
    row += [
        "    pub created_at: fields::Timestamp,",
        "    pub updated_at: fields::Timestamp,",
    ]

    creating = "creating" if needs_creating else "_creating"
    if checks:
        validate_body = ["        let mut errors = Vec::new();", *checks]
    else:
        validate_body = ["        let errors = Vec::new();"]
    if assigns:
        assign_body = [
            "        let mut columns = Vec::new();",
            "        let mut values = SqliteArguments::default();",
            *assigns,
            "        Ok((columns, values))",
        ]
    else:
        assign_body = ["        Ok((Vec::new(), SqliteArguments::default()))"]
    reference_call = ["    input.check_references(pool).await?;"] if references else []
    reference_fn = (
        [
            "",
            "    /// Every foreign key it sets must point at a row that exists (a 422",
            "    /// naming the field, instead of the database's bare refusal).",
            "    async fn check_references(&self, pool: &SqlitePool) -> Result<(), ApiError> {",
            *references,
            "        Ok(())",
            "    }",
        ]
        if references
        else []
    )
    table_sql = q(t.sql_name)
    lines = [
        f"//! {doc(heading)}",
        "//!",
        "//! Deterministically generated by VengaiCode from the Architecture tab (no AI",
        "//! call). The table is created and changed by the migrations in migrations/,",
        "//! which the app applies as it starts (src/migrate.rs).",
        "",
        "use crate::error::ApiError;",
        "use crate::fields;",
        "use sqlx::sqlite::{SqliteArguments, SqlitePool};",
        "use sqlx::Arguments as _;",
        "",
        f"const LABEL: &str = {rust_str(table['label'])};",
        f"const RESTRICT_MESSAGE: &str = {rust_str(_restrict_message(t.sql_name, snapshot))};",
        f"const LIST_SQL: &str = {_sql(select + ' ORDER BY ' + q('id'))};",
        f"const FIND_SQL: &str = {_sql(select + ' WHERE ' + q('id') + ' = ?')};",
        f"const DELETE_SQL: &str = {_sql(f'DELETE FROM {table_sql} WHERE ' + q('id') + ' = ?')};",
        "",
        f"/// One row of {doc(table['label'])} as the API answers it — keyed by column name.",
        "#[derive(Debug, Clone, serde::Serialize, sqlx::FromRow)]",
        f"pub struct {name} {{",
        *row,
        "}",
        "",
        f"/// The body of POST and PUT /api/{doc(t.sql_name)}. A field left out is None (the",
        "/// database default applies, or PUT keeps the value); one sent as null is",
        "/// Some(None), which a required field refuses.",
        "#[derive(Debug, Default, serde::Deserialize)]",
        f"pub struct {name}Input {{",
        *inputs,
        "}",
        "",
        f"impl {name}Input {{",
        "    /// Every problem with the request at once, as one 422.",
        f"    fn validate(&self, {creating}: bool) -> Result<(), ApiError> {{",
        *validate_body,
        "        fields::finish(errors)",
        "    }",
        *reference_fn,
        "",
        "    /// The columns this request sets, with their values in the same order.",
        "    fn assignments<'q>(self) -> Result<(Vec<&'static str>, SqliteArguments<'q>), ApiError> {",
        *assign_body,
        "    }",
        "}",
        "",
        f"pub async fn list(pool: &SqlitePool) -> Result<Vec<{name}>, ApiError> {{",
        "    sqlx::query_as(LIST_SQL).fetch_all(pool).await.map_err(ApiError::from_db)",
        "}",
        "",
        f"pub async fn find(pool: &SqlitePool, id: i64) -> Result<{name}, ApiError> {{",
        "    sqlx::query_as(FIND_SQL)",
        "        .bind(id)",
        "        .fetch_optional(pool)",
        "        .await",
        "        .map_err(ApiError::from_db)?",
        "        .ok_or_else(|| ApiError::not_found(LABEL, id))",
        "}",
        "",
        f"pub async fn create(pool: &SqlitePool, input: {name}Input) -> Result<{name}, ApiError> {{",
        "    input.validate(true)?;",
        *reference_call,
        "    let (columns, values) = input.assignments()?;",
        "    let sql = if columns.is_empty() {",
        f"        {_sql(f'INSERT INTO {table_sql} DEFAULT VALUES')}.to_string()",
        "    } else {",
        "        format!(",
        f'            {rust_fmt(f"INSERT INTO {table_sql} (")[:-1]}{{}}) VALUES ({{}})",',
        '            columns.join(", "),',
        '            vec!["?"; columns.len()].join(", ")',
        "        )",
        "    };",
        "    let done = sqlx::query_with(&sql, values)",
        "        .execute(pool)",
        "        .await",
        "        .map_err(ApiError::from_db)?;",
        "    find(pool, done.last_insert_rowid()).await",
        "}",
        "",
        "/// Changes only the fields the request sends, like the other generated backends.",
        f"pub async fn update(pool: &SqlitePool, id: i64, input: {name}Input) -> Result<{name}, ApiError> {{",
        "    find(pool, id).await?;",
        "    input.validate(false)?;",
        *reference_call,
        "    let (columns, mut values) = input.assignments()?;",
        '    let mut sets: Vec<String> = columns.iter().map(|column| format!("{column} = ?")).collect();',
        f'    sets.push(format!("{q("updated_at").replace(chr(34), chr(92) + chr(34))} = {{}}", fields::NOW_SQL));',
        "    values.add(id).map_err(ApiError::internal)?;",
        f'    let sql = format!({rust_fmt(f"UPDATE {table_sql} SET ")[:-1]}{{}} WHERE \\"id\\" = ?", sets.join(", "));',
        "    sqlx::query_with(&sql, values)",
        "        .execute(pool)",
        "        .await",
        "        .map_err(ApiError::from_db)?;",
        "    find(pool, id).await",
        "}",
        "",
        "pub async fn delete(pool: &SqlitePool, id: i64) -> Result<(), ApiError> {",
        "    let done = sqlx::query(DELETE_SQL)",
        "        .bind(id)",
        "        .execute(pool)",
        "        .await",
        "        .map_err(|err| ApiError::from_delete(err, RESTRICT_MESSAGE))?;",
        "    if done.rows_affected() == 0 {",
        "        return Err(ApiError::not_found(LABEL, id));",
        "    }",
        "    Ok(())",
        "}",
        "",
        f"// VENGAI:CUSTOM:{t.slug}_model:start",
        f"// Add functions for {doc(table['label'])} here. A new column belongs in the Architecture",
        "// tab instead, so a migration adds it to the database.",
        "// This block is preserved across future regenerations.",
        f"// VENGAI:CUSTOM:{t.slug}_model:end",
        "",
    ]
    return GeneratedFile(
        path=f"backend/src/models/{t.slug}.rs",
        language="rust",
        content="\n".join(lines),
        description=f"Deterministic model, validation and SQL for {t.name}",
    )


def _mod_lines(schema: db_schema.ResolvedSchema) -> list[str]:
    return [f"pub mod {module_name(t.slug)};" for t in schema.tables]


def models_mod(schema: db_schema.ResolvedSchema) -> GeneratedFile:
    return GeneratedFile(
        path="backend/src/models/mod.rs",
        language="rust",
        content="//! Every table's model — written by VengaiCode.\n\n"
        + "\n".join(_mod_lines(schema))
        + "\n",
        description="Declares every table's model module",
    )


# ───────────────────────────────────────────────
#  routes/<table>.rs — per framework
# ───────────────────────────────────────────────
def _routes_header(t: db_schema.ResolvedTable) -> list[str]:
    return [
        f"//! REST routes for {doc(t.name)} — the paths the generated screens call.",
        "//! Deterministically generated by VengaiCode (no AI call); the work itself",
        f"//! is in models/{t.slug}.rs.",
        "",
    ]


def _custom_handlers(t: db_schema.ResolvedTable) -> list[str]:
    return [
        "",
        f"// VENGAI:CUSTOM:{t.slug}_handlers:start",
        "// Add custom handlers here — this block is preserved across regenerations.",
        f"// VENGAI:CUSTOM:{t.slug}_handlers:end",
        "",
    ]


def _actix_routes(t: db_schema.ResolvedTable) -> str:
    base = f"/api/{t.sql_name}"
    lines = [
        *_routes_header(t),
        "use actix_web::{web, HttpResponse};",
        "use sqlx::SqlitePool;",
        "",
        "use crate::error::ApiError;",
        "use crate::fields;",
        f"use crate::models::{module_name(t.slug)} as model;",
        "",
        "pub fn configure(cfg: &mut web::ServiceConfig) {",
        "    cfg.service(",
        f"        web::resource({rust_str(base)})",
        "            .route(web::get().to(list))",
        "            .route(web::post().to(create)),",
        "    )",
        "    .service(",
        f"        web::resource({rust_str(base + '/{id}')})",
        "            .route(web::get().to(read))",
        "            .route(web::put().to(update))",
        "            .route(web::delete().to(remove)),",
        "    );",
        f"    // VENGAI:CUSTOM:{t.slug}_routes:start",
        "    // Register custom, non-CRUD routes here, e.g.",
        f"    // cfg.route({rust_str(base + '/export')}, web::get().to(export));",
        "    // This block is preserved across regenerations.",
        f"    // VENGAI:CUSTOM:{t.slug}_routes:end",
        "}",
        "",
        "async fn list(pool: web::Data<SqlitePool>) -> Result<HttpResponse, ApiError> {",
        "    Ok(HttpResponse::Ok().json(model::list(&pool).await?))",
        "}",
        "",
        "async fn create(pool: web::Data<SqlitePool>, body: web::Bytes) -> Result<HttpResponse, ApiError> {",
        "    let input = fields::parse_body(&body)?;",
        "    Ok(HttpResponse::Created().json(model::create(&pool, input).await?))",
        "}",
        "",
        "async fn read(pool: web::Data<SqlitePool>, id: web::Path<String>) -> Result<HttpResponse, ApiError> {",
        "    let id = fields::parse_id(&id)?;",
        "    Ok(HttpResponse::Ok().json(model::find(&pool, id).await?))",
        "}",
        "",
        "async fn update(",
        "    pool: web::Data<SqlitePool>,",
        "    id: web::Path<String>,",
        "    body: web::Bytes,",
        ") -> Result<HttpResponse, ApiError> {",
        "    let id = fields::parse_id(&id)?;",
        "    let input = fields::parse_body(&body)?;",
        "    Ok(HttpResponse::Ok().json(model::update(&pool, id, input).await?))",
        "}",
        "",
        "async fn remove(pool: web::Data<SqlitePool>, id: web::Path<String>) -> Result<HttpResponse, ApiError> {",
        "    model::delete(&pool, fields::parse_id(&id)?).await?;",
        "    Ok(HttpResponse::NoContent().finish())",
        "}",
        *_custom_handlers(t),
    ]
    return "\n".join(lines)


def _axum_routes(t: db_schema.ResolvedTable) -> str:
    base = f"/api/{t.sql_name}"
    row = f"model::{t.class_name}"
    lines = [
        *_routes_header(t),
        "use axum::body::Bytes;",
        "use axum::extract::{Path, State};",
        "use axum::http::StatusCode;",
        "use axum::routing::get;",
        "use axum::{Json, Router};",
        "use sqlx::SqlitePool;",
        "",
        "use crate::error::ApiError;",
        "use crate::fields;",
        f"use crate::models::{module_name(t.slug)} as model;",
        "",
        "pub fn router() -> Router<SqlitePool> {",
        "    let router = Router::new()",
        f"        .route({rust_str(base)}, get(list).post(create))",
        f"        .route({rust_str(base + '/{id}')}, get(read).put(update).delete(remove));",
        f"    // VENGAI:CUSTOM:{t.slug}_routes:start",
        "    // Add custom, non-CRUD routes here, e.g.",
        f"    // let router = router.route({rust_str(base + '/export')}, get(export));",
        "    // This block is preserved across regenerations.",
        f"    // VENGAI:CUSTOM:{t.slug}_routes:end",
        "    router",
        "}",
        "",
        f"async fn list(State(pool): State<SqlitePool>) -> Result<Json<Vec<{row}>>, ApiError> {{",
        "    Ok(Json(model::list(&pool).await?))",
        "}",
        "",
        "async fn create(",
        "    State(pool): State<SqlitePool>,",
        "    body: Bytes,",
        f") -> Result<(StatusCode, Json<{row}>), ApiError> {{",
        "    let input = fields::parse_body(&body)?;",
        "    Ok((StatusCode::CREATED, Json(model::create(&pool, input).await?)))",
        "}",
        "",
        "async fn read(",
        "    State(pool): State<SqlitePool>,",
        "    Path(id): Path<String>,",
        f") -> Result<Json<{row}>, ApiError> {{",
        "    let id = fields::parse_id(&id)?;",
        "    Ok(Json(model::find(&pool, id).await?))",
        "}",
        "",
        "async fn update(",
        "    State(pool): State<SqlitePool>,",
        "    Path(id): Path<String>,",
        "    body: Bytes,",
        f") -> Result<Json<{row}>, ApiError> {{",
        "    let id = fields::parse_id(&id)?;",
        "    let input = fields::parse_body(&body)?;",
        "    Ok(Json(model::update(&pool, id, input).await?))",
        "}",
        "",
        "async fn remove(State(pool): State<SqlitePool>, Path(id): Path<String>) -> Result<StatusCode, ApiError> {",
        "    model::delete(&pool, fields::parse_id(&id)?).await?;",
        "    Ok(StatusCode::NO_CONTENT)",
        "}",
        *_custom_handlers(t),
    ]
    return "\n".join(lines)


def routes_file(framework: str, t: db_schema.ResolvedTable) -> GeneratedFile:
    content = _actix_routes(t) if framework == "actix" else _axum_routes(t)
    return GeneratedFile(
        path=f"backend/src/routes/{t.slug}.rs",
        language="rust",
        content=content,
        description=f"REST routes for {t.name}",
    )


def routes_mod(framework: str, schema: db_schema.ResolvedSchema) -> GeneratedFile:
    # Paths start with :: (the crate, not a table module that shares its name).
    if framework == "actix":
        body = [
            "/// Registers every table's routes on the app.",
            "pub fn configure(cfg: &mut ::actix_web::web::ServiceConfig) {",
            *[f"    {module_name(t.slug)}::configure(cfg);" for t in schema.tables],
            "}",
        ]
    else:
        body = [
            "/// Every table's routes, on one router.",
            "pub fn router() -> ::axum::Router<::sqlx::SqlitePool> {",
            "    ::axum::Router::new()",
            *[
                f"        .merge({module_name(t.slug)}::router())"
                for t in schema.tables
            ],
            "}",
        ]
    lines = [
        "//! Every table's REST routes — written by VengaiCode.",
        "",
        *_mod_lines(schema),
        "",
        *body,
        "",
    ]
    return GeneratedFile(
        path="backend/src/routes/mod.rs",
        language="rust",
        content="\n".join(lines),
        description="Collects every table's routes",
    )


# ───────────────────────────────────────────────
#  error.rs — the constraint sentences, then the framework's response impl
# ───────────────────────────────────────────────
_ERROR_COMMON = """
#[derive(Debug)]
pub struct ApiError {
    pub status: u16,
    pub detail: String,
}

impl ApiError {
    pub fn new(status: u16, detail: impl Into<String>) -> Self {
        Self { status, detail: detail.into() }
    }

    pub fn not_found(label: &str, id: i64) -> Self {
        Self::new(404, format!("{label} {id} not found."))
    }

    /// A failure that isn't the request's fault: logged, answered as a 500.
    pub fn internal(err: impl fmt::Display) -> Self {
        eprintln!("internal error: {err}");
        Self::new(500, "Something went wrong on the server.")
    }

    /// A failed read or write, explained.
    pub fn from_db(err: sqlx::Error) -> Self {
        if let sqlx::Error::Database(db) = &err {
            return explain(db.message());
        }
        Self::internal(err)
    }

    /// A failed delete: a foreign key refusing it means rows still refer to this one.
    pub fn from_delete(err: sqlx::Error, restrict_message: &str) -> Self {
        if let sqlx::Error::Database(db) = &err {
            if db.message().contains("FOREIGN KEY constraint failed") {
                return Self::new(409, restrict_message);
            }
        }
        Self::from_db(err)
    }
}

impl fmt::Display for ApiError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.detail)
    }
}

fn explain(text: &str) -> ApiError {
    if text.starts_with("UNIQUE constraint failed") || text.starts_with("CHECK constraint failed") {
        // SQLite names a failed UNIQUE by its columns, a failed CHECK by its name.
        if let Some((_, status, message)) = CONSTRAINTS.iter().find(|(key, _, _)| names(text, key)) {
            return ApiError::new(*status, *message);
        }
    }
    if let Some(column) = text.strip_prefix("NOT NULL constraint failed: ") {
        return ApiError::new(422, format!("{column}: may not be null"));
    }
    if text.contains("FOREIGN KEY constraint failed") {
        return ApiError::new(422, "A record this one refers to doesn't exist.");
    }
    ApiError::new(409, format!("The database refused this change: {text}"))
}

/// Whether the message names `key` whole, not as part of a longer name.
fn names(text: &str, key: &str) -> bool {
    let part = |c: char| c.is_alphanumeric() || c == '_' || c == '.';
    text.match_indices(key).any(|(at, _)| {
        !text[..at].chars().next_back().is_some_and(part)
            && !text[at + key.len()..].chars().next().is_some_and(part)
    })
}
"""

_ERROR_ACTIX = """
impl ResponseError for ApiError {
    fn status_code(&self) -> StatusCode {
        StatusCode::from_u16(self.status).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR)
    }

    fn error_response(&self) -> HttpResponse {
        HttpResponse::build(self.status_code()).json(serde_json::json!({ "detail": self.detail }))
    }
}
"""

_ERROR_AXUM = """
impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        let status = StatusCode::from_u16(self.status).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR);
        (status, Json(serde_json::json!({ "detail": self.detail }))).into_response()
    }
}
"""


def error_file(
    framework: str, constraints: list[tuple[str, int, str]]
) -> GeneratedFile:
    entries = "\n".join(
        f"    ({rust_str(k)}, {s}, {rust_str(m)}),"
        for k, s, m in sorted(constraints, key=lambda e: -len(e[0]))
    )
    if framework == "actix":
        imports = [
            "use actix_web::http::StatusCode;",
            "use actix_web::{HttpResponse, ResponseError};",
        ]
        response = _ERROR_ACTIX
    else:
        imports = [
            "use axum::http::StatusCode;",
            "use axum::response::{IntoResponse, Response};",
            "use axum::Json;",
        ]
        response = _ERROR_AXUM
    content = "\n".join(
        [
            '//! API errors — every failure answers {"detail": "..."} with its HTTP status,',
            "//! which is what the generated screens show. Written by VengaiCode.",
            "",
            *imports,
            "use std::fmt;",
            "",
            "// What each database constraint means, so a violation comes back as a",
            "// sentence instead of a raw database error: (name in the database's",
            "// message, HTTP status, sentence). Longest names first.",
            "const CONSTRAINTS: &[(&str, u16, &str)] = &[",
            *([entries] if entries else []),
            "];",
        ]
    )
    return GeneratedFile(
        path="backend/src/error.rs",
        language="rust",
        content=content + "\n" + _ERROR_COMMON + response,
        description="Turns every error into a {detail} response with its status",
    )


# ───────────────────────────────────────────────
#  fields.rs — request/response value types, the same for both
# ───────────────────────────────────────────────
_FIELDS_RS = """//! Field helpers shared by every table's model — written by VengaiCode.
//!
//! Values are stored the way SQLite compares them: date-times as UTC text with
//! six fractional digits ("2024-01-31 09:30:00.000000"), dates as "2024-01-31",
//! booleans as 0/1 and JSON as its text. A request may leave a field out (the
//! database default applies, or an update keeps the value) or send it as null;
//! Patch tells the two apart.

// Not every table uses every helper.
#![allow(dead_code)]

use chrono::{DateTime, NaiveDate, NaiveDateTime, SecondsFormat};
use serde::de::{DeserializeOwned, Error as _};
use serde::{Deserialize, Deserializer, Serialize, Serializer};

use crate::error::ApiError;

/// Digits a decimal keeps, and how many of them follow the point.
pub const DECIMAL_DIGITS: usize = __DIGITS__;
pub const DECIMAL_PLACES: usize = __PLACES__;
/// SQL for "now" in the stored date-time form (%f is seconds with 3 decimals).
pub const NOW_SQL: &str = "__NOW_SQL__";
const STORED: &str = "%Y-%m-%d %H:%M:%S%.6f";

/// A request field: None = left out, Some(None) = sent as null.
pub type Patch<T> = Option<Option<T>>;

/// serde helper for Patch fields: a field that is present, even as null, is Some.
pub fn present<'de, T, D>(deserializer: D) -> Result<Patch<T>, D::Error>
where
    T: Deserialize<'de>,
    D: Deserializer<'de>,
{
    Option::<T>::deserialize(deserializer).map(Some)
}

/// A request body as `T`: 400 for anything but a JSON object, 422 naming the
/// field for a value of the wrong kind.
pub fn parse_body<T: DeserializeOwned>(body: &[u8]) -> Result<T, ApiError> {
    let value: serde_json::Value = serde_json::from_slice(body)
        .map_err(|_| ApiError::new(400, "Send the record as a JSON object."))?;
    if !value.is_object() {
        return Err(ApiError::new(400, "Send the record as a JSON object."));
    }
    serde_path_to_error::deserialize(value)
        .map_err(|err| ApiError::new(422, format!("{}: {}", err.path(), err.inner())))
}

/// The {id} in a route's path.
pub fn parse_id(text: &str) -> Result<i64, ApiError> {
    text.parse().map_err(|_| ApiError::new(400, "id: not a valid id"))
}

/// A NOT NULL field with no default: needed on create, never null.
pub fn required<T>(value: &Patch<T>, field: &str, creating: bool, errors: &mut Vec<String>) {
    match value {
        None if creating => errors.push(format!("{field}: is required")),
        Some(None) => errors.push(format!("{field}: may not be null")),
        _ => {}
    }
}

/// A NOT NULL field with a default: may be left out, never null.
pub fn not_null<T>(value: &Patch<T>, field: &str, errors: &mut Vec<String>) {
    if let Some(None) = value {
        errors.push(format!("{field}: may not be null"));
    }
}

/// Text no longer than its column allows.
pub fn max_chars(value: &Patch<String>, max: usize, field: &str, errors: &mut Vec<String>) {
    if let Some(Some(text)) = value {
        if text.chars().count() > max {
            errors.push(format!("{field}: at most {max} characters"));
        }
    }
}

/// Every problem found, as one 422 — or none.
pub fn finish(errors: Vec<String>) -> Result<(), ApiError> {
    if errors.is_empty() {
        Ok(())
    } else {
        Err(ApiError::new(422, errors.join("\\n")))
    }
}

/// A decimal from a request: a JSON number, or text like "12.50".
#[derive(Debug, Clone, Copy)]
pub struct DecimalValue(pub f64);

impl<'de> Deserialize<'de> for DecimalValue {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let text = match serde_json::Value::deserialize(deserializer)? {
            serde_json::Value::Number(n) => n.as_f64().map(|f| f.to_string()).unwrap_or_default(),
            serde_json::Value::String(s) => s.trim().to_string(),
            _ => String::new(),
        };
        decimal(&text).map(DecimalValue).map_err(D::Error::custom)
    }
}

fn decimal(text: &str) -> Result<f64, String> {
    let unsigned = text.strip_prefix('-').unwrap_or(text);
    let (whole, fraction) = unsigned.split_once('.').unwrap_or((unsigned, ""));
    let digits = |s: &str| s.bytes().all(|b| b.is_ascii_digit());
    if whole.is_empty() || !digits(whole) || !digits(fraction) || unsigned.ends_with('.') {
        return Err("expected a number like 12.50".to_string());
    }
    if fraction.trim_end_matches('0').len() > DECIMAL_PLACES {
        return Err(format!("only {DECIMAL_PLACES} decimal places are stored"));
    }
    if whole.trim_start_matches('0').len() > DECIMAL_DIGITS - DECIMAL_PLACES {
        return Err("number is too large".to_string());
    }
    text.parse().map_err(|_| "expected a number like 12.50".to_string())
}

/// A date from a request: "2024-01-31".
#[derive(Debug, Clone)]
pub struct DateValue(pub String);

impl<'de> Deserialize<'de> for DateValue {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let text = String::deserialize(deserializer)?;
        NaiveDate::parse_from_str(text.trim(), "%Y-%m-%d")
            .map(|day| DateValue(day.format("%Y-%m-%d").to_string()))
            .map_err(|_| D::Error::custom("expected a date like 2024-01-31"))
    }
}

/// A date-time from a request — RFC 3339 ("2024-01-31T09:30:00Z", any offset),
/// or without an offset, read as UTC — kept as stored UTC text.
#[derive(Debug, Clone)]
pub struct DateTimeValue(pub String);

impl<'de> Deserialize<'de> for DateTimeValue {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let text = String::deserialize(deserializer)?;
        let text = text.trim();
        let naive = text.replace('T', " ");
        let utc = DateTime::parse_from_rfc3339(text)
            .map(|when| when.naive_utc())
            .or_else(|_| NaiveDateTime::parse_from_str(&naive, "%Y-%m-%d %H:%M:%S%.f"))
            .or_else(|_| NaiveDateTime::parse_from_str(&naive, "%Y-%m-%d %H:%M"))
            .map_err(|_| D::Error::custom("expected a date and time like 2024-01-31T09:30:00Z"))?;
        Ok(DateTimeValue(utc.format(STORED).to_string()))
    }
}

/// A stored date-time, answered as RFC 3339 UTC ("2024-01-31T09:30:00Z").
#[derive(Debug, Clone, sqlx::Type)]
#[sqlx(transparent)]
pub struct Timestamp(pub String);

impl Serialize for Timestamp {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        match NaiveDateTime::parse_from_str(&self.0, "%Y-%m-%d %H:%M:%S%.f") {
            Ok(when) => serializer.serialize_str(&when.and_utc().to_rfc3339_opts(SecondsFormat::AutoSi, true)),
            // Written some other way (by hand, say): answered as stored.
            Err(_) => serializer.serialize_str(&self.0),
        }
    }
}

/// A stored JSON value, answered as JSON rather than as its text.
#[derive(Debug, Clone, sqlx::Type)]
#[sqlx(transparent)]
pub struct JsonText(pub String);

impl Serialize for JsonText {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        match serde_json::from_str::<serde_json::Value>(&self.0) {
            Ok(value) => value.serialize(serializer),
            Err(_) => serializer.serialize_str(&self.0),
        }
    }
}
"""


def fields_file() -> GeneratedFile:
    from app.ai.migrations_sqlite import NOW_SQL

    content = (
        _FIELDS_RS.replace("__DIGITS__", str(db_schema.DECIMAL_PRECISION))
        .replace("__PLACES__", str(db_schema.DECIMAL_SCALE))
        .replace("__NOW_SQL__", NOW_SQL)
    )
    return GeneratedFile(
        path="backend/src/fields.rs",
        language="rust",
        content=content,
        description="Request and response value types shared by every model",
    )


def backend_files(
    framework: str,
    schema: db_schema.ResolvedSchema,
    constraints: list[tuple[str, int, str]],
    headings: dict[str, str],
) -> tuple[list[GeneratedFile], list[GeneratedFile]]:
    """(model files, other backend files) — the first backend file is the
    routes module list, which the wiring context calls the routes file."""
    snapshot = db_schema.snapshot(schema)
    models = [model_file(t, snapshot, headings[t.sql_name]) for t in schema.tables]
    backend = [
        routes_mod(framework, schema),
        *[routes_file(framework, t) for t in schema.tables],
        models_mod(schema),
        error_file(framework, constraints),
        fields_file(),
    ]
    return models, backend
