# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Ruby on Rails Backend Adapter
#  ai/codegen/backend/rails.py — ActiveRecord's model files legitimately
#  don't declare columns (Rails infers them from the DB schema at
#  runtime) — the schema itself lives in a migration file, generated
#  deterministically here (mechanical name -> column-type heuristic,
#  same style as codegen_shared.py's NATIVE_CAPABILITY_KEYWORDS) so the
#  AI call is scoped to what's actually business logic: validations,
#  associations, and controller behavior.
#
#  2026-09-21: added a real "graphql" api_style using graphql-ruby
#  (the "graphql" gem, currently 2.6.10 on rubygems.org — confirmed live
#  while writing this, not guessed). The base Types::*/Mutations::Base*
#  scaffold classes, GraphqlController, and the `post "/graphql"` route
#  below are transcribed VERBATIM from graphql-ruby's own real installer
#  generator templates (lib/generators/graphql/templates/*.erb on
#  rmosolgo/graphql-ruby), not freehanded — that's the exact scaffold
#  `rails g graphql:install` produces. QueryType/MutationType are built
#  deterministically (one query + one full CRUD mutation set per table)
#  and handed to the AI as an exact contract, same reasoning as every
#  other backend's deterministic-schema-for-statically-bound-languages
#  pattern (see spring_boot.py/nestjs.py) — Ruby is dynamic, so this
#  isn't strictly required the way Java's reflection binding is, but
#  keeping the schema deterministic here too avoids the AI inventing
#  a MutationType.rb that doesn't attach the exact mutation classes it
#  wrote in the other file.
#
#  2026-09-24: typed columns. A table that declares field types, foreign
#  keys, uniques, indexes or checks in the Architecture editor gets them
#  in its migration (t.references ... foreign_key:, t.index, Rails 7.1's
#  t.check_constraint) and in its GraphQL type; migrations run parents-
#  first so every referenced table exists. A table that declares nothing
#  still produces exactly the output it always did — see
#  typed_schema.py.
# ═══════════════════════════════════════════════════════════════

import re

from app.ai import db_schema
from app.ai.codegen.backend import typed_schema
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


def _infer_column_type(field_name: str) -> str:
    lowered = field_name.lower()
    if any(
        k in lowered for k in ("done", "active", "enabled", "completed", "is_", "has_")
    ):
        return "boolean"
    if any(k in lowered for k in ("_at", "date", "time")):
        return "datetime"
    if any(k in lowered for k in ("price", "amount", "total", "cost")):
        return "decimal"
    if any(k in lowered for k in ("count", "quantity", "number", "age")):
        return "integer"
    return "string"


def _table_slug(table_name: str) -> str:
    return f"{_slug(table_name)}s"  # simple pluralization, matches Rails' table-naming convention


