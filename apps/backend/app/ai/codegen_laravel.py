# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Deterministic (no-AI) PHP backend: Laravel over Eloquent
#  + SQLite
#  ai/codegen_laravel.py — The Laravel backend codegen_deterministic
#  dispatches to: a complete, runnable Laravel app. Per table: an
#  Eloquent model (app/Models/) and a controller (app/Http/Controllers/).
#  Shared by every table: the base Controller, app/Support (RequestFields,
#  DatabaseErrors, ApiError), routes/api.php, and the bootstrap/, config/,
#  public/ and storage/ a Laravel app needs to boot.
#
#  Follows the knowledge registry's Laravel rules: $fillable on every
#  model, JSON answered with response()->json() and a proper status,
#  schema changes in migrations. One rule is deliberately not followed:
#  $request->validate(). Its rules are looser than the contract every
#  generated backend keeps ("integer" accepts "5", "boolean" accepts 1)
#  and its sentences are Laravel's own, so a request's JSON is read
#  field by field against the model's FIELDS (app/Support/
#  RequestFields.php) — strictly, and with the same sentences as the
#  other backends. The raw body is read, so Laravel's global
#  TrimStrings / ConvertEmptyStringsToNull middleware can't change a value
#  before it is stored either.
#
#  Same REST surface as every other generated backend: /api/<table> and
#  /api/<table>/<id>, JSON keyed by column name, PUT changes only the
#  fields it sends, every problem with a request reported at once, the
#  database's constraint violations answered with the same sentences.
#  Errors are {"message": ...} — Laravel's own shape — which the screens
#  read.
#
#  The schema is owned by real Laravel migrations (migrations_laravel),
#  applied with `php artisan migrate`.
#
#  Values are stored as the other SQLite backends store them, and the
#  models declare no casts: Eloquent's date cast would write a date as a
#  date-time, and its date-time format drops the fraction the migrations'
#  checks compare. RequestFields turns a request value into the stored
#  one and back, and a model's own timestamps use $dateFormat with
#  microseconds.
#
#  Names. PHP namespaces keep a model called File or Data apart from
#  PHP's own, and nothing generated is named after a column: columns are
#  array keys, set with setRawAttributes() and read with getAttributes(),
#  so no Eloquent accessor, mutator or property can be hit by a column's
#  name. Models are referred to by their full name (\App\Models\Book), so
#  a model can't collide with a class a file imports.
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import re

from app.ai import db_schema
from app.ai.codegen_shared import GeneratedFile
from app.ai.migrations_laravel import comment

# Laravel 13 is the current release; it needs PHP 8.3 or newer.
LARAVEL_VERSION = "13"
PHP_VERSION = "8.3"
DEFAULT_PORT = 8000

# How a request value is read, stored and answered for a column
# (RequestFields).
_KINDS = {
    "string": "string",
    "text": "string",
    "integer": "integer",
    "float": "float",
    "decimal": "decimal",
    "boolean": "boolean",
    "date": "date",
    "datetime": "datetime",
    "json": "json",
}


# ───────────────────────────────────────────────
#  Text helpers
# ───────────────────────────────────────────────
def php_str(text: str) -> str:
    """A single-quoted PHP string: only \\ and ' are special, so nothing in
    user text can be read as a variable. "TODO" is split so the
    generated-file check doesn't mistake a table's name for a marker."""
    body = str(text).replace("\\", "\\\\").replace("'", "\\'")
    return "'" + body.replace("TODO", "TO'.'DO") + "'"


_TOKEN = re.compile(r"__([A-Z_]+?)__")


def _fill(template: str, **values: str) -> str:
    """Every __TOKEN__ replaced in one pass, so a value (a table's label,
    say) that happens to contain a token's text is left as written. PHP's
    own __DIR__ is not a token."""
    return _TOKEN.sub(lambda m: values.get(m.group(1), m.group(0)), template)


def model_class(class_name: str) -> str:
    return f"\\App\\Models\\{class_name}"


def controller_class(class_name: str) -> str:
    return f"{class_name}Controller"


# Class names PHP keeps for itself beyond its keywords and type names,
# which the schema check already refuses.
_RESERVED_CLASSES = frozenset({"self", "parent"})


