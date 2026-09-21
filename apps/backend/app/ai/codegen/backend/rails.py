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
# ═══════════════════════════════════════════════════════════════

import re

from app.ai.codegen.types import BackendAdapter, FileResult, ModelCtx, RoutesCtx, WiringCtx
from app.ai.codegen_shared import GROQ_FILE_MAX_TOKENS, GeneratedFile, _pascal, _slug, generate_text_validated


def _infer_column_type(field_name: str) -> str:
    lowered = field_name.lower()
    if any(k in lowered for k in ("done", "active", "enabled", "completed", "is_", "has_")):
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

    prompt = f"""Write ONE complete, real ActiveRecord model class for the "{table_name}" table of this app.

Table purpose: {ctx.table.get('purpose', '')}
Fields (already defined as DB columns by a migration — do NOT redeclare them, just use them):
{', '.join(ctx.table.get('key_fields', []))}

Requirements:
- Class name: {class_name} < ApplicationRecord
- Do NOT declare any columns/attributes — ActiveRecord infers those from the database schema
  automatically. This file is ONLY: `validates` calls for real validation rules, `has_many`/
  `belongs_to` associations if implied by the key features / user stories, and any real instance/
  class methods the app's behavior needs.
- No placeholders or TODOs.

Return ONLY the raw Ruby code for this one file. No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(
        prompt, "ruby", GROQ_FILE_MAX_TOKENS,
        user=ctx.user, db=ctx.db, context=ctx.shared_context(),
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
        prompt, "ruby", GROQ_FILE_MAX_TOKENS,
        user=ctx.user, db=ctx.db, context=ctx.shared_context(),
    )
    return [(
        GeneratedFile(
            path="backend/app/controllers/api_controller.rb",
            language="ruby",
            content=content,
            description="Rails controller implementing all API endpoints against the real models",
        ),
        issue,
    )]


def _graphql_type_field(field_name: str) -> str:
    graphql_type = {
        "boolean": "Boolean",
        "datetime": "GraphQL::Types::ISO8601DateTime",
        "decimal": "Float",
        "integer": "Integer",
    }.get(_infer_column_type(field_name), "String")
    return f'    field :{_slug(field_name)}, {graphql_type}'


def _table_type_rb(table: dict) -> str:
    name = _pascal(table.get("name", "Item"))
    fields = table.get("key_fields", []) or []
    field_lines = "\n".join(_graphql_type_field(f) for f in fields)
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
    REST migration's own column-type inference), so the AI's two calls
    are scoped to what's actually business logic — real query filtering
    and real mutation validation/persistence."""
    models_text = ", ".join(_pascal(t.get("name", "Item")) for t in ctx.tables)
    types_text = "\n".join(
        f"- Types::{_pascal(t.get('name', 'Item'))}Type wraps the {_pascal(t.get('name', 'Item'))} model "
        f"(fields: {', '.join(_slug(f) for f in (t.get('key_fields', []) or []))})"
        for t in ctx.tables
    )
    endpoints_text = "\n".join(
        f"- {e.get('method')} {e.get('path')}: {e.get('purpose')}" for e in ctx.endpoints
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
        query_prompt, "ruby", GROQ_FILE_MAX_TOKENS,
        user=ctx.user, db=ctx.db, context=ctx.shared_context(),
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
        mutation_prompt, "ruby", GROQ_FILE_MAX_TOKENS,
        user=ctx.user, db=ctx.db, context=ctx.shared_context(),
    )

    results: list[FileResult] = [
        (
            GeneratedFile(
                path=f"backend/app/graphql/types/{_slug(t.get('name', 'item'))}_type.rb",
                language="ruby",
                content=_table_type_rb(t),
                description=f"GraphQL object type wrapping {t.get('name', 'Item')} (deterministic)",
            ),
            None,
        )
        for t in ctx.tables
    ]
    results.append((
        GeneratedFile(
            path=_GRAPHQL_QUERY_TYPE_PATH,
            language="ruby",
            content=query_content,
            description="GraphQL Query type implementing every read capability against the real models",
        ),
        query_issue,
    ))
    results.append((
        GeneratedFile(
            path="backend/app/graphql/types/mutation_type.rb",
            language="ruby",
            content=mutation_content,
            description="GraphQL Mutation type implementing every write capability against the real models",
        ),
        mutation_issue,
    ))
    return results


ROUTES_BUILDERS = {"rest": _rest_routes, "graphql": _graphql_routes}


async def generate_routes(ctx: RoutesCtx) -> list[FileResult]:
    return await ROUTES_BUILDERS[ctx.api_style](ctx)


_GRAPHQL_QUERY_TYPE_PATH = "backend/app/graphql/types/query_type.rb"


def _is_graphql(ctx: WiringCtx) -> bool:
    return any(f.path == _GRAPHQL_QUERY_TYPE_PATH for f in ctx.routes_files)


