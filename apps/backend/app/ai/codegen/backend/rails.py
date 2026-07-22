# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Ruby on Rails Backend Adapter
#  ai/codegen/backend/rails.py — ActiveRecord's model files legitimately
#  don't declare columns (Rails infers them from the DB schema at
#  runtime) — the schema itself lives in a migration file, generated
#  deterministically here (mechanical name -> column-type heuristic,
#  same style as codegen_shared.py's NATIVE_CAPABILITY_KEYWORDS) so the
#  AI call is scoped to what's actually business logic: validations,
#  associations, and controller behavior.
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

    prompt = f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Write ONE complete, real ActiveRecord model class for the "{table_name}" table of this app.

App: {ctx.project_name}
{ctx.requirements_text}
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

    content, issue = await generate_text_validated(prompt, "ruby", GROQ_FILE_MAX_TOKENS)
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

    prompt = f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Write ONE complete, real Rails controller implementing every API endpoint below for this app.

App: {ctx.project_name}
{ctx.requirements_text}
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

    content, issue = await generate_text_validated(prompt, "ruby", GROQ_FILE_MAX_TOKENS)
    return [(
        GeneratedFile(
            path="backend/app/controllers/api_controller.rb",
            language="ruby",
            content=content,
            description="Rails controller implementing all API endpoints against the real models",
        ),
        issue,
    )]


ROUTES_BUILDERS = {"rest": _rest_routes}


async def generate_routes(ctx: RoutesCtx) -> list[FileResult]:
    return await ROUTES_BUILDERS[ctx.api_style](ctx)


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


def _gemfile(project_name: str) -> str:
    return """source 'https://rubygems.org'

gem 'rails', '~> 7.1'
gem 'sqlite3', '~> 1.4'
gem 'puma', '~> 6.0'
gem 'rack-cors'
"""


_CORS_INITIALIZER = """Rails.application.config.middleware.insert_before 0, Rack::Cors do
  allow do
    origins '*'
    resource '*', headers: :any, methods: [:get, :post, :put, :patch, :delete, :options]
  end
end
"""


def manifest_files(ctx: WiringCtx) -> list[GeneratedFile]:
    return [
        GeneratedFile(path="backend/Gemfile", language="text", content=_gemfile(ctx.project_name), description="Ruby gem dependencies"),
        GeneratedFile(path="backend/config/database.yml", language="yaml", content=_database_yml(), description="Database config (SQLite, zero external setup)"),
    ]


def entry_point_files(ctx: WiringCtx) -> list[GeneratedFile]:
    files = [
        GeneratedFile(path="backend/config/boot.rb", language="ruby", content=_boot_rb(), description="Rails boot file"),
        GeneratedFile(path="backend/config/application.rb", language="ruby", content=_application_rb(ctx.project_name), description="Rails application config (API-only mode)"),
        GeneratedFile(path="backend/config/environment.rb", language="ruby", content=_environment_rb(ctx.project_name), description="Rails environment loader"),
        GeneratedFile(path="backend/config/initializers/cors.rb", language="ruby", content=_CORS_INITIALIZER, description="CORS config"),
        GeneratedFile(path="backend/app/models/application_record.rb", language="ruby", content=_APPLICATION_RECORD_RB, description="Base ActiveRecord class"),
        GeneratedFile(path="backend/app/controllers/application_controller.rb", language="ruby", content=_APPLICATION_CONTROLLER_RB, description="Base controller class (API-only)"),
    ]
    if ctx.endpoints:
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