def name_problems(schema: db_schema.ResolvedSchema) -> list[str]:
    """What PHP would refuse in a model's class name. Columns are only
    array keys here (see the header), so they need no rule of their own."""
    problems = []
    owners: dict[str, db_schema.ResolvedTable] = {}
    for t in schema.tables:
        folded = t.class_name.lower()
        if folded in _RESERVED_CLASSES:
            problems.append(
                f'The table "{t.name}" would produce a class named {t.class_name}, '
                "a name PHP keeps for itself — rename the table in Architecture."
            )
        elif folded in owners:
            other = owners[folded]
            problems.append(
                f'The table "{t.name}" would produce a class named {t.class_name}, which PHP '
                f'can\'t tell apart from {other.class_name} (the table "{other.name}") — PHP '
                "class names ignore case. Rename one of them in Architecture."
            )
        else:
            owners[folded] = t
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
#  app/Models/<Class>.php
# ───────────────────────────────────────────────
def model_file(
    t: db_schema.ResolvedTable,
    snapshot: dict,
    heading: str,
    class_names: dict[str, str],
) -> GeneratedFile:
    tables = snapshot["tables"]
    table = tables[t.sql_name]
    label = comment(table["label"])
    fields = []
    for c in table["column_order"]:
        col = table["columns"][c]
        base = _base(col, tables)
        kind = base["type"]
        parts = [
            f"'kind' => '{_KINDS[kind]}'",
            f"'null' => {'true' if col['nullable'] else 'false'}",
            f"'default' => {'true' if col['default'] else 'false'}",
        ]
        if kind == "string" and base.get("length"):
            parts.append(f"'limit' => {base['length']}")
        if col["fk"]:
            fk = col["fk"]
            parts.append(
                "'references' => ["
                f"'model' => {model_class(class_names[fk['table']])}::class, "
                f"'column' => {php_str(fk['column'])}, "
                f"'label' => {php_str(tables[fk['table']]['label'])}"
                "]"
            )
        fields.append(f"        {php_str(c)} => [{', '.join(parts)}],")
    fillable = ", ".join(php_str(c) for c in table["column_order"])
    field_lines = (
        ["    public const FIELDS = [", *fields, "    ];"]
        if fields
        else ["    public const FIELDS = [];"]
    )
    lines = [
        "<?php",
        "",
        f"// {comment(heading)}",
        "//",
        "// Deterministically generated by VengaiCode from the Architecture tab (no AI",
        "// call). The table is created and changed by the migrations in",
        "// database/migrations/ (`php artisan migrate`).",
        "",
        "namespace App\\Models;",
        "",
        "use Illuminate\\Database\\Eloquent\\Model;",
        "",
        f"class {t.class_name} extends Model",
        "{",
        f"    protected $table = {php_str(t.sql_name)};",
        "",
        "    // Date-times are stored as UTC text with six fractional digits, the form the",
        "    // migrations' checks and defaults compare.",
        "    protected $dateFormat = 'Y-m-d H:i:s.u';",
        "",
        "    // Mass assignment is limited to the table's own columns.",
        f"    protected $fillable = [{fillable}];",
        "",
        "    // What a request may send for each column and what it has to satisfy; read",
        "    // by App\\Support\\RequestFields, which also turns a request value into the",
        "    // stored one and back (so there are no casts here).",
        *field_lines,
        "",
        f"    // VENGAI:CUSTOM:{t.slug}_model:start",
        f"    // Add relationships, scopes and methods for {label} here. A new column",
        "    // belongs in the Architecture tab instead, so a migration adds it to the",
        "    // database.",
        "    // This block is preserved across future regenerations.",
        f"    // VENGAI:CUSTOM:{t.slug}_model:end",
        "}",
        "",
    ]
    return GeneratedFile(
        path=f"backend/app/Models/{t.class_name}.php",
        language="php",
        content="\n".join(lines),
        description=f"Deterministic Eloquent model for {t.name}",
    )


