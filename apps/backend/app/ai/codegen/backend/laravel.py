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
#
#  2026-09-24: typed columns. A table that declares field types, foreign
#  keys, uniques, indexes or checks in the Architecture editor gets them
#  in its migration (foreignId()->constrained()->cascadeOnDelete(),
#  ->nullable(), ->default(), ->unique(), $table->index()) and in its
#  Lighthouse type; migrations run parents-first, and a typed table's
#  columns are required/optional exactly as the editor shows (instead
#  of Laravel's blanket NOT NULL). Laravel's schema
#  builder has no portable CHECK constraint, so a check becomes a clear
#  comment in the migration (and a rule in the model prompt) instead of
#  a fake one. A table that declares nothing still produces exactly the
#  output it always did — see typed_schema.py.
# ═══════════════════════════════════════════════════════════════

import json
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
    all_tables = ctx.all_tables or [ctx.table]
    schema = typed_schema.resolve_if_typed(all_tables)
    rt = typed_schema.typed_table(schema, ctx.table)
    if rt is not None:
        # The exact column names the typed migration creates.
        fields = [c.column for c in rt.columns]
    column_types = ", ".join(
        f"{column} {method}"
        for column, method in _migration_column_types(ctx.table, schema)
    )
    # Laravel's migration can't create a CHECK constraint (see
    # _check_comment_lines), so the model is where those rules live.
    check_rule = (
        "\n- Enforce every check constraint listed above in this model (e.g. a `saving` model event"
        "\n  that throws on a violation) — the migration can't enforce them in the database."
        if rt is not None and rt.checks
        else ""
    )

    prompt = f"""Write ONE complete, real Eloquent model class for the "{table_name}" table of this app.

Table purpose: {ctx.table.get("purpose", "")}
The columns below are ALREADY created by a migration — do NOT redeclare them as properties.
{db_schema.describe_table_for_prompt(ctx.table, all_tables)}
Column types the migration really creates (where these differ from the list above, these are
what the database has): {column_types or "(none besides id and timestamps)"}

Requirements:
- Class name: {class_name} extends Model (`use Illuminate\\Database\\Eloquent\\Model;`).
- Declare `protected $fillable = [{", ".join(repr(f) for f in fields)}];` for mass assignment.
- Add `$casts` for any boolean/date/datetime/decimal fields, a real `belongsTo` relationship for
  every foreign key listed above (plus any `hasMany`/`belongsTo` implied by the key features /
  user stories), and any real accessor/mutator methods the app's behavior needs.{check_rule}
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


# Lighthouse scalar for each db_schema type. Date/DateTime are Lighthouse's
# own built-in scalar classes (declared at the top of a typed schema —
# see _SCALAR_DECLARATIONS). Lighthouse ships no JSON scalar, so a json
# column is exposed as its JSON text (String) rather than pulling in an
# extra package just for it.
_LIGHTHOUSE_TYPES = {
    "string": "String",
    "text": "String",
    "integer": "Int",
    "float": "Float",
    "decimal": "Float",
    "boolean": "Boolean",
    "date": "Date",
    "datetime": "DateTime",
    "json": "String",
}

# Lighthouse resolves a custom scalar only if the schema declares it
# with its implementing class (Nuwave\Lighthouse\Schema\Types\Scalars\*).
_SCALAR_DECLARATIONS = {
    "Date": 'scalar Date @scalar(class: "Nuwave\\\\Lighthouse\\\\Schema\\\\Types\\\\Scalars\\\\Date")',
    "DateTime": 'scalar DateTime @scalar(class: "Nuwave\\\\Lighthouse\\\\Schema\\\\Types\\\\Scalars\\\\DateTime")',
}


def _lighthouse_scalar(field_name: str) -> str:
    """A table that declares nothing: the same name-based guess its
    migration's column type came from."""
    graphql_type = {
        "boolean": "Boolean",
        "dateTime": "DateTime",
        "decimal": "Float",
        "integer": "Int",
    }.get(_infer_column_type(field_name), "String")
    return graphql_type


