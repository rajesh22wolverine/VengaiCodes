# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Laravel Backend Adapter
#  ai/codegen/backend/laravel.py — Laravel 11's simplified skeleton
#  (single bootstrap/app.php, no separate Kernel.php/Providers spread).
#  Same schema/business-logic split as rails.py: migrations are
#  deterministic (mechanical field-name -> column-type heuristic),
#  routes/api.php is deterministic (wired to exact controller method
#  names dictated to the AI, same pattern as django.py/rails.py).
#
#  2026-09-21: added a real "graphql" api_style using Lighthouse
#  (nuwave/lighthouse — confirmed current v6.70.1, Laravel 9-13
#  compatible, via its own composer.json/GitHub release while writing
#  this, not guessed). Lighthouse is schema-first with a real directive
#  system (@all/@find/@create/@update/@delete — confirmed against
#  Lighthouse's own current eloquent docs) that maps GraphQL operations
#  DIRECTLY onto Eloquent, so unlike Spring/Rails there is no separate
#  "controller" to write at all for straightforward CRUD — the schema
#  IS the implementation. schema.graphql is generated deterministically
#  (mirrors the migration's own column-type inference for real field
#  types), and the AI is used only for anything Lighthouse's directives
#  can't express declaratively (custom validation, computed fields) via
#  a `@field(resolver:)`-bound resolver class, kept genuinely optional
#  since most CRUD needs nothing beyond directives.
# ═══════════════════════════════════════════════════════════════

import re

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
        return "dateTime"
    if any(k in lowered for k in ("price", "amount", "total", "cost")):
        return "decimal"
    if any(k in lowered for k in ("count", "quantity", "number", "age")):
        return "integer"
    return "string"


def _table_slug(table_name: str) -> str:
    return f"{_slug(table_name)}s"


def _view_name(method: str, path: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "", path.strip("/").title()).strip() or "Root"
    return f"{method.lower()}{slug}"


def _laravel_path(path: str) -> str:
    """'/tasks/{id}' -> 'tasks/{id}' (Laravel already uses {param} syntax natively)."""
    return path.strip("/")


async def generate_model(ctx: ModelCtx) -> FileResult:
    table_name = ctx.table.get("name", "Item")
    class_name = _pascal(table_name)
    fields = ctx.table.get("key_fields", []) or []

    prompt = f"""Write ONE complete, real Eloquent model class for the "{table_name}" table of this app.

Table purpose: {ctx.table.get("purpose", "")}
Fields (already defined as DB columns by a migration — do NOT redeclare them as properties):
{", ".join(fields)}

Requirements:
- Class name: {class_name} extends Model (`use Illuminate\\Database\\Eloquent\\Model;`).
- Declare `protected $fillable = [{", ".join(repr(f) for f in fields)}];` for mass assignment.
- Add `$casts` for any boolean/datetime/decimal fields, real relationships (`hasMany`/
  `belongsTo`) if implied by the key features / user stories, and any real accessor/mutator
  methods the app's behavior needs.
- No placeholders or TODOs.

Return ONLY the raw PHP code for this one file (including `<?php` and `namespace App\\Models;`).
No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(
        prompt,
        "php",
        GROQ_FILE_MAX_TOKENS,
        user=ctx.user,
        db=ctx.db,
        context=ctx.shared_context(),
    )
    return GeneratedFile(
        path=f"backend/app/Models/{class_name}.php",
        language="php",
        content=content,
        description=f"Eloquent model for {table_name}",
    ), issue


async def _rest_routes(ctx: RoutesCtx) -> list[FileResult]:
    endpoints_text = "\n".join(
        f"- {e.get('method')} {e.get('path')}: {e.get('purpose')} "
        f"(implement as a method named `{_view_name(e.get('method', 'GET'), e.get('path', '/'))}`)"
        for e in ctx.endpoints
    )
    models_text = ", ".join(_pascal(t.get("name", "Item")) for t in ctx.tables)

    prompt = f"""Write ONE complete, real Laravel controller implementing every API endpoint below for this app.