# ───────────────────────────────────────────────
#  app/Http/Controllers/
# ───────────────────────────────────────────────
_CONTROLLER_PHP = """<?php

// REST routes for __TITLE__ — the paths the generated screens call.
// Deterministically generated by VengaiCode (no AI call); what every table's
// controller shares is in Controller and app/Support.

namespace App\\Http\\Controllers;

use App\\Support\\ApiError;
use App\\Support\\RequestFields;
use Illuminate\\Database\\QueryException;
use Illuminate\\Http\\JsonResponse;
use Illuminate\\Http\\Request;
use Illuminate\\Http\\Response;

class __CONTROLLER__ extends Controller
{
    private const LABEL = __LABEL__;

    private const RESTRICT_MESSAGE = __RESTRICT__;

    public function index(): JsonResponse
    {
        return response()->json(RequestFields::rows(__MODEL__::query()->orderBy('id')->get()));
    }

    public function show(string $id): JsonResponse
    {
        return response()->json(RequestFields::row($this->find(__MODEL__::class, self::LABEL, $id)));
    }

    public function store(Request $request): JsonResponse
    {
        $record = new __MODEL__();
        RequestFields::fill($record, $this->body($request), creating: true);
        $record->save();

        // Answered as stored.
        return response()->json(RequestFields::row($record->refresh()), 201);
    }

    // Changes only the fields the request sends, like the other generated backends.
    public function update(Request $request, string $id): JsonResponse
    {
        $record = $this->find(__MODEL__::class, self::LABEL, $id);
        RequestFields::fill($record, $this->body($request), creating: false);
        $record->setUpdatedAt($record->freshTimestamp());
        $record->save();

        return response()->json(RequestFields::row($record->refresh()));
    }

    // A 404 when the row isn't there, a 409 when other rows still need it.
    public function destroy(string $id): Response
    {
        $record = $this->find(__MODEL__::class, self::LABEL, $id);
        try {
            $record->delete();
        } catch (QueryException $refusal) {
            if (str_contains($refusal->getMessage(), 'FOREIGN KEY constraint failed')) {
                throw new ApiError(409, self::RESTRICT_MESSAGE);
            }
            throw $refusal;
        }

        return response()->noContent();
    }

    // VENGAI:CUSTOM:__SLUG___routes:start
    // Add custom, non-CRUD actions here (and their routes in routes/api.php).
    // This block is preserved across regenerations.
    // VENGAI:CUSTOM:__SLUG___routes:end
}
"""


def controller_file(t: db_schema.ResolvedTable, snapshot: dict) -> GeneratedFile:
    return GeneratedFile(
        path=f"backend/app/Http/Controllers/{controller_class(t.class_name)}.php",
        language="php",
        content=_fill(
            _CONTROLLER_PHP,
            TITLE=comment(t.name),
            CONTROLLER=controller_class(t.class_name),
            MODEL=model_class(t.class_name),
            LABEL=php_str(snapshot["tables"][t.sql_name]["label"]),
            RESTRICT=php_str(_restrict_message(t.sql_name, snapshot)),
            SLUG=t.slug,
        ),
        description=f"REST routes for {t.name}",
    )


_BASE_CONTROLLER_PHP = """<?php

// What every table's controller shares: reading a request's JSON and finding
// the row a path names. Written by VengaiCode.

namespace App\\Http\\Controllers;

use App\\Support\\ApiError;
use Illuminate\\Database\\Eloquent\\Model;
use Illuminate\\Http\\Request;

abstract class Controller
{
    // The request's JSON object; a 400 for anything else. The raw body is read,
    // so a value arrives exactly as it was sent.
    protected function body(Request $request): \\stdClass
    {
        $body = json_decode($request->getContent());
        if (! $body instanceof \\stdClass) {
            throw new ApiError(400, 'Send the record as a JSON object.');
        }

        return $body;
    }

    // The row the path's {id} names; a 400 when that isn't a number, a 404 when
    // no row has it.
    protected function find(string $model, string $label, string $id): Model
    {
        if (preg_match('/^-?[0-9]+$/D', $id) !== 1) {
            throw new ApiError(400, 'id: not a valid id');
        }

        return $model::query()->find((int) $id)
            ?? throw new ApiError(404, $label.' '.(int) $id.' not found.');
    }
}
"""

_API_ERROR_PHP = """<?php

// A failure with the HTTP status to answer it with; bootstrap/app.php turns one
// into {"message": "..."}. Written by VengaiCode.

namespace App\\Support;

use RuntimeException;

final class ApiError extends RuntimeException
{
    public function __construct(public readonly int $status, string $message)
    {
        parent::__construct($message);
    }
}
"""