def _type_fields(
    table: dict, schema: db_schema.ResolvedSchema | None
) -> list[tuple[str, str, bool, bool]]:
    """(field, scalar, non-null, required on create) per user column —
    the one source for the type block, the mutation arguments and the
    prompt that describes them. A table that declares nothing keeps its
    original shape (every field optional); a typed table's scalars and
    nullability follow the exact column its migration creates."""
    rt = typed_schema.typed_table(schema, table)
    if rt is None:
        return [
            (_slug(f), _lighthouse_scalar(f), False, False)
            for f in (table.get("key_fields", []) or [])
        ]
    return [
        (
            c.column,
            _LIGHTHOUSE_TYPES[_laravel_column(c, schema)[2]],
            not c.nullable,
            not c.nullable and c.default is None,
        )
        for c in rt.columns
    ]


def _table_type_block(
    table: dict, schema: db_schema.ResolvedSchema | None = None
) -> str:
    name = _pascal(table.get("name", "Item"))
    field_lines = "\n".join(
        f"  {field}: {scalar}{'!' if non_null else ''}"
        for field, scalar, non_null, _required in _type_fields(table, schema)
    )
    return f"""type {name} {{
  id: ID!
{field_lines}
  created_at: DateTime!
  updated_at: DateTime!
}}"""


def _mutation_args(
    table: dict,
    required: bool,
    schema: db_schema.ResolvedSchema | None = None,
    on_create: bool = False,
) -> str:
    """`required` marks every argument non-null. With `on_create`, a
    typed table's required columns that have no default are non-null
    too — the database would reject a create without them anyway."""
    return ", ".join(
        f"{field}: {scalar}{'!' if required or (on_create and required_on_create) else ''}"
        for field, scalar, _non_null, required_on_create in _type_fields(table, schema)
    )


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

    schema = typed_schema.resolve_if_typed(tables)
    types = "\n\n".join(_table_type_block(t, schema) for t in tables)
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
            f"  create{name}({_mutation_args(t, False, schema, on_create=True)}): {name}! @create"
        )
        mutation_fields.append(
            f"  update{name}(id: ID!, {_mutation_args(t, False, schema)}): {name}! @update"
        )
        mutation_fields.append(f"  delete{name}(id: ID! @whereKey): {name} @delete")

    query_block = "type Query {\n" + "\n".join(query_fields) + "\n}"
    mutation_block = "type Mutation {\n" + "\n".join(mutation_fields) + "\n}"
    sdl = f"{query_block}\n\n{mutation_block}\n\n{types}\n"
    if schema is None:
        return sdl
    # A typed schema declares every Lighthouse scalar it uses (DateTime
    # always — every type has created_at/updated_at).
    used = [s for s in _SCALAR_DECLARATIONS if re.search(rf":\s*{s}\b", sdl)]
    declarations = "\n".join(_SCALAR_DECLARATIONS[s] for s in used)
    return f"{declarations}\n\n{sdl}" if declarations else sdl