Available Eloquent models to use (import from App\\Models): {models_text}

API endpoints to implement (use the EXACT method name given for each — routes/api.php
references these exact names):
{endpoints_text}

Requirements:
- Class name: `ApiController extends Controller` (namespace `App\\Http\\Controllers`).
- Each method takes `Illuminate\\Http\\Request $request` (plus any route params as further
  arguments, matching Laravel's implicit route-model-binding-free convention — a param from a
  path like "/tasks/{{id}}" arrives as a plain `$id` argument).
- Each method MUST do real reads/writes against the Eloquent models above (`Model::all()`,
  `Model::findOrFail($id)`, `Model::create($request->validate([...]))`, etc.) — do not return
  hardcoded/fake JSON. Return `response()->json(...)` with correct HTTP status codes (404 via
  `abort(404)` or `findOrFail`, 422 for validation failures via `$request->validate([...])`).
- Implement the actual behavior implied by the key features and user stories above.
- No placeholders or TODOs — every method must be fully implemented.

Return ONLY the raw PHP code for this one file (including `<?php` and the namespace declaration).
No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(
        prompt,
        "php",
        GROQ_FILE_MAX_TOKENS,
        user=ctx.user,
        db=ctx.db,
        context=ctx.shared_context(),
    )
    return [
        (
            GeneratedFile(
                path="backend/app/Http/Controllers/ApiController.php",
                language="php",
                content=content,
                description="Laravel controller implementing all API endpoints against the real models",
            ),
            issue,
        )
    ]


def _lighthouse_scalar(field_name: str) -> str:
    graphql_type = {
        "boolean": "Boolean",
        "dateTime": "DateTime",
        "decimal": "Float",
        "integer": "Int",
    }.get(_infer_column_type(field_name), "String")
    return graphql_type


def _table_type_block(table: dict) -> str:
    name = _pascal(table.get("name", "Item"))
    fields = table.get("key_fields", []) or []
    field_lines = "\n".join(f"  {_slug(f)}: {_lighthouse_scalar(f)}" for f in fields)
    return f"""type {name} {{
  id: ID!
{field_lines}
  created_at: DateTime!
  updated_at: DateTime!
}}"""


def _mutation_args(table: dict, required: bool) -> str:
    fields = table.get("key_fields", []) or []
    suffix = "!" if required else ""
    return ", ".join(f"{_slug(f)}: {_lighthouse_scalar(f)}{suffix}" for f in fields)


def _search_field_name(table_name: str) -> str:
    return f"search{_pascal(table_name)}"


def _graphql_schema(tables: list[dict]) -> str:
    """Directive-driven CRUD is fully deterministic and fully real —
    Lighthouse's @all/@find/@create/@update/@delete directives map
    GraphQL operations DIRECTLY onto Eloquent at the framework level, no
    separate resolver code to write (confirmed against Lighthouse's own
    current eloquent docs while writing this — see module header). The
    one thing directives can't express is real search/filter logic
    specific to this app's fields, so each table also gets one
    `@field(resolver:)`-bound search query — see _graphql_routes()."""
    if not tables:
        return "type Query {\n  _placeholder: Boolean\n}\n"

    types = "\n\n".join(_table_type_block(t) for t in tables)
    query_fields, mutation_fields = [], []
    for t in tables:
        name = _pascal(t.get("name", "Item"))
        plural = f"{name[0].lower()}{name[1:]}s"
        singular = name[0].lower() + name[1:]
        query_fields.append(f"  {plural}: [{name}!]! @paginate(defaultCount: 25)")
        query_fields.append(f"  {singular}(id: ID @eq): {name} @find")
        query_fields.append(
            f"  {_search_field_name(t.get('name', 'Item'))}(term: String!): [{name}!]! "
            f'@field(resolver: "App\\\\GraphQL\\\\Queries\\\\CustomQueries@{_search_field_name(t.get("name", "Item"))}")'
        )
        mutation_fields.append(
            f"  create{name}({_mutation_args(t, False)}): {name}! @create"
        )
        mutation_fields.append(
            f"  update{name}(id: ID!, {_mutation_args(t, False)}): {name}! @update"
        )
        mutation_fields.append(f"  delete{name}(id: ID! @whereKey): {name} @delete")

    query_block = "type Query {\n" + "\n".join(query_fields) + "\n}"
    mutation_block = "type Mutation {\n" + "\n".join(mutation_fields) + "\n}"
    return f"{query_block}\n\n{mutation_block}\n\n{types}\n"