_REQUEST_FIELDS_PHP = """<?php

// Reads a request's JSON into a model, field by field, against the model's
// FIELDS — and turns stored rows back into what the API answers. Written by
// VengaiCode.
//
// Every field is checked first, and every problem is reported at once as one
// 422; every foreign key has to point at a row that exists; only then are the
// fields the request sent set. A request may leave a field out (the default
// applies, or an update keeps the value) or send it as null — json_decode()'s
// object keeps the two apart.
//
// Values are stored the way SQLite compares them: date-times as UTC text with
// six fractional digits ("2024-01-31 09:30:00.000000"), dates as "2024-01-31",
// booleans as 0/1 and JSON as its text.

namespace App\\Support;

use DateTimeImmutable;
use DateTimeZone;
use Illuminate\\Database\\Eloquent\\Model;
use InvalidArgumentException;

final class RequestFields
{
    // Digits a decimal keeps, and how many of them follow the point.
    public const DECIMAL_DIGITS = __DIGITS__;

    public const DECIMAL_PLACES = __PLACES__;

    private const NOT_A_DECIMAL = 'expected a number like 12.50';

    private const STORED = 'Y-m-d H:i:s.u';

    private const DATE_TIME = '/^(\\d{4})-(\\d{2})-(\\d{2})[T ](\\d{2}):(\\d{2})(?::(\\d{2})(\\.\\d{1,9})?)?(Z|[+-]\\d{2}:\\d{2})?$/D';

    public static function fill(Model $record, \\stdClass $body, bool $creating): void
    {
        $fields = $record::FIELDS;
        $problems = [];
        $values = [];
        foreach ($fields as $name => $field) {
            if (! property_exists($body, $name)) {
                continue;
            }
            try {
                $values[$name] = $body->{$name} === null ? null : self::parse($field['kind'], $body->{$name});
            } catch (InvalidArgumentException $mismatch) {
                // A value of the wrong kind, named by its field.
                $problems[] = $name.': '.$mismatch->getMessage();
            }
        }
        foreach ($fields as $name => $field) {
            $sent = property_exists($body, $name);
            if (! $field['null']) {
                if ($sent && $body->{$name} === null) {
                    $problems[] = $name.': may not be null';
                } elseif ($creating && ! $sent && ! $field['default']) {
                    $problems[] = $name.': is required';
                }
            }
            $value = $values[$name] ?? null;
            if (isset($field['limit']) && is_string($value) && mb_strlen($value) > $field['limit']) {
                $problems[] = $name.': at most '.$field['limit'].' characters';
            }
        }
        if ($problems !== []) {
            throw new ApiError(422, implode("\\n", $problems));
        }

        foreach ($fields as $name => $field) {
            $value = $values[$name] ?? null;
            if (! isset($field['references']) || $value === null) {
                continue;
            }
            $target = $field['references'];
            if (! $target['model']::query()->where($target['column'], $value)->exists()) {
                throw new ApiError(422, $name.': no row in '.$target['label'].' has '.$target['column'].' '.$value.'.');
            }
        }

        // Set directly: the values are already in their stored form.
        $record->setRawAttributes(array_merge($record->getAttributes(), $values));
    }

    // Every row, as the API answers it.
    public static function rows(iterable $records): array
    {
        $rows = [];
        foreach ($records as $record) {
            $rows[] = self::row($record);
        }

        return $rows;
    }

    // A row as the API answers it: keyed by column name, numbers as numbers,
    // true/false as booleans, date-times as RFC 3339 UTC, JSON as JSON.
    public static function row(Model $record): array
    {
        $stored = $record->getAttributes();
        $row = ['id' => (int) $stored['id']];
        foreach ($record::FIELDS as $name => $field) {
            $row[$name] = self::shown($field['kind'], $stored[$name] ?? null);
        }
        $row['created_at'] = self::shown('datetime', $stored['created_at'] ?? null);
        $row['updated_at'] = self::shown('datetime', $stored['updated_at'] ?? null);

        return $row;
    }

    // A request value in the form it is stored in.
    private static function parse(string $kind, mixed $value): mixed
    {
        switch ($kind) {
            case 'string':
                return is_string($value) ? $value : throw new InvalidArgumentException('expected text');
            case 'integer':
                return is_int($value) ? $value : throw new InvalidArgumentException('expected a whole number');
            case 'float':
                return (is_int($value) || is_float($value)) && is_finite((float) $value)
                    ? (float) $value
                    : throw new InvalidArgumentException('expected a number');
            case 'boolean':
                return is_bool($value) ? (int) $value : throw new InvalidArgumentException('expected true or false');
            case 'decimal':
                return self::decimal($value);
            case 'date':
                return self::date($value);
            case 'datetime':
                return self::dateTime($value);
            default:
                return json_encode($value, JSON_THROW_ON_ERROR | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_PRESERVE_ZERO_FRACTION);
        }
    }

    // A fixed-point number: a JSON number, or text like "12.50".
    private static function decimal(mixed $value): float
    {
        if (is_string($value)) {
            $text = trim($value);
        } elseif (is_int($value)) {
            $text = (string) $value;
        } elseif (is_float($value) && is_finite($value)) {
            // The shortest text that reads back as this number.
            $text = json_encode($value);
            if (stripos($text, 'e') !== false) {
                throw new InvalidArgumentException(
                    abs($value) >= 1 ? 'number is too large' : 'only '.self::DECIMAL_PLACES.' decimal places are stored'
                );
            }
        } else {
            throw new InvalidArgumentException(self::NOT_A_DECIMAL);
        }
        if (preg_match('/^-?([0-9]+)(?:\\.([0-9]+))?$/D', $text, $parts) !== 1) {
            throw new InvalidArgumentException(self::NOT_A_DECIMAL);
        }
        if (strlen(rtrim($parts[2] ?? '', '0')) > self::DECIMAL_PLACES) {
            throw new InvalidArgumentException('only '.self::DECIMAL_PLACES.' decimal places are stored');
        }
        if (strlen(ltrim($parts[1], '0')) > self::DECIMAL_DIGITS - self::DECIMAL_PLACES) {
            throw new InvalidArgumentException('number is too large');
        }

        return (float) $text;
    }

    // A date: "2024-01-31".
    private static function date(mixed $value): string
    {
        if (
            is_string($value)
            && preg_match('/^(\\d{4})-(\\d{2})-(\\d{2})$/D', trim($value), $parts) === 1
            && checkdate((int) $parts[2], (int) $parts[3], (int) $parts[1])
        ) {
            return trim($value);
        }
        throw new InvalidArgumentException('expected a date like 2024-01-31');
    }

    // A date-time: RFC 3339 ("2024-01-31T09:30:00Z", any offset), or without an
    // offset, read as UTC. Kept as stored UTC text.
    private static function dateTime(mixed $value): string
    {
        $utc = new DateTimeZone('UTC');
        if (
            is_string($value)
            && preg_match(self::DATE_TIME, trim($value), $parts) === 1
            && checkdate((int) $parts[2], (int) $parts[3], (int) $parts[1])
            && (int) $parts[4] < 24
            && (int) $parts[5] < 60
            && (int) ($parts[6] ?? 0) < 60
        ) {
            return (new DateTimeImmutable(trim($value), $utc))->setTimezone($utc)->format(self::STORED);
        }
        throw new InvalidArgumentException('expected a date and time like 2024-01-31T09:30:00Z');
    }

    // A stored value as the API answers it.
    private static function shown(string $kind, mixed $value): mixed
    {
        if ($value === null) {
            return null;
        }

        return match ($kind) {
            'integer' => (int) $value,
            'float', 'decimal' => (float) $value,
            'boolean' => (bool) $value,
            'datetime' => self::rfc3339((string) $value),
            'json' => self::json((string) $value),
            default => (string) $value,
        };
    }

    private static function rfc3339(string $stored): string
    {
        $utc = new DateTimeZone('UTC');
        $when = DateTimeImmutable::createFromFormat(self::STORED, $stored, $utc)
            ?: DateTimeImmutable::createFromFormat('Y-m-d H:i:s', $stored, $utc);
        if ($when === false) {
            // Written some other way (by hand, say): answered as stored.
            return $stored;
        }

        return $when->format('Y-m-d\\TH:i:s').rtrim(rtrim($when->format('.u'), '0'), '.').'Z';
    }

    private static function json(string $stored): mixed
    {
        $value = json_decode($stored);

        return $value === null && trim($stored) !== 'null' ? $stored : $value;
    }
}
"""