def _view_name(method: str, path: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", path.strip("/")).strip("_").lower() or "root"
    return f"{method.lower()}_{slug}"


def _rails_path(path: str) -> str:
    """'/tasks/{id}' -> '/tasks/:id' (Rails' route-param syntax)."""
    return "/" + re.sub(r"\{(\w+)\}", r":\1", path.strip("/"))


async def generate_model(ctx: ModelCtx) -> FileResult:
    table_name = ctx.table.get("name", "Item")
    class_name = _pascal(table_name)
    all_tables = ctx.all_tables or [ctx.table]
    column_types = ", ".join(
        f"{column} {rails_type}"
        for column, rails_type in _migration_column_types(
            ctx.table, typed_schema.resolve_if_typed(all_tables)
        )
    )

    prompt = f"""Write ONE complete, real ActiveRecord model class for the "{table_name}" table of this app.

Table purpose: {ctx.table.get("purpose", "")}
The columns below are ALREADY created by a migration — do NOT redeclare them, just use them.
{db_schema.describe_table_for_prompt(ctx.table, all_tables)}
Column types the migration really creates (where these differ from the list above, these are
what the database has): {column_types or "(none besides id and timestamps)"}

Requirements:
- Class name: {class_name} < ApplicationRecord
- Do NOT declare any columns/attributes — ActiveRecord infers those from the database schema
  automatically. This file is ONLY: `validates` calls for real validation rules (including one
  for every required field, unique field and check constraint listed above), `has_many`/
  `belongs_to` associations for every foreign key listed above (`optional: true` on an optional
  one) plus any implied by the key features / user stories, and any real instance/class methods
  the app's behavior needs.
- No placeholders or TODOs.

Return ONLY the raw Ruby code for this one file. No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(
        prompt,
        "ruby",
        GROQ_FILE_MAX_TOKENS,
        user=ctx.user,
        db=ctx.db,
        context=ctx.shared_context(),
    )
    return GeneratedFile(
        path=f"backend/app/models/{_slug(table_name)}.rb",
        language="ruby",
        content=content,
        description=f"ActiveRecord model for {table_name}",
    ), issue


async def _rest_routes(ctx: RoutesCtx) -> list[FileResult]:
    endpoints_text = "\n".join(
        f"- {e.get('method')} {e.get('path')}: {e.get('purpose')} "
        f"(implement as a method named `{_view_name(e.get('method', 'GET'), e.get('path', '/'))}`)"
        for e in ctx.endpoints
    )
    models_text = ", ".join(_pascal(t.get("name", "Item")) for t in ctx.tables)

    prompt = f"""Write ONE complete, real Rails controller implementing every API endpoint below for this app.

Available ActiveRecord models to use: {models_text}

API endpoints to implement (use the EXACT method name given for each — config/routes.rb
references these exact names):
{endpoints_text}

Requirements:
- Class name: `ApiController < ApplicationController`.
- Each method MUST do real reads/writes against the ActiveRecord models above (`Model.all`,
  `Model.find`, `Model.create`, etc.) — do not return hardcoded/fake JSON. Render with
  `render json: ...` and correct HTTP status (`status: :created`, `status: :not_found`, etc.).
- Any route param (e.g. from a path like "/tasks/{{id}}") is available as `params[:id]`.
- Implement the actual behavior implied by the key features and user stories above, including
  real strong-parameter filtering (`params.require(...).permit(...)`) for create/update methods.
- No placeholders or TODOs — every method must be fully implemented.

Return ONLY the raw Ruby code for this one file. No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(
        prompt,
        "ruby",
        GROQ_FILE_MAX_TOKENS,
        user=ctx.user,
        db=ctx.db,
        context=ctx.shared_context(),
    )
    return [
        (
            GeneratedFile(
                path="backend/app/controllers/api_controller.rb",
                language="ruby",
                content=content,
                description="Rails controller implementing all API endpoints against the real models",
            ),
            issue,
        )
    ]


# graphql-ruby's own built-in scalars for each db_schema type — ISO8601Date
# and JSON ship with graphql-ruby itself, so a declared date/json column
# needs no extra gem. decimal stays Float, same as the name-based guess.
_GRAPHQL_RUBY_TYPES = {
    "string": "String",
    "text": "String",
    "integer": "Integer",
    "float": "Float",
    "decimal": "Float",
    "boolean": "Boolean",
    "date": "GraphQL::Types::ISO8601Date",
    "datetime": "GraphQL::Types::ISO8601DateTime",
    "json": "GraphQL::Types::JSON",
}


def _graphql_scalar(field_name: str) -> str:
    """A table that declares nothing: the same name-based guess its
    migration's column type came from."""
    return {
        "boolean": "Boolean",
        "datetime": "GraphQL::Types::ISO8601DateTime",
        "decimal": "Float",
        "integer": "Integer",
    }.get(_infer_column_type(field_name), "String")


def _type_fields(
    table: dict, schema: db_schema.ResolvedSchema | None
) -> list[tuple[str, str, bool]]:
    """(field, graphql type, non-null) for every column the table's
    GraphQL type exposes — shared by the deterministic type file and the
    prompts that describe it, so the two can't disagree. A typed table's
    scalars follow the exact column its migration creates."""
    rt = typed_schema.typed_table(schema, table)
    if rt is None:
        return [
            (_slug(f), _graphql_scalar(f), False)
            for f in (table.get("key_fields", []) or [])
        ]
    fields = [
        (c.column, _GRAPHQL_RUBY_TYPES[_rails_column(c, schema)[2]], not c.nullable)
        for c in rt.columns
    ]
    # t.timestamps always creates both (NOT NULL), so the type can too.
    return fields + [
        ("created_at", "GraphQL::Types::ISO8601DateTime", True),
        ("updated_at", "GraphQL::Types::ISO8601DateTime", True),
    ]


def _table_type_rb(table: dict, schema: db_schema.ResolvedSchema | None = None) -> str:
    name = _pascal(table.get("name", "Item"))
    field_lines = "\n".join(
        f"    field :{field}, {graphql_type}{', null: false' if non_null else ''}"
        for field, graphql_type, non_null in _type_fields(table, schema)
    )
    return f"""module Types
  class {name}Type < Types::BaseObject
    field :id, ID, null: false
{field_lines}
  end
end
"""


async def _graphql_routes(ctx: RoutesCtx) -> list[FileResult]:
    """graphql-ruby's dynamic-language field-based style doesn't need
    exact reflection-based name binding the way Java/C# do, but the
    schema is still split the same way as every other backend's
    deterministic-contract + AI-implementation design: {Table}Type
    wrapping is pure field-list boilerplate (built here, mirroring the
    REST migration's own column types), so the AI's two calls are
    scoped to what's actually business logic — real query filtering
    and real mutation validation/persistence."""
    schema = typed_schema.resolve_if_typed(ctx.tables)
    models_text = ", ".join(_pascal(t.get("name", "Item")) for t in ctx.tables)
    types_text = "\n".join(
        f"- Types::{_pascal(t.get('name', 'Item'))}Type wraps the {_pascal(t.get('name', 'Item'))} model "
        f"(fields: "
        + ", ".join(
            f"{field} {graphql_type}{' (required)' if non_null else ''}"
            for field, graphql_type, non_null in _type_fields(t, schema)
        )
        + ")"
        for t in ctx.tables
    )
    endpoints_text = "\n".join(
        f"- {e.get('method')} {e.get('path')}: {e.get('purpose')}"
        for e in ctx.endpoints
    )

    query_prompt = f"""Write ONE complete, real graphql-ruby QueryType class for this app.

Available ActiveRecord models: {models_text}
Available GraphQL object types (already generated, import nothing — same Types module):
{types_text}

The real-world capabilities this app needs (use this to inform REAL query behavior — filtering,
ordering, scoping — not just a bare "return everything" where the app's purpose implies more):
{endpoints_text}

Requirements:
- `module Types\\n  class QueryType < Types::BaseObject\\n    ...\\n  end\\nend`
- For each model above, define a real `field :xs, [Types::XType], null: false` (list) field and a
  `field :x, Types::XType, null: true do argument :id, ID, required: true end` (single-record)
  field, each with a real `def xs; ...; end` / `def x(id:); ...; end` resolver method doing a real
  ActiveRecord query (`Model.all`, `Model.find_by(id: id)`, etc.) — never hardcoded/fake data.
- Field/argument names use graphql-ruby's snake_case Ruby convention (graphql-ruby camelizes them
  automatically for the wire protocol) — do not camelCase them yourself.
- Implement the actual behavior implied by the key features and user stories above.
- No placeholders or TODOs — every field's resolver must be fully implemented.

Return ONLY the raw Ruby code for this one file. No markdown fences, no explanation, no JSON."""

    query_content, query_issue = await generate_text_validated(
        query_prompt,
        "ruby",
        GROQ_FILE_MAX_TOKENS,
        user=ctx.user,
        db=ctx.db,
        context=ctx.shared_context(),
    )

    mutation_prompt = f"""Write ONE complete, real graphql-ruby MutationType class for this app.

Available ActiveRecord models: {models_text}
Available GraphQL object types (already generated, import nothing — same Types module):
{types_text}

The real-world capabilities this app needs (use this to inform REAL mutation behavior —
validation, defaults — not just a bare passthrough where the app's purpose implies more):
{endpoints_text}

Requirements:
- `module Types\\n  class MutationType < Types::BaseObject\\n    ...\\n  end\\nend`
- For each model above, define real `create_x`, `update_x`, `delete_x` fields using graphql-ruby's
  inline field-resolver style (NOT separate Mutation classes): `field :create_x, Types::XType,
  null: false do argument :field1, String, required: true; argument :field2, ..., required: false
  ...; end` with a matching `def create_x(field1:, field2: nil, ...); ...; end` method doing a
  real `Model.create!(...)`. Same pattern for `update_x` (id + optional fields, real
  `Model.find(id).update!(...)`) and `delete_x` (id argument, real `Model.find(id).destroy!`,
  returns `Types::XType` for create/update, `Boolean` for delete).
- Field/argument names use graphql-ruby's snake_case Ruby convention.
- Raise a real `GraphQL::ExecutionError.new("...")` with a clear message for not-found/invalid
  cases — never let an unhandled exception leak a raw stack trace.
- Implement the actual behavior implied by the key features and user stories above.
- No placeholders or TODOs — every field's resolver must be fully implemented.

Return ONLY the raw Ruby code for this one file. No markdown fences, no explanation, no JSON."""

    mutation_content, mutation_issue = await generate_text_validated(
        mutation_prompt,
        "ruby",
        GROQ_FILE_MAX_TOKENS,
        user=ctx.user,
        db=ctx.db,
        context=ctx.shared_context(),
    )

    results: list[FileResult] = [
        (
            GeneratedFile(
                path=f"backend/app/graphql/types/{_slug(t.get('name', 'item'))}_type.rb",
                language="ruby",
                content=_table_type_rb(t, schema),
                description=f"GraphQL object type wrapping {t.get('name', 'Item')} (deterministic)",
            ),
            None,
        )
        for t in ctx.tables
    ]
    results.append(
        (
            GeneratedFile(
                path=_GRAPHQL_QUERY_TYPE_PATH,
                language="ruby",
                content=query_content,
                description="GraphQL Query type implementing every read capability against the real models",
            ),
            query_issue,
        )
    )
    results.append(
        (
            GeneratedFile(
                path="backend/app/graphql/types/mutation_type.rb",
                language="ruby",
                content=mutation_content,
                description="GraphQL Mutation type implementing every write capability against the real models",
            ),
            mutation_issue,
        )
    )
    return results


ROUTES_BUILDERS = {"rest": _rest_routes, "graphql": _graphql_routes}


async def generate_routes(ctx: RoutesCtx) -> list[FileResult]:
    return await ROUTES_BUILDERS[ctx.api_style](ctx)


_GRAPHQL_QUERY_TYPE_PATH = "backend/app/graphql/types/query_type.rb"


def _is_graphql(ctx: WiringCtx) -> bool:
    return any(f.path == _GRAPHQL_QUERY_TYPE_PATH for f in ctx.routes_files)


# db_schema type -> (ActiveRecord column type, its type options). Sizes
# match db_schema's own (string 255, decimal 12,2) so a Rails app and the
# no-AI generator agree on what a declared type means.
_RAILS_TYPES: dict[str, tuple[str, str]] = {
    "string": ("string", f"limit: {db_schema.STRING_LENGTH}"),
    "text": ("text", ""),
    "integer": ("integer", ""),
    "float": ("float", ""),
    "decimal": (
        "decimal",
        f"precision: {db_schema.DECIMAL_PRECISION}, scale: {db_schema.DECIMAL_SCALE}",
    ),
    "boolean": ("boolean", ""),
    "date": ("date", ""),
    "datetime": ("datetime", ""),
    "json": ("json", ""),
}

_RAILS_ON_DELETE = {
    "cascade": ":cascade",
    "set_null": ":nullify",
    "restrict": ":restrict",
}


def _ruby_str(text: str) -> str:
    # Single-quoted: only \ and ' are special, so no #{...} interpolation
    # can sneak in from a user-written default or check expression.
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _ruby_value(value) -> str:
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(_ruby_value(v) for v in value) + "]"
    if isinstance(value, dict):
        pairs = ", ".join(
            f"{_ruby_str(str(k))} => {_ruby_value(v)}" for k, v in value.items()
        )
        return "{ " + pairs + " }" if pairs else "{}"
    return _ruby_str(str(value))


_DECIMAL_LITERAL_RE = re.compile(r"-?\d+(\.\d+)?")


def _ruby_default(default: dict, field_type: str) -> str:
    kind = default["kind"]
    if kind == "now":
        return '-> { "CURRENT_TIMESTAMP" }'
    if kind == "today":
        return '-> { "CURRENT_DATE" }'
    value = default["value"]
    # db_schema keeps decimals as exact strings ("9.99") — a bare numeric
    # literal, not a quoted string, is what a decimal column's default is.
    if (
        field_type == "decimal"
        and isinstance(value, str)
        and _DECIMAL_LITERAL_RE.fullmatch(value)
    ):
        return value
    return _ruby_value(value)


def _rails_column(
    col: db_schema.ResolvedColumn, schema: db_schema.ResolvedSchema
) -> tuple[str, str, str]:
    """(ActiveRecord column type, its type options, the db_schema type
    that amounts to) — the last is what the column's default and its
    GraphQL scalar are rendered from, so neither can disagree with the
    column the migration actually creates."""
    ref_col = typed_schema.referenced_column(schema, col)
    if ref_col is not None:
        # Same column type as the column it points at.
        return _rails_column(ref_col, schema)
    if col.fk is not None:
        return "bigint", "", "integer"  # Rails' own primary keys are bigint
    guessed = _infer_column_type(col.name)  # always a db_schema type name too
    if typed_schema.keeps_guess(col, guessed, schema):
        return guessed, "", guessed
    return (*_RAILS_TYPES[col.type], col.type)


def _typed_migration_body(
    rt: db_schema.ResolvedTable, schema: db_schema.ResolvedSchema
) -> list[str]:
    """The lines inside create_table — columns, then t.timestamps, then
    every constraint and index, all created in the one CREATE TABLE."""
    columns: list[str] = []
    constraints: list[str] = []
    for col in rt.columns:
        rails_type, type_opts, field_type = _rails_column(col, schema)
        opts: list[str] = []
        if not col.nullable:
            opts.append("null: false")
        default = typed_schema.rendered_default(col, field_type)
        if default is not None:
            opts.append(f"default: {_ruby_default(default, field_type)}")
        fk = col.fk
        if (
            fk is not None
            and fk.ref_column == "id"
            and col.column.endswith("_id")
            and len(col.column) > 3
        ):
            # `t.references :author` IS the author_id column, its index and
            # (with foreign_key:) the constraint, in Rails' own idiom.
            opts.append(
                f"foreign_key: {{ to_table: :{_table_slug(fk.ref_table)}, "
                f'on_delete: {_RAILS_ON_DELETE[fk.on_delete]}, name: "{fk.constraint_name}" }}'
            )
            if col.unique:
                opts.append(
                    f'index: {{ unique: true, name: "{col.unique_constraint_name}" }}'
                )
            columns.append(f"      t.references :{col.column[:-3]}, {', '.join(opts)}")
            continue
        all_opts = ", ".join(o for o in [type_opts, *opts] if o)
        columns.append(
            f"      t.{rails_type} :{col.column}{', ' + all_opts if all_opts else ''}"
        )
        if col.unique:
            constraints.append(
                f'      t.index [:{col.column}], name: "{col.unique_constraint_name}", unique: true'
            )
        if fk is not None:
            # Not a <table>_id -> id reference, so t.references doesn't
            # fit — a typed column plus t.foreign_key does. Declared inside
            # create_table it's part of the CREATE TABLE itself (no SQLite
            # table rebuild, which a later add_foreign_key would need).
            primary_key = (
                f", primary_key: :{fk.ref_column}" if fk.ref_column != "id" else ""
            )
            constraints.append(
                f"      t.foreign_key :{_table_slug(fk.ref_table)}, column: :{col.column}"
                f"{primary_key}, on_delete: {_RAILS_ON_DELETE[fk.on_delete]}, "
                f'name: "{fk.constraint_name}"'
            )
    for idx in rt.indexes:
        cols = ", ".join(f":{c}" for c in idx.columns)
        unique = ", unique: true" if idx.unique else ""
        constraints.append(f'      t.index [{cols}], name: "{idx.name}"{unique}')
    for chk in rt.checks:
        # Rails 7.1 emits this inside CREATE TABLE on SQLite and Postgres
        # alike. chk.sql is rendered from db_schema's parsed expression,
        # never the raw text, so it's the same portable SQL every other
        # target enforces.
        constraints.append(
            f'      t.check_constraint {_ruby_str(chk.sql)}, name: "{chk.constraint_name}"'
        )
    return columns + ["      t.timestamps"] + constraints


def _migration_column_types(
    table: dict, schema: db_schema.ResolvedSchema | None
) -> list[tuple[str, str]]:
    """(column, ActiveRecord type) for every column _build_migration_rb
    creates besides id/timestamps — what the model prompt quotes, so the
    AI's validations match the real column types."""
    rt = typed_schema.typed_table(schema, table)
    if rt is None:
        return [
            (_slug(f), _infer_column_type(f))
            for f in (table.get("key_fields", []) or [])
            if _slug(f) not in ("created_at", "updated_at")
        ]
    return [(c.column, _rails_column(c, schema)[0]) for c in rt.columns]


def _build_migration_rb(
    index: int, table: dict, schema: db_schema.ResolvedSchema | None = None
) -> tuple[str, str]:
    """Returns (filename, content) for one table's migration. `schema` is
    the whole architecture resolved (typed_schema.resolve_if_typed) —
    needed to type a foreign key after the column it references; None
    resolves this table on its own."""
    table_name = table.get("name", "Item")
    plural = _table_slug(table_name)
    class_name = f"Create{_pascal(plural)}"
    if schema is None:
        schema = typed_schema.resolve_if_typed([table])
    rt = typed_schema.typed_table(schema, table)
    if rt is not None:
        body = "\n".join(_typed_migration_body(rt, schema))
        content = f"""class {class_name} < ActiveRecord::Migration[7.1]
  def change
    create_table :{plural} do |t|
{body}
    end
  end
end
"""
        return f"{20240101000000 + index:014d}_{_slug(plural)}.rb", content

    # created_at/updated_at are already provided by `t.timestamps` below —
    # declaring them again would be a duplicate-column error when the
    # migration actually runs.
    fields = [
        f
        for f in (table.get("key_fields", []) or [])
        if _slug(f) not in ("created_at", "updated_at")
    ]
    columns = "\n".join(
        f"      t.{_infer_column_type(field)} :{_slug(field)}" for field in fields
    )
    content = f"""class {class_name} < ActiveRecord::Migration[7.1]
  def change
    create_table :{plural} do |t|
{columns}
      t.timestamps
    end
  end
end
"""
    # Deterministic, uniquely-ordered "timestamp" — doesn't need to be a
    # real date, only unique and sortable so migrations run in a stable
    # order matching the tables list.
    filename = f"{20240101000000 + index:014d}_{_slug(plural)}.rb"
    return filename, content


def _build_routes_rb(endpoints: list[dict]) -> str:
    lines = (
        "\n".join(
            f"  {e.get('method', 'GET').lower()} '{_rails_path(e.get('path', '/'))}', "
            f"to: 'api#{_view_name(e.get('method', 'GET'), e.get('path', '/'))}'"
            for e in endpoints
        )
        or "  # no endpoints defined"
    )
    return f"""Rails.application.routes.draw do
{lines}
end
"""


_APPLICATION_RECORD_RB = """class ApplicationRecord < ActiveRecord::Base
  self.abstract_class = true
end
"""

_APPLICATION_CONTROLLER_RB = """class ApplicationController < ActionController::API
end
"""


def _application_rb(project_name: str) -> str:
    module_name = (
        "".join(ch for ch in project_name.title() if ch.isalnum()) or "GeneratedApp"
    )
    return f"""require_relative 'boot'
require 'rails/all'

Bundler.require(*Rails.groups)

module {module_name}
  class Application < Rails::Application
    config.load_defaults 7.1
    config.api_only = true
  end
end
"""


def _boot_rb() -> str:
    return """require 'bundler/setup'
require 'bootsnap/setup' if File.exist?(File.expand_path('../Gemfile.lock', __dir__))
"""


def _environment_rb(project_name: str) -> str:
    module_name = (
        "".join(ch for ch in project_name.title() if ch.isalnum()) or "GeneratedApp"
    )
    return f"""require_relative 'application'

{module_name}::Application.initialize!
"""


def _database_yml() -> str:
    return """default: &default
  adapter: sqlite3
  pool: 5
  timeout: 5000

development:
  <<: *default
  database: storage/development.sqlite3

test:
  <<: *default
  database: storage/test.sqlite3

production:
  <<: *default
  database: storage/production.sqlite3
"""


def _gemfile(project_name: str, graphql: bool) -> str:
    graphql_gem = "\ngem 'graphql', '~> 2.6'" if graphql else ""
    return f"""source 'https://rubygems.org'

gem 'rails', '~> 7.1'
gem 'sqlite3', '~> 1.4'
gem 'puma', '~> 6.0'
gem 'rack-cors'{graphql_gem}
"""


_CORS_INITIALIZER = """Rails.application.config.middleware.insert_before 0, Rack::Cors do
  allow do
    origins '*'
    resource '*', headers: :any, methods: [:get, :post, :put, :patch, :delete, :options]
  end
end
"""


# Every file below is transcribed verbatim from graphql-ruby's own real
# installer generator templates (lib/generators/graphql/templates/*.erb,
# rmosolgo/graphql-ruby — fetched and confirmed while writing this, not
# freehanded) — the exact scaffold `rails g graphql:install` produces.
_BASE_ARGUMENT_RB = """module Types
  class BaseArgument < GraphQL::Schema::Argument
  end
end
"""

_BASE_FIELD_RB = """module Types
  class BaseField < GraphQL::Schema::Field
    argument_class Types::BaseArgument
  end
end
"""

_BASE_INPUT_OBJECT_RB = """module Types
  class BaseInputObject < GraphQL::Schema::InputObject
    argument_class Types::BaseArgument
  end
end
"""

_BASE_OBJECT_RB = """module Types
  class BaseObject < GraphQL::Schema::Object
    field_class Types::BaseField
  end
end
"""


def _graphql_controller_rb(schema_name: str) -> str:
    return f"""class GraphqlController < ApplicationController
  def execute
    variables = prepare_variables(params[:variables])
    query = params[:query]
    operation_name = params[:operationName]
    context = {{
      # Query context goes here, for example:
      # current_user: current_user,
    }}
    result = {schema_name}.execute(query, variables: variables, context: context, operation_name: operation_name)
    render json: result
  rescue StandardError => e
    raise e unless Rails.env.development?
    handle_error_in_development(e)
  end

  private

  # Handle variables in form data, JSON body, or a blank value
  def prepare_variables(variables_param)
    case variables_param
    when String
      if variables_param.present?
        JSON.parse(variables_param) || {{}}
      else
        {{}}
      end
    when Hash
      variables_param
    when ActionController::Parameters
      variables_param.to_unsafe_hash
    when nil
      {{}}
    else
      raise ArgumentError, "Unexpected parameter: #{{variables_param}}"
    end
  end

  def handle_error_in_development(e)
    logger.error e.message
    logger.error e.backtrace.join("\\n")

    render json: {{ errors: [{{ message: e.message, backtrace: e.backtrace }}], data: {{}} }}, status: 500
  end
end
"""


def _graphql_schema_rb(schema_name: str) -> str:
    return f"""class {schema_name} < GraphQL::Schema
  query(Types::QueryType)
  mutation(Types::MutationType)

  use GraphQL::Dataloader

  max_depth(15)
  max_query_string_tokens(5000)
  validate_max_errors(100)
end
"""


def manifest_files(ctx: WiringCtx) -> list[GeneratedFile]:
    graphql = _is_graphql(ctx)
    return [
        GeneratedFile(
            path="backend/Gemfile",
            language="text",
            content=_gemfile(ctx.project_name, graphql),
            description="Ruby gem dependencies",
        ),
        GeneratedFile(
            path="backend/config/database.yml",
            language="yaml",
            content=_database_yml(),
            description="Database config (SQLite, zero external setup)",
        ),
    ]


def _schema_name(project_name: str) -> str:
    module_name = (
        "".join(ch for ch in project_name.title() if ch.isalnum()) or "GeneratedApp"
    )
    return f"{module_name}Schema"


def entry_point_files(ctx: WiringCtx) -> list[GeneratedFile]:
    graphql = _is_graphql(ctx)
    files = [
        GeneratedFile(
            path="backend/config/boot.rb",
            language="ruby",
            content=_boot_rb(),
            description="Rails boot file",
        ),
        GeneratedFile(
            path="backend/config/application.rb",
            language="ruby",
            content=_application_rb(ctx.project_name),
            description="Rails application config (API-only mode)",
        ),
        GeneratedFile(
            path="backend/config/environment.rb",
            language="ruby",
            content=_environment_rb(ctx.project_name),
            description="Rails environment loader",
        ),
        GeneratedFile(
            path="backend/config/initializers/cors.rb",
            language="ruby",
            content=_CORS_INITIALIZER,
            description="CORS config",
        ),
        GeneratedFile(
            path="backend/app/models/application_record.rb",
            language="ruby",
            content=_APPLICATION_RECORD_RB,
            description="Base ActiveRecord class",
        ),
        GeneratedFile(
            path="backend/app/controllers/application_controller.rb",
            language="ruby",
            content=_APPLICATION_CONTROLLER_RB,
            description="Base controller class (API-only)",
        ),
    ]
    if graphql:
        schema_name = _schema_name(ctx.project_name)
        files += [
            GeneratedFile(
                path="backend/app/graphql/types/base_argument.rb",
                language="ruby",
                content=_BASE_ARGUMENT_RB,
                description="graphql-ruby base scaffold (verbatim from the real installer generator)",
            ),
            GeneratedFile(
                path="backend/app/graphql/types/base_field.rb",
                language="ruby",
                content=_BASE_FIELD_RB,
                description="graphql-ruby base scaffold (verbatim from the real installer generator)",
            ),
            GeneratedFile(
                path="backend/app/graphql/types/base_input_object.rb",
                language="ruby",
                content=_BASE_INPUT_OBJECT_RB,
                description="graphql-ruby base scaffold (verbatim from the real installer generator)",
            ),
            GeneratedFile(
                path="backend/app/graphql/types/base_object.rb",
                language="ruby",
                content=_BASE_OBJECT_RB,
                description="graphql-ruby base scaffold (verbatim from the real installer generator)",
            ),
            GeneratedFile(
                path="backend/app/controllers/graphql_controller.rb",
                language="ruby",
                content=_graphql_controller_rb(schema_name),
                description="GraphQL HTTP entry point (verbatim from the real installer generator)",
            ),
            GeneratedFile(
                path=f"backend/app/graphql/{_slug(schema_name)}.rb",
                language="ruby",
                content=_graphql_schema_rb(schema_name),
                description="GraphQL schema — wires QueryType + MutationType",
            ),
            GeneratedFile(
                path="backend/config/routes.rb",
                language="ruby",
                content='Rails.application.routes.draw do\n  post "/graphql", to: "graphql#execute"\nend\n',
                description="Real graphql-ruby route (verbatim from the real installer generator)",
            ),
        ]
    elif ctx.endpoints:
        files.append(
            GeneratedFile(
                path="backend/config/routes.rb",
                language="ruby",
                content=_build_routes_rb(ctx.endpoints),
                description="URL routing, deterministically wired to the exact controller method names dictated to the AI",
            )
        )
    schema = typed_schema.resolve_if_typed(ctx.tables)
    # Parents first, so a foreign key's table always exists when the
    # table referencing it is created (identity order with no FKs).
    order = (
        typed_schema.migration_order(ctx.tables, schema)
        if schema is not None
        else range(len(ctx.tables))
    )
    for index, table in enumerate(ctx.tables[i] for i in order):
        filename, content = _build_migration_rb(index, table, schema)
        files.append(
            GeneratedFile(
                path=f"backend/db/migrate/{filename}",
                language="ruby",
                content=content,
                description=f"Schema migration for {table.get('name', 'Item')}",
            )
        )
    return files


def setup_commands(project_name: str) -> list[str]:
    return ["cd backend", "bundle install", "bin/rails db:migrate", "bin/rails server"]


ADAPTER = BackendAdapter(
    key="rails",
    label="Ruby on Rails",
    supported_languages=("ruby",),
    supported_api_styles=tuple(ROUTES_BUILDERS),
    generate_model=generate_model,
    generate_routes=generate_routes,
    manifest_files=manifest_files,
    entry_point_files=entry_point_files,
    setup_commands=setup_commands,
)