async def _graphql_routes(ctx: RoutesCtx) -> list[FileResult]:
    schema_sdl = _graphql_schema(ctx.tables)
    tables_text = (
        "\n".join(
            f"- {_search_field_name(t.get('name', 'Item'))}($root, array $args): searches "
            f"{_pascal(t.get('name', 'Item'))} (fields: {', '.join(_slug(f) for f in (t.get('key_fields', []) or []))}) "
            f"by the string argument $args['term']"
            for t in ctx.tables
        )
        or "(no tables)"
    )
    endpoints_text = "\n".join(
        f"- {e.get('method')} {e.get('path')}: {e.get('purpose')}"
        for e in ctx.endpoints
    )

    prompt = f"""A Lighthouse GraphQL schema (below) has ALREADY been generated deterministically for this app — every field except the search ones is handled entirely by Lighthouse's own directives (@all/@find/@create/@update/@delete), so there is nothing to implement for those. Write the ONE PHP resolver class that implements every search method the schema references via @field(resolver:).

Already-generated schema.graphql contract (for context — do not redefine any of its types):
{schema_sdl}

Search methods this class must define (EXACT method names — the schema above references them):
{tables_text}

The real-world capabilities this app needs (use this to inform what "search" should reasonably
match on for each model — which fields are the meaningful ones to search, given its purpose):
{endpoints_text}

Requirements:
- `<?php\\n\\nnamespace App\\GraphQL\\Queries;` then `use App\\Models\\X;` for every model.
- Class name: `CustomQueries` (exported).
- One `public function search{{Table}}($root, array $args)` method per search method listed above,
  doing a REAL Eloquent query against real text/string columns of that model
  (`X::where('column', 'like', '%' . $args['term'] . '%')->orWhere(...)->get()` across whichever
  of the model's real fields are meaningfully searchable — never hardcoded/fake data).
- Implement the actual behavior implied by the key features and user stories above.
- No placeholders or TODOs — every method must be fully implemented.

Return ONLY the raw PHP code for this one file (including `<?php` and the namespace declaration).
No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(
        prompt,
        "php",
        GROQ_FILE_MAX_TOKENS,
        user=ctx.user,
        db=ctx.db,
        context=ctx.shared_context(),
    )
    return [
        (
            GeneratedFile(
                path=_GRAPHQL_SCHEMA_PATH,
                language="text",
                content=schema_sdl,
                description="Lighthouse GraphQL schema — real, directive-driven CRUD against Eloquent, plus one real search field per table",
            ),
            None,
        ),
        (
            GeneratedFile(
                path="backend/app/GraphQL/Queries/CustomQueries.php",
                language="php",
                content=content,
                description="Real search resolvers for the schema's @field(resolver:)-bound queries",
            ),
            issue,
        ),
    ]


ROUTES_BUILDERS = {"rest": _rest_routes, "graphql": _graphql_routes}


async def generate_routes(ctx: RoutesCtx) -> list[FileResult]:
    return await ROUTES_BUILDERS[ctx.api_style](ctx)


_GRAPHQL_SCHEMA_PATH = "backend/graphql/schema.graphql"


def _is_graphql(ctx: WiringCtx) -> bool:
    return any(f.path == _GRAPHQL_SCHEMA_PATH for f in ctx.routes_files)


def _build_migration_php(index: int, table: dict) -> tuple[str, str]:
    table_name = table.get("name", "Item")
    plural = _table_slug(table_name)
    fields = [
        f
        for f in (table.get("key_fields", []) or [])
        if _slug(f) not in ("created_at", "updated_at")
    ]
    columns = "\n".join(
        f"            $table->{_infer_column_type(f)}('{_slug(f)}');" for f in fields
    )

    content = f"""<?php