_DATABASE_ERRORS_PHP = """<?php

// What a refusal by the database means, so a violated constraint comes back as
// a sentence instead of a raw database error. Written by VengaiCode.

namespace App\\Support;

use Illuminate\\Database\\QueryException;

final class DatabaseErrors
{
    // [its name in the database's message, HTTP status, sentence]. Longest
    // names first.
    private const CONSTRAINTS = [
__CONSTRAINTS__    ];

    public static function explain(QueryException $refusal): ApiError
    {
        // The driver's own message: Laravel's adds the statement and its values.
        $text = $refusal->getPrevious()?->getMessage() ?? $refusal->getMessage();
        if (str_contains($text, 'UNIQUE constraint failed') || str_contains($text, 'CHECK constraint failed')) {
            // SQLite names a failed UNIQUE by its columns, a failed CHECK by its name.
            foreach (self::CONSTRAINTS as [$key, $status, $message]) {
                if (self::names($text, $key)) {
                    return new ApiError($status, $message);
                }
            }
        }
        if (preg_match('/NOT NULL constraint failed: (\\S+)/', $text, $parts) === 1) {
            return new ApiError(422, $parts[1].': may not be null');
        }
        if (str_contains($text, 'FOREIGN KEY constraint failed')) {
            return new ApiError(422, "A record this one refers to doesn't exist.");
        }

        return new ApiError(409, 'The database refused this change: '.$text);
    }

    // Whether the message names $key whole, not as part of a longer name.
    private static function names(string $text, string $key): bool
    {
        return preg_match('/(?<![A-Za-z0-9_.])'.preg_quote($key, '/').'(?![A-Za-z0-9_.])/', $text) === 1;
    }
}
"""