def _build_migration_rb(index: int, table: dict) -> tuple[str, str]:
    """Returns (filename, content) for one table's migration."""
    table_name = table.get("name", "Item")
    plural = _table_slug(table_name)
    class_name = f"Create{_pascal(plural)}"
    # created_at/updated_at are already provided by `t.timestamps` below —
    # declaring them again would be a duplicate-column error when the
    # migration actually runs.
    fields = [f for f in (table.get("key_fields", []) or []) if _slug(f) not in ("created_at", "updated_at")]
    columns = "\n".join(f"      t.{_infer_column_type(field)} :{_slug(field)}" for field in fields)
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
    lines = "\n".join(
        f"  {e.get('method', 'GET').lower()} '{_rails_path(e.get('path', '/'))}', "
        f"to: 'api#{_view_name(e.get('method', 'GET'), e.get('path', '/'))}'"
        for e in endpoints
    ) or "  # no endpoints defined"
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
    module_name = "".join(ch for ch in project_name.title() if ch.isalnum()) or "GeneratedApp"
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
    module_name = "".join(ch for ch in project_name.title() if ch.isalnum()) or "GeneratedApp"
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
        GeneratedFile(path="backend/Gemfile", language="text", content=_gemfile(ctx.project_name, graphql), description="Ruby gem dependencies"),
        GeneratedFile(path="backend/config/database.yml", language="yaml", content=_database_yml(), description="Database config (SQLite, zero external setup)"),
    ]


def _schema_name(project_name: str) -> str:
    module_name = "".join(ch for ch in project_name.title() if ch.isalnum()) or "GeneratedApp"
    return f"{module_name}Schema"


def entry_point_files(ctx: WiringCtx) -> list[GeneratedFile]:
    graphql = _is_graphql(ctx)
    files = [
        GeneratedFile(path="backend/config/boot.rb", language="ruby", content=_boot_rb(), description="Rails boot file"),
        GeneratedFile(path="backend/config/application.rb", language="ruby", content=_application_rb(ctx.project_name), description="Rails application config (API-only mode)"),
        GeneratedFile(path="backend/config/environment.rb", language="ruby", content=_environment_rb(ctx.project_name), description="Rails environment loader"),
        GeneratedFile(path="backend/config/initializers/cors.rb", language="ruby", content=_CORS_INITIALIZER, description="CORS config"),
        GeneratedFile(path="backend/app/models/application_record.rb", language="ruby", content=_APPLICATION_RECORD_RB, description="Base ActiveRecord class"),
        GeneratedFile(path="backend/app/controllers/application_controller.rb", language="ruby", content=_APPLICATION_CONTROLLER_RB, description="Base controller class (API-only)"),
    ]
    if graphql:
        schema_name = _schema_name(ctx.project_name)
        files += [
            GeneratedFile(path="backend/app/graphql/types/base_argument.rb", language="ruby", content=_BASE_ARGUMENT_RB, description="graphql-ruby base scaffold (verbatim from the real installer generator)"),
            GeneratedFile(path="backend/app/graphql/types/base_field.rb", language="ruby", content=_BASE_FIELD_RB, description="graphql-ruby base scaffold (verbatim from the real installer generator)"),
            GeneratedFile(path="backend/app/graphql/types/base_input_object.rb", language="ruby", content=_BASE_INPUT_OBJECT_RB, description="graphql-ruby base scaffold (verbatim from the real installer generator)"),
            GeneratedFile(path="backend/app/graphql/types/base_object.rb", language="ruby", content=_BASE_OBJECT_RB, description="graphql-ruby base scaffold (verbatim from the real installer generator)"),
            GeneratedFile(path="backend/app/controllers/graphql_controller.rb", language="ruby", content=_graphql_controller_rb(schema_name), description="GraphQL HTTP entry point (verbatim from the real installer generator)"),
            GeneratedFile(path=f"backend/app/graphql/{_slug(schema_name)}.rb", language="ruby", content=_graphql_schema_rb(schema_name), description="GraphQL schema — wires QueryType + MutationType"),
            GeneratedFile(path="backend/config/routes.rb", language="ruby", content='Rails.application.routes.draw do\n  post "/graphql", to: "graphql#execute"\nend\n', description="Real graphql-ruby route (verbatim from the real installer generator)"),
        ]
    elif ctx.endpoints:
        files.append(GeneratedFile(
            path="backend/config/routes.rb",
            language="ruby",
            content=_build_routes_rb(ctx.endpoints),
            description="URL routing, deterministically wired to the exact controller method names dictated to the AI",
        ))
    for index, table in enumerate(ctx.tables):
        filename, content = _build_migration_rb(index, table)
        files.append(GeneratedFile(
            path=f"backend/db/migrate/{filename}",
            language="ruby",
            content=content,
            description=f"Schema migration for {table.get('name', 'Item')}",
        ))
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