async def _graphql_routes(ctx: RoutesCtx) -> list[FileResult]:
    schema_sdl = _graphql_schema(ctx.tables)
    schema = typed_schema.resolve_if_typed(ctx.tables)
    tables_text = (
        "\n".join(
            f"- {_search_field_name(t.get('name', 'Item'))}($root, array $args): searches "
            f"{_pascal(t.get('name', 'Item'))} (fields: "
            + ", ".join(
                f"{field} {scalar}"
                for field, scalar, _nn, _req in _type_fields(t, schema)
            )
            + ") by the string argument $args['term']"
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


# db_schema type -> Blueprint column method + extra arguments. Sizes match
# db_schema's own (string 255, decimal 12,2).
_LARAVEL_TYPES: dict[str, tuple[str, str]] = {
    "string": ("string", f", {db_schema.STRING_LENGTH}"),
    "text": ("text", ""),
    "integer": ("integer", ""),
    "float": ("float", ""),
    "decimal": (
        "decimal",
        f", {db_schema.DECIMAL_PRECISION}, {db_schema.DECIMAL_SCALE}",
    ),
    "boolean": ("boolean", ""),
    "date": ("date", ""),
    "datetime": ("dateTime", ""),
    "json": ("json", ""),
}

_LARAVEL_ON_DELETE = {
    "cascade": "cascadeOnDelete()",
    "set_null": "nullOnDelete()",
    "restrict": "restrictOnDelete()",
}


def _php_str(text: str) -> str:
    # Single-quoted: only \ and ' are special, so no "$var" interpolation.
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


_DECIMAL_LITERAL_RE = re.compile(r"-?\d+(\.\d+)?")


def _php_default(default: dict, field_type: str) -> str:
    """The modifier that sets a column's default."""
    kind = default["kind"]
    if kind == "now":
        return "->useCurrent()"
    if kind == "today":
        # Parenthesized so it's also a valid default expression on MySQL.
        return (
            "->default(new \\Illuminate\\Database\\Query\\Expression('(CURRENT_DATE)'))"
        )
    value = default["value"]
    if field_type == "json":
        literal = _php_str(json.dumps(value, sort_keys=True))
    elif (
        field_type == "decimal"
        and isinstance(value, str)
        and _DECIMAL_LITERAL_RE.fullmatch(value)
    ):
        literal = value  # db_schema's exact decimal string, e.g. "9.99"
    elif isinstance(value, bool):
        literal = "true" if value else "false"
    elif isinstance(value, (int, float)):
        literal = repr(value)
    else:
        literal = _php_str(str(value))
    return f"->default({literal})"


def _laravel_column(
    col: db_schema.ResolvedColumn, schema: db_schema.ResolvedSchema
) -> tuple[str, str, str]:
    """(Blueprint method, its extra arguments, the db_schema type that
    amounts to) — the last is what the column's default and its
    Lighthouse scalar are rendered from, so neither can disagree with
    the column the migration actually creates."""
    ref_col = typed_schema.referenced_column(schema, col)
    if ref_col is not None:
        # Same column type as the column it points at.
        return _laravel_column(ref_col, schema)
    if col.fk is not None:
        return "foreignId", "", "integer"  # $table->id() is an unsigned bigint
    guessed = _infer_column_type(col.name)
    field_type = "datetime" if guessed == "dateTime" else guessed
    if typed_schema.keeps_guess(col, field_type, schema):
        return guessed, "", field_type
    return (*_LARAVEL_TYPES[col.type], col.type)


def _comment_text(text: str) -> str:
    """Safe inside a PHP `//` comment: a newline would end the comment,
    and `?>` would end PHP mode even inside one."""
    return re.sub(r"\s+", " ", text).replace("?>", "? >")


def _typed_migration_columns(
    rt: db_schema.ResolvedTable, schema: db_schema.ResolvedSchema
) -> tuple[list[str], list[str]]:
    """(column lines, lines that go after $table->timestamps())."""
    indent = "            "
    columns: list[str] = []
    constraints: list[str] = []
    for col in rt.columns:
        fk = col.fk
        method, args, field_type = _laravel_column(col, schema)
        line = f"$table->{method}('{col.column}'{args})"
        # Laravel makes a column NOT NULL unless told ->nullable(). A
        # table that declares nothing keeps that (its legacy output), but
        # a typed table follows db_schema's required/optional for every
        # column — what the Architecture editor showed, what the model
        # prompt says, and what the GraphQL arguments below require.
        if col.nullable:
            line += "->nullable()"
        default = typed_schema.rendered_default(col, field_type)
        if default is not None:
            line += _php_default(default, field_type)
        if col.unique:
            line += f"->unique('{col.unique_constraint_name}')"
        if fk is not None and fk.ref_column == "id":
            # Column modifiers must come before constrained() — Laravel
            # applies everything after it to the foreign key instead.
            line += (
                f"->constrained('{_table_slug(fk.ref_table)}', 'id', '{fk.constraint_name}')"
                f"->{_LARAVEL_ON_DELETE[fk.on_delete]}"
            )
        elif fk is not None:
            constraints.append(
                f"{indent}$table->foreign('{col.column}', '{fk.constraint_name}')"
                f"->references('{fk.ref_column}')->on('{_table_slug(fk.ref_table)}')"
                f"->{_LARAVEL_ON_DELETE[fk.on_delete]};"
            )
        columns.append(f"{indent}{line};")
    for idx in rt.indexes:
        cols = ", ".join(f"'{c}'" for c in idx.columns)
        method = "unique" if idx.unique else "index"
        constraints.append(f"{indent}$table->{method}([{cols}], '{idx.name}');")
    for chk in rt.checks:
        constraints += _check_comment_lines(chk, rt, indent)
    return columns, constraints


def _check_comment_lines(
    chk: db_schema.ResolvedCheck, rt: db_schema.ResolvedTable, indent: str
) -> list[str]:
    """Laravel's schema builder has no CHECK constraint method, and raw
    ALTER TABLE ... ADD CONSTRAINT isn't possible on SQLite (this app's
    database) — so rather than fake one, say plainly that the database
    does NOT enforce the rule and where it is enforced instead (the
    model prompt tells the AI to enforce every check)."""
    return [
        f'{indent}// CHECK "{_comment_text(chk.name)}" ({chk.constraint_name}): {_comment_text(chk.sql)}',
        f"{indent}// Not enforced by the database — Laravel's schema builder has no portable CHECK",
        f"{indent}// constraint. The App\\Models\\{rt.class_name} model enforces it before every save.",
    ]


def _migration_column_types(
    table: dict, schema: db_schema.ResolvedSchema | None
) -> list[tuple[str, str]]:
    """(column, Blueprint method) for every column _build_migration_php
    creates besides id/timestamps — what the model prompt quotes, so the
    AI's $casts match the real column types."""
    rt = typed_schema.typed_table(schema, table)
    if rt is None:
        return [
            (_slug(f), _infer_column_type(f))
            for f in (table.get("key_fields", []) or [])
            if _slug(f) not in ("created_at", "updated_at")
        ]
    return [(c.column, _laravel_column(c, schema)[0]) for c in rt.columns]


def _build_migration_php(
    index: int, table: dict, schema: db_schema.ResolvedSchema | None = None
) -> tuple[str, str]:
    """`schema` is the whole architecture resolved (typed_schema.
    resolve_if_typed) — needed to type a foreign key after the column
    it references; None resolves this table on its own."""
    table_name = table.get("name", "Item")
    plural = _table_slug(table_name)
    if schema is None:
        schema = typed_schema.resolve_if_typed([table])
    rt = typed_schema.typed_table(schema, table)
    if rt is not None:
        column_lines, after_timestamps = _typed_migration_columns(rt, schema)
        columns = "\n".join(column_lines)
        trailing = "".join(f"\n{line}" for line in after_timestamps)
    else:
        fields = [
            f
            for f in (table.get("key_fields", []) or [])
            if _slug(f) not in ("created_at", "updated_at")
        ]
        columns = "\n".join(
            f"            $table->{_infer_column_type(f)}('{_slug(f)}');"
            for f in fields
        )
        trailing = ""

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
            $table->timestamps();{trailing}
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


def _database_php(foreign_keys: bool = False) -> str:
    # SQLite ignores foreign keys unless each connection turns them on,
    # and this config replaces Laravel's stock one (which does) — so any
    # project that declares a foreign key needs the flag, or ON DELETE
    # rules would silently never fire. Left out otherwise so a project
    # without foreign keys keeps the exact file it always had.
    fk_line = "\n            'foreign_key_constraints' => true," if foreign_keys else ""
    return f"""<?php

return [
    'default' => 'sqlite',
    'connections' => [
        'sqlite' => [
            'driver' => 'sqlite',
            'database' => database_path('database.sqlite'),
            'prefix' => '',{fk_line}
        ],
    ],
];
"""


def _has_foreign_keys(tables: list[dict]) -> bool:
    schema = typed_schema.resolve_if_typed(tables)
    return schema is not None and any(c.fk for t in schema.tables for c in t.columns)


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
            content=_database_php(_has_foreign_keys(ctx.tables)),
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
    schema = typed_schema.resolve_if_typed(ctx.tables)
    # Parents first, so a foreign key's table always exists when the
    # table referencing it is created (identity order with no FKs).
    order = (
        typed_schema.migration_order(ctx.tables, schema)
        if schema is not None
        else range(len(ctx.tables))
    )
    for index, table in enumerate(ctx.tables[i] for i in order):
        filename, content = _build_migration_php(index, table, schema)
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