def shared_files(constraints: list[tuple[str, int, str]]) -> list[GeneratedFile]:
    entries = "".join(
        f"        [{php_str(k)}, {s}, {php_str(m)}],\n"
        for k, s, m in sorted(constraints, key=lambda e: -len(e[0]))
    )

    def php(path: str, content: str, description: str) -> GeneratedFile:
        return GeneratedFile(
            path=f"backend/{path}",
            language="php",
            content=content,
            description=description,
        )

    return [
        php(
            "app/Http/Controllers/Controller.php",
            _BASE_CONTROLLER_PHP,
            "What every controller shares: reading a request and finding a row",
        ),
        php(
            "app/Support/ApiError.php",
            _API_ERROR_PHP,
            "A failure with the HTTP status to answer it with",
        ),
        php(
            "app/Support/RequestFields.php",
            _fill(
                _REQUEST_FIELDS_PHP,
                DIGITS=str(db_schema.DECIMAL_PRECISION),
                PLACES=str(db_schema.DECIMAL_SCALE),
            ),
            "Reads and checks a request's fields against the model's FIELDS; answers rows",
        ),
        php(
            "app/Support/DatabaseErrors.php",
            _fill(_DATABASE_ERRORS_PHP, CONSTRAINTS=entries),
            "What each database constraint means",
        ),
    ]


_ROUTES_API_PHP = """<?php

// /api/<table> and /api/<table>/{id} for every table (bootstrap/app.php adds the
// /api prefix). Written by VengaiCode.

use Illuminate\\Support\\Facades\\Route;

__ROUTES__
// VENGAI:CUSTOM:extra_routes:start
// Add routes for custom actions here, e.g.
// Route::get('books/export', [\\App\\Http\\Controllers\\BookController::class, 'export']);
// This block is preserved across regenerations.
// VENGAI:CUSTOM:extra_routes:end
"""