use Illuminate\\Database\\Migrations\\Migration;
use Illuminate\\Database\\Schema\\Blueprint;
use Illuminate\\Support\\Facades\\Schema;

return new class extends Migration
{{
    public function up(): void
    {{
        Schema::create('{plural}', function (Blueprint $table) {{
            $table->id();
{columns}
            $table->timestamps();
        }});
    }}

    public function down(): void
    {{
        Schema::dropIfExists('{plural}');
    }}
}};
"""
    # Matches Laravel's real migration filename convention
    # (YYYY_MM_DD_HHMMSS_description.php) — the date itself is a fixed
    # placeholder, only `index` needs to vary, to keep migrations sorting
    # in a stable order matching the tables list.
    filename = f"2024_01_01_{index:06d}_create_{_slug(plural)}_table.php"
    return filename, content


def _build_routes_api_php(endpoints: list[dict]) -> str:
    lines = (
        "\n".join(
            f"Route::{e.get('method', 'GET').lower()}('{_laravel_path(e.get('path', '/'))}', "
            f"[ApiController::class, '{_view_name(e.get('method', 'GET'), e.get('path', '/'))}']);"
            for e in endpoints
        )
        or "// no endpoints defined"
    )
    return f"""<?php

use App\\Http\\Controllers\\ApiController;
use Illuminate\\Support\\Facades\\Route;

{lines}
"""


_BOOTSTRAP_APP_PHP = """<?php

use Illuminate\\Foundation\\Application;
use Illuminate\\Foundation\\Configuration\\Exceptions;
use Illuminate\\Foundation\\Configuration\\Middleware;

return Application::configure(basePath: dirname(__DIR__))
    ->withRouting(
        api: __DIR__.'/../routes/api.php',
        commands: __DIR__.'/../routes/console.php',
    )
    ->withMiddleware(function (Middleware $middleware) {
        $middleware->api(prepend: [
            \\Illuminate\\Http\\Middleware\\HandleCors::class,
        ]);
    })
    ->withExceptions(function (Exceptions $exceptions) {
        //
    })->create();
"""

_PUBLIC_INDEX_PHP = """<?php

use Illuminate\\Foundation\\Application;
use Illuminate\\Http\\Request;

define('LARAVEL_START', microtime(true));

require __DIR__.'/../vendor/autoload.php';

(require_once __DIR__.'/../bootstrap/app.php')
    ->handleRequest(Request::capture());
"""

_ARTISAN = """#!/usr/bin/env php
<?php

define('LARAVEL_START', microtime(true));

require __DIR__.'/vendor/autoload.php';

$app = require_once __DIR__.'/bootstrap/app.php';

$status = (function () use ($app) {
    $kernel = $app->make(Illuminate\\Contracts\\Console\\Kernel::class);
    return $kernel->handle(
        $input = new Symfony\\Component\\Console\\Input\\ArgvInput,
        new Symfony\\Component\\Console\\Output\\ConsoleOutput
    );
})();

exit($status);
"""

_ROUTES_CONSOLE_PHP = """<?php

// No custom Artisan commands generated for this app.
"""


def _composer_json(project_name: str, graphql: bool) -> str:
    import json

    package_name = f"vengaicode/{_slug(project_name).replace('_', '-')}"
    require = {
        "php": "^8.2",
        "laravel/framework": "^11.0",
    }
    if graphql:
        # Version confirmed live via nuwave/lighthouse's own GitHub
        # release/composer.json at the time this was written.
        require["nuwave/lighthouse"] = "^6.70"

    return (
        json.dumps(
            {
                "name": package_name,
                "type": "project",
                "require": require,
                "autoload": {"psr-4": {"App\\\\": "app/"}},
            },
            indent=2,
        )
        + "\n"
    )


def _env_file() -> str:
    return """APP_NAME=Laravel