def routes_file(schema: db_schema.ResolvedSchema) -> GeneratedFile:
    blocks = []
    for t in schema.tables:
        target = f"\\App\\Http\\Controllers\\{controller_class(t.class_name)}::class"
        path = php_str(t.sql_name)
        one = php_str(f"{t.sql_name}/{{id}}")
        blocks.append(
            f"Route::get({path}, [{target}, 'index']);\n"
            f"Route::post({path}, [{target}, 'store']);\n"
            f"Route::get({one}, [{target}, 'show']);\n"
            f"Route::put({one}, [{target}, 'update']);\n"
            f"Route::delete({one}, [{target}, 'destroy']);\n"
        )
    return GeneratedFile(
        path="backend/routes/api.php",
        language="php",
        content=_fill(_ROUTES_API_PHP, ROUTES="\n".join(blocks)),
        description="Routes: /api/<table> and /api/<table>/{id} for every table",
    )


# ───────────────────────────────────────────────
#  bootstrap/, config/, public/, storage/ and composer.json (the Laravel
#  adapter's migrations mode)
# ───────────────────────────────────────────────
_BOOTSTRAP_APP_PHP = """<?php

// __TITLE__ API, written by VengaiCode.
//
// `php artisan migrate` applies the database migrations and `php artisan serve`
// serves the API on port __PORT__ (--port changes it). The database is SQLite:
// database/database.sqlite, or the file DATABASE_PATH names.

use App\\Support\\ApiError;
use App\\Support\\DatabaseErrors;
use Illuminate\\Database\\QueryException;
use Illuminate\\Foundation\\Application;
use Illuminate\\Foundation\\Configuration\\Exceptions;
use Illuminate\\Foundation\\Configuration\\Middleware;
use Illuminate\\Support\\Facades\\Route;

return Application::configure(basePath: dirname(__DIR__))
    ->withRouting(
        api: __DIR__.'/../routes/api.php',
        commands: __DIR__.'/../routes/console.php',
        then: function () {
            Route::get('/', fn () => response()->json(['message' => __MESSAGE__]));
        },
    )
    ->withMiddleware(function (Middleware $middleware) {
        // Laravel's defaults: among them the CORS handling config/cors.php sets up.
    })
    ->withExceptions(function (Exceptions $exceptions) {
        // Every failure answers {"message": "..."} with its HTTP status, which is
        // what the generated screens show.
        $exceptions->render(fn (ApiError $problem) => response()->json(['message' => $problem->getMessage()], $problem->status));

        // A refusal by the database, explained.
        $exceptions->render(function (QueryException $refusal) {
            $problem = DatabaseErrors::explain($refusal);

            return response()->json(['message' => $problem->getMessage()], $problem->status);
        });

        // A request that breaks a rule isn't an error worth a log entry.
        $exceptions->dontReport([ApiError::class]);

        // An API: every error is answered as JSON.
        $exceptions->shouldRenderJsonWhen(fn () => true);
    })->create();
"""

_PUBLIC_INDEX_PHP = """<?php

use Illuminate\\Foundation\\Application;
use Illuminate\\Http\\Request;

define('LARAVEL_START', microtime(true));

require __DIR__.'/../vendor/autoload.php';

/** @var Application $app */
$app = require_once __DIR__.'/../bootstrap/app.php';

$app->handleRequest(Request::capture());
"""

_ARTISAN = """#!/usr/bin/env php
<?php

use Illuminate\\Foundation\\Application;
use Symfony\\Component\\Console\\Input\\ArgvInput;

define('LARAVEL_START', microtime(true));

require __DIR__.'/vendor/autoload.php';

/** @var Application $app */
$app = require_once __DIR__.'/bootstrap/app.php';

$status = $app->handleCommand(new ArgvInput);

exit($status);
"""

_ROUTES_CONSOLE_PHP = """<?php

// Custom Artisan commands go here; none are generated for this app.
"""

_CONFIG_DATABASE_PHP = """<?php

// SQLite. Set DATABASE_PATH to keep the database somewhere else.

return [
    'default' => 'sqlite',

    'connections' => [
        'sqlite' => [
            'driver' => 'sqlite',
            'database' => env('DATABASE_PATH', database_path('database.sqlite')),
            'prefix' => '',
            // SQLite enforces foreign keys only on connections that ask for it.
            'foreign_key_constraints' => true,
            // A writer waits for another one instead of failing.
            'busy_timeout' => 5000,
        ],
    ],
];
"""

_CONFIG_CORS_PHP = """<?php

// The screens may call the API from another origin (a packaged app's window
// isn't the API's origin).

return [
    'paths' => ['*'],
    'allowed_methods' => ['*'],
    'allowed_origins' => ['*'],
    'allowed_origins_patterns' => [],
    'allowed_headers' => ['*'],
    'exposed_headers' => [],
    'max_age' => 0,
    'supports_credentials' => false,
];
"""

# Nothing here needs a database table, a cookie or an encryption key: the API
# keeps no session, and the cache and queue are only Laravel's own plumbing.
_ENV = """APP_ENV=local
APP_DEBUG=true
APP_KEY=
LOG_CHANNEL=single
CACHE_STORE=file
SESSION_DRIVER=array
QUEUE_CONNECTION=sync
"""

# Laravel writes into these folders and won't create them itself.
_KEEP_FOLDER = "*\n!.gitignore\n"
_RUNTIME_FOLDERS = (
    "bootstrap/cache",
    "storage/framework/cache/data",
    "storage/framework/sessions",
    "storage/framework/views",
    "storage/logs",
)


def composer_json() -> str:
    return (
        json.dumps(
            {
                "name": "vengaicode/generated-app",
                "type": "project",
                "require": {
                    "php": f"^{PHP_VERSION}",
                    "laravel/framework": f"^{LARAVEL_VERSION}.0",
                },
                "autoload": {"psr-4": {"App\\": "app/"}},
                "config": {"optimize-autoloader": True, "sort-packages": True},
                "minimum-stability": "stable",
                "prefer-stable": True,
            },
            indent=4,
        )
        + "\n"
    )


def manifest_files() -> list[GeneratedFile]:
    return [
        GeneratedFile(
            path="backend/composer.json",
            language="json",
            content=composer_json(),
            description="PHP dependency manifest",
        ),
        GeneratedFile(
            path="backend/.env",
            language="text",
            content=_ENV,
            description="Environment settings",
        ),
        GeneratedFile(
            path="backend/config/database.php",
            language="php",
            content=_CONFIG_DATABASE_PHP,
            description="Database connection settings (SQLite)",
        ),
        GeneratedFile(
            path="backend/config/cors.php",
            language="php",
            content=_CONFIG_CORS_PHP,
            description="Allows cross-origin calls",
        ),
    ]


def entry_point_files(project_name: str) -> list[GeneratedFile]:
    def php(path: str, content: str, description: str) -> GeneratedFile:
        return GeneratedFile(
            path=f"backend/{path}",
            language="php",
            content=content,
            description=description,
        )

    return [
        php(
            "bootstrap/app.php",
            _fill(
                _BOOTSTRAP_APP_PHP,
                TITLE=comment(project_name),
                PORT=str(DEFAULT_PORT),
                MESSAGE=php_str(f"{project_name} API is running"),
            ),
            "Laravel application bootstrap: routes, and how errors are answered",
        ),
        php("public/index.php", _PUBLIC_INDEX_PHP, "HTTP entry point"),
        php("artisan", _ARTISAN, "The `artisan` command for this app"),
        php("routes/console.php", _ROUTES_CONSOLE_PHP, "Console routes"),
        *[
            GeneratedFile(
                path=f"backend/{folder}/.gitignore",
                language="text",
                content=_KEEP_FOLDER,
                description="Keeps a folder Laravel writes into",
            )
            for folder in _RUNTIME_FOLDERS
        ],
        GeneratedFile(
            path="backend/database/.gitignore",
            language="text",
            content="*.sqlite*\n",
            description="Keeps the database file out of version control",
        ),
    ]


def backend_files(
    schema: db_schema.ResolvedSchema,
    constraints: list[tuple[str, int, str]],
    headings: dict[str, str],
) -> tuple[list[GeneratedFile], list[GeneratedFile]]:
    """(model files, other backend files) — the first backend file is
    routes/api.php, which the wiring context calls the routes file."""
    snapshot = db_schema.snapshot(schema)
    class_names = {t.sql_name: t.class_name for t in schema.tables}
    models = [
        model_file(t, snapshot, headings[t.sql_name], class_names)
        for t in schema.tables
    ]
    backend = [
        routes_file(schema),
        *[controller_file(t, snapshot) for t in schema.tables],
        *shared_files(constraints),
    ]
    return models, backend