APP_ENV=local
APP_KEY=
APP_DEBUG=true
APP_URL=http://localhost:8000

DB_CONNECTION=sqlite
DB_DATABASE=database/database.sqlite
"""


def _database_php() -> str:
    return """<?php

return [
    'default' => 'sqlite',
    'connections' => [
        'sqlite' => [
            'driver' => 'sqlite',
            'database' => database_path('database.sqlite'),
            'prefix' => '',
        ],
    ],
];
"""


def manifest_files(ctx: WiringCtx) -> list[GeneratedFile]:
    return [
        GeneratedFile(
            path="backend/composer.json",
            language="json",
            content=_composer_json(ctx.project_name, _is_graphql(ctx)),
            description="PHP dependency manifest",
        ),
        GeneratedFile(
            path="backend/.env",
            language="text",
            content=_env_file(),
            description="Environment config (SQLite, zero external setup)",
        ),
        GeneratedFile(
            path="backend/config/database.php",
            language="php",
            content=_database_php(),
            description="Database config",
        ),
    ]


def entry_point_files(ctx: WiringCtx) -> list[GeneratedFile]:
    files = [
        GeneratedFile(
            path="backend/bootstrap/app.php",
            language="php",
            content=_BOOTSTRAP_APP_PHP,
            description="Laravel 11 application bootstrap",
        ),
        GeneratedFile(
            path="backend/public/index.php",
            language="php",
            content=_PUBLIC_INDEX_PHP,
            description="HTTP entry point",
        ),
        GeneratedFile(
            path="backend/artisan",
            language="php",
            content=_ARTISAN,
            description="Artisan CLI entry point",
        ),
        GeneratedFile(
            path="backend/routes/console.php",
            language="php",
            content=_ROUTES_CONSOLE_PHP,
            description="Console routes (none generated)",
        ),
    ]
    if _is_graphql(ctx):
        # bootstrap/app.php's withRouting(api: .../routes/api.php) needs
        # this file to exist even though Lighthouse's own service
        # provider auto-registers /graphql independently of it (Laravel,
        # unlike Lumen, needs no manual route — see module header).
        files.append(
            GeneratedFile(
                path="backend/routes/api.php",
                language="php",
                content="<?php\n\n// GraphQL only — Lighthouse's service provider auto-registers /graphql.\n// No REST routes for this project.\n",
                description="Empty REST routing file — GraphQL is served by Lighthouse's auto-registered /graphql route instead",
            )
        )
    elif ctx.endpoints:
        files.append(
            GeneratedFile(
                path="backend/routes/api.php",
                language="php",
                content=_build_routes_api_php(ctx.endpoints),
                description="API routing, deterministically wired to the exact controller method names dictated to the AI",
            )
        )
    for index, table in enumerate(ctx.tables):
        filename, content = _build_migration_php(index, table)
        files.append(
            GeneratedFile(
                path=f"backend/database/migrations/{filename}",
                language="php",
                content=content,
                description=f"Schema migration for {table.get('name', 'Item')}",
            )
        )
    return files


def setup_commands(project_name: str) -> list[str]:
    return [
        "cd backend",
        "composer install",
        "touch database/database.sqlite",
        "php artisan migrate",
        "php artisan serve",
    ]


ADAPTER = BackendAdapter(
    key="laravel",
    label="Laravel",
    supported_languages=("php",),
    supported_api_styles=tuple(ROUTES_BUILDERS),
    generate_model=generate_model,
    generate_routes=generate_routes,
    manifest_files=manifest_files,
    entry_point_files=entry_point_files,
    setup_commands=setup_commands,
)
