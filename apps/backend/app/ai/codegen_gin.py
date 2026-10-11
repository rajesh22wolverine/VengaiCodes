# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Deterministic (no-AI) Go backend: Gin over database/sql
#  + SQLite
#  ai/codegen_gin.py — The Gin backend codegen_deterministic dispatches
#  to. Per table: a model file (the row struct the API answers with, the
#  request it accepts, its checks and the SQL) and a handlers file (the
#  REST routes). Shared by every table: fields/ (request field types and
#  row value types), apierr/ (errors and what each database constraint
#  means), handlers/routes.go and main.go.
#
#  It is the Rust backends' design (codegen_rust.py) in Go, statement
#  for statement where the languages allow: the same SQL, the same
#  checks in the same order, the same sentences. The database is the
#  same too — the SQL migrations are migrations_sqlite's, applied by the
#  app's own runner (migrations/migrate.go) — so a project can move
#  between Actix/Axum and Gin and keep its app.db.
#
#  Follows the knowledge registry's Go and Gin rules: JSON bound with
#  c.ShouldBindJSON (400 when it isn't a JSON object), exported fields
#  with `json:"snake_case"` tags, every error checked and answered as
#  {"error": ...} (which the screens read), context.Context first.
#
#  database/sql rather than GORM, on purpose: the schema is owned by the
#  migrations, and every statement the app runs is written out here —
#  no ORM conventions (auto timestamps, zero-value skipping, soft
#  deletes) deciding what a request stores. The driver is
#  modernc.org/sqlite, which is pure Go: `go run .` needs no C compiler.
#  What the generated code relies on was read from the driver's source
#  at the pinned version: a DSN's `?_pragma=…` runs on every new
#  connection, Exec runs every statement of a multi-statement string,
#  and a TEXT column (dates and date-times here) is returned as text.
#
#  Go's build rules shape two things:
#    - File names. `x_test.go` is a test file and `x_linux.go` /
#      `x_amd64.go` build on that platform only, so a table called
#      "load test" or "order windows" would silently drop out of the
#      build. Every per-table file ends _model.go / _handlers.go.
#    - Names. Everything a table adds to a package is its class name
#      plus a fixed suffix (Book, BookInput, BookStore; bookLabel,
#      bookListSQL, …), so two tables collide only when one's name is
#      another's plus "Input"/"Store" — which name_problems and
#      codegen_deterministic refuse, like two columns that would be the
#      same exported field (a_1 and a1 are both A1).
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations

import re

from app.ai import db_schema, knowledge
from app.ai.codegen_shared import GeneratedFile
from app.ai.migrations_sqlite import NOW_SQL, q

# What go.mod pins. Gin 1.10 needs Go 1.20 and this driver release Go
# 1.21 — the Go version the installer workflows set up.
GO_VERSION = "1.21"
GIN_VERSION = "v1.10.1"
SQLITE_DRIVER_VERSION = "v1.34.5"

# Names a table's exported types may not take (none: the generated code
# refers to everything else through its package).
IMPORTED_NAMES: frozenset[str] = frozenset()
# What a table adds to package models besides its row struct.
SUFFIXES = ("Input", "Store")
# Fields every row struct has.
_FIXED_FIELDS = {"ID": "id", "CreatedAt": "created_at", "UpdatedAt": "updated_at"}

# Top-level standard library packages: a module can't safely be named one.
_GO_STD = frozenset(
    "archive bufio builtin bytes cmd cmp compress container context crypto database debug embed encoding "
    "errors expvar flag fmt go hash html image index internal io iter log main maps math mime net os path "
    "plugin reflect regexp runtime slices sort std strconv strings structs sync syscall testing text time "
    "unicode unique unsafe vendor weak".split()
)

# Go type of a column in the row struct (what database/sql scans) …
_ROW_TYPE = {
    "string": "string",
    "text": "string",
    "integer": "int64",
    "float": "float64",
    "decimal": "float64",
    "boolean": "bool",
    "date": "string",
    "datetime": "fields.Timestamp",
    "json": "fields.JSONText",
}
# … and in the request struct (what reads and checks the JSON).
_INPUT_TYPE = {
    "string": "fields.Text",
    "text": "fields.Text",
    "integer": "fields.Integer",
    "float": "fields.Float",
    "decimal": "fields.Decimal",
    "boolean": "fields.Boolean",
    "date": "fields.Date",
    "datetime": "fields.DateTime",
    "json": "fields.JSON",
}


# ───────────────────────────────────────────────
#  Go text helpers
# ───────────────────────────────────────────────
def go_str(text: str) -> str:
    """A Go string literal for user text. "TODO" is written with an escape
    (same string at runtime) so the generated-file check, which looks for
    leftover TODO markers, doesn't flag a table's name. Anything Go
    source can't hold raw (control characters, a byte order mark, half a
    surrogate pair) is escaped too."""
    out = []
    for ch in str(text):
        code = ord(ch)
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
        elif ch.isprintable():
            out.append(ch)
        elif 0xD800 <= code <= 0xDFFF:
            out.append("\\ufffd")
        elif code > 0xFFFF:
            out.append(f"\\U{code:08x}")
        else:
            out.append(f"\\u{code:04x}")
    return '"' + "".join(out).replace("TODO", "TOD\\u004f") + '"'


def go_sql(text: str) -> str:
    """SQL as a Go raw string (`…`), so quoted identifiers read as SQL."""
    if "`" in text or "TODO" in text or not all(ch.isprintable() for ch in text):
        return go_str(text)
    return f"`{text}`"


def doc(text: str) -> str:
    """User text on one comment line."""
    line = " ".join(str(text or "").split())
    return "".join(ch for ch in line if ch.isprintable()).replace("TODO", "to-do")


def field_name(slug: str) -> str:
    """A column as an exported struct field: is_available -> IsAvailable."""
    return knowledge.identifier_for(slug, "pascal")


def _lower_first(name: str) -> str:
    return name[:1].lower() + name[1:]


def module_path(project_name: str) -> str:
    """The Go module (and import prefix) for a project."""
    from app.core.naming import slugify_app_name

    name = re.sub(r"[^a-z0-9]", "", slugify_app_name(project_name))
    if not name or name[0].isdigit():
        name = f"app{name}"
    return f"{name}app" if name in _GO_STD else name


_TOKEN = re.compile(r"__([A-Z_]+?)__")


def _fill(template: str, **values: str) -> str:
    """Every __TOKEN__ replaced in one pass, so a value (a table's label,
    say) that happens to contain a token's text is left as written."""
    return _TOKEN.sub(lambda m: values[m.group(1)], template)


def _go(text: str) -> str:
    """Templates here are indented with four spaces; Go files use tabs."""
    out = []
    for line in text.split("\n"):
        body = line.lstrip(" ")
        depth, rest = divmod(len(line) - len(body), 4)
        out.append("\t" * depth + " " * rest + body)
    return "\n".join(out)


def _aligned(rows: list[tuple[str, ...]]) -> list[str]:
    """Struct fields the way gofmt lays them out: each column padded to
    its widest cell."""
    if not rows:
        return []
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]) - 1)]
    return [
        "    " + "".join(f"{cell:<{w}} " for cell, w in zip(r, widths)) + r[-1]
        for r in rows
    ]


def model_path(slug: str) -> str:
    return f"backend/models/{slug}_model.go"


def handlers_path(slug: str) -> str:
    return f"backend/handlers/{slug}_handlers.go"


def name_problems(schema: db_schema.ResolvedSchema) -> list[str]:
    problems = []
    for t in schema.tables:
        taken = dict(_FIXED_FIELDS)
        for c in t.columns:
            name = field_name(c.column)
            if name in _FIXED_FIELDS:
                problems.append(
                    f'The field "{c.name}" in "{t.name}" would be the Go struct field {name}, which '
                    f"every generated row already has (for {_FIXED_FIELDS[name]}) — rename it in Architecture."
                )
            elif name in taken:
                problems.append(
                    f'The fields "{taken[name]}" and "{c.name}" in "{t.name}" would both be the Go struct '
                    f"field {name} — rename one of them in Architecture."
                )
            else:
                taken[name] = c.name
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
#  models/<table>_model.go
# ───────────────────────────────────────────────
_STORE_GO = """// __NAME__Store reads and writes the rows of __LABEL__.
type __NAME__Store struct {
    DB *sql.DB
}

// List answers every row, oldest first.
func (s __NAME__Store) List(ctx context.Context) ([]__NAME__, error) {
    rows, err := s.DB.QueryContext(ctx, __LC__ListSQL)
    if err != nil {
        return nil, apierr.FromDB(err)
    }
    defer rows.Close()
    items := []__NAME__{}
    for rows.Next() {
        var item __NAME__
        if err := item.scan(rows); err != nil {
            return nil, apierr.FromDB(err)
        }
        items = append(items, item)
    }
    if err := rows.Err(); err != nil {
        return nil, apierr.FromDB(err)
    }
    return items, nil
}

// Find answers one row, or a 404.
func (s __NAME__Store) Find(ctx context.Context, id int64) (__NAME__, error) {
    var item __NAME__
    err := item.scan(s.DB.QueryRowContext(ctx, __LC__FindSQL, id))
    if errors.Is(err, sql.ErrNoRows) {
        return __NAME__{}, apierr.NotFound(__LC__Label, id)
    }
    if err != nil {
        return __NAME__{}, apierr.FromDB(err)
    }
    return item, nil
}

// Create adds a row from a request body, and answers it as stored.
func (s __NAME__Store) Create(ctx context.Context, body map[string]json.RawMessage) (__NAME__, error) {
    var in __NAME__Input
    if err := in.read(body, true); err != nil {
        return __NAME__{}, err
    }
__CHECK_REFERENCES__    columns, values := in.assignments()
    query := __INSERT_DEFAULTS__
    if len(columns) > 0 {
        query = __INSERT_OPEN__ + strings.Join(columns, ", ") + `) VALUES (` + fields.Placeholders(len(columns)) + `)`
    }
    done, err := s.DB.ExecContext(ctx, query, values...)
    if err != nil {
        return __NAME__{}, apierr.FromDB(err)
    }
    id, err := done.LastInsertId()
    if err != nil {
        return __NAME__{}, apierr.Internal(err)
    }
    return s.Find(ctx, id)
}

// Update changes only the fields the request sends, like the other generated backends.
func (s __NAME__Store) Update(ctx context.Context, id int64, body map[string]json.RawMessage) (__NAME__, error) {
    if _, err := s.Find(ctx, id); err != nil {
        return __NAME__{}, err
    }
    var in __NAME__Input
    if err := in.read(body, false); err != nil {
        return __NAME__{}, err
    }
__CHECK_REFERENCES__    columns, values := in.assignments()
    sets := make([]string, 0, len(columns)+1)
    for _, column := range columns {
        sets = append(sets, column+" = ?")
    }
    sets = append(sets, __UPDATED_AT__+fields.NowSQL)
    values = append(values, id)
    query := __UPDATE_OPEN__ + strings.Join(sets, ", ") + __UPDATE_WHERE__
    if _, err := s.DB.ExecContext(ctx, query, values...); err != nil {
        return __NAME__{}, apierr.FromDB(err)
    }
    return s.Find(ctx, id)
}

// Delete removes a row: a 404 when it isn't there, a 409 when other rows
// still need it.
func (s __NAME__Store) Delete(ctx context.Context, id int64) error {
    done, err := s.DB.ExecContext(ctx, __LC__DeleteSQL, id)
    if err != nil {
        return apierr.FromDelete(err, __LC__RestrictMessage)
    }
    affected, err := done.RowsAffected()
    if err != nil {
        return apierr.Internal(err)
    }
    if affected == 0 {
        return apierr.NotFound(__LC__Label, id)
    }
    return nil
}
"""

_CHECK_REFERENCES_CALL = """    if err := in.checkReferences(ctx, s.DB); err != nil {
        return __NAME__{}, err
    }
"""


def model_file(
    t: db_schema.ResolvedTable, snapshot: dict, heading: str, module: str
) -> GeneratedFile:
    tables = snapshot["tables"]
    table = tables[t.sql_name]
    name = t.class_name
    lc = _lower_first(name)
    columns = table["column_order"]
    quoted = ", ".join(q(c) for c in ["id", *columns, "created_at", "updated_at"])
    select = f"SELECT {quoted} FROM {q(t.sql_name)}"
    table_sql = q(t.sql_name)
    label = doc(table["label"])

    row_fields: list[tuple[str, ...]] = [("ID", "int64", '`json:"id"`')]
    input_fields: list[tuple[str, ...]] = []
    scans = ["&item.ID"]
    reads: list[str] = []
    checks: list[str] = []
    assigns: list[str] = []
    references: list[str] = []
    for c in columns:
        col = table["columns"][c]
        base = _base(col, tables)
        kind = base["type"]
        field = field_name(c)
        row_type = _ROW_TYPE[kind]
        row_fields.append(
            (field, f"*{row_type}" if col["nullable"] else row_type, f'`json:"{c}"`')
        )
        input_fields.append((field, _INPUT_TYPE[kind]))
        scans.append(f"&item.{field}")
        reads.append(f"    fields.Read(body, {go_str(c)}, &in.{field}, &problems)")
        if not col["nullable"] and col["default"] is None:
            checks.append(
                f"    fields.Required(&in.{field}, {go_str(c)}, creating, &problems)"
            )
        elif not col["nullable"]:
            checks.append(f"    fields.NotNull(&in.{field}, {go_str(c)}, &problems)")
        if kind == "string" and base.get("length"):
            checks.append(
                f"    fields.MaxChars(&in.{field}, {base['length']}, {go_str(c)}, &problems)"
            )
        assigns.append(
            f"    fields.Assign(&in.{field}, {go_sql(q(c))}, &columns, &values)"
        )
        if col["fk"]:
            fk = col["fk"]
            target = tables[fk["table"]]
            query = f"SELECT 1 FROM {q(fk['table'])} WHERE {q(fk['column'])} = ?"
            message = f"{c}: no row in {target['label']} has {fk['column']}"
            references += [
                f"    if err := fields.Exists(ctx, db, {go_sql(query)}, &in.{field}, {go_str(message)}); err != nil {{",
                "        return err",
                "    }",
            ]
    row_fields += [
        ("CreatedAt", "fields.Timestamp", '`json:"created_at"`'),
        ("UpdatedAt", "fields.Timestamp", '`json:"updated_at"`'),
    ]
    scans += ["&item.CreatedAt", "&item.UpdatedAt"]

    input_struct = (
        [f"type {name}Input struct {{", *_aligned(input_fields), "}"]
        if input_fields
        else [f"type {name}Input struct{{}}"]
    )
    reference_fn = (
        [
            "",
            "// checkReferences makes sure every foreign key the request sets points at a",
            "// row that exists: a 422 naming the field, instead of the database's bare",
            "// refusal.",
            f"func (in *{name}Input) checkReferences(ctx context.Context, db *sql.DB) error {{",
            *references,
            "    return nil",
            "}",
        ]
        if references
        else []
    )
    store = _fill(
        _STORE_GO,
        CHECK_REFERENCES=_fill(_CHECK_REFERENCES_CALL, NAME=name) if references else "",
        INSERT_DEFAULTS=go_sql(f"INSERT INTO {table_sql} DEFAULT VALUES"),
        INSERT_OPEN=go_sql(f"INSERT INTO {table_sql} ("),
        UPDATED_AT=go_sql(f"{q('updated_at')} = "),
        UPDATE_OPEN=go_sql(f"UPDATE {table_sql} SET "),
        UPDATE_WHERE=go_sql(f" WHERE {q('id')} = ?"),
        LABEL=label,
        NAME=name,
        LC=lc,
    )
    lines = [
        f"// {doc(heading)}",
        "//",
        "// Deterministically generated by VengaiCode from the Architecture tab (no AI",
        "// call). The table is created and changed by the migrations in migrations/,",
        "// which the app applies as it starts (migrations/migrate.go).",
        "",
        "package models",
        "",
        "import (",
        '    "context"',
        '    "database/sql"',
        '    "encoding/json"',
        '    "errors"',
        '    "strings"',
        "",
        f'    "{module}/apierr"',
        f'    "{module}/fields"',
        ")",
        "",
        f"const {lc}Label = {go_str(table['label'])}",
        f"const {lc}RestrictMessage = {go_str(_restrict_message(t.sql_name, snapshot))}",
        f"const {lc}ListSQL = {go_sql(select + ' ORDER BY ' + q('id'))}",
        f"const {lc}FindSQL = {go_sql(select + ' WHERE ' + q('id') + ' = ?')}",
        f"const {lc}DeleteSQL = {go_sql(f'DELETE FROM {table_sql} WHERE ' + q('id') + ' = ?')}",
        "",
        f"// {name} is one row of {label} as the API answers it, keyed by column name.",
        f"type {name} struct {{",
        *_aligned(row_fields),
        "}",
        "",
        f"func (item *{name}) scan(row rowScanner) error {{",
        "    return row.Scan(",
        *[f"        {dest}," for dest in scans],
        "    )",
        "}",
        "",
        f"// {name}Input is the body of POST and PUT /api/{t.sql_name}. Each field records",
        "// whether the request sent it: one left out keeps the database default (on",
        "// PUT, the stored value); one sent as null is refused by a required field.",
        *input_struct,
        "",
        "// read fills the input from a request body and checks it, reporting every",
        "// problem at once as one 422.",
        f"func (in *{name}Input) read(body map[string]json.RawMessage, creating bool) error {{",
        "    var problems []string",
        *reads,
        *checks,
        "    return fields.Finish(problems)",
        "}",
        *reference_fn,
        "",
        "// assignments lists the columns the request sets, with their values in the",
        "// same order.",
        f"func (in *{name}Input) assignments() ([]string, []any) {{",
        "    var columns []string",
        "    var values []any",
        *assigns,
        "    return columns, values",
        "}",
        "",
        store.rstrip("\n"),
        "",
        f"// VENGAI:CUSTOM:{t.slug}_model:start",
        f"// Add functions for {label} here. A new column belongs in the Architecture",
        "// tab instead, so a migration adds it to the database.",
        "// This block is preserved across future regenerations.",
        f"// VENGAI:CUSTOM:{t.slug}_model:end",
        "",
    ]
    return GeneratedFile(
        path=model_path(t.slug),
        language="go",
        content=_go("\n".join(lines)),
        description=f"Deterministic model, validation and SQL for {t.name}",
    )


_MODELS_GO = """// Package models holds every table's model: the row the API answers with, the
// request it accepts, its checks and its SQL. Written by VengaiCode.
package models

// rowScanner is a *sql.Row or a *sql.Rows.
type rowScanner interface {
    Scan(dest ...any) error
}
"""


def models_file() -> GeneratedFile:
    return GeneratedFile(
        path="backend/models/models.go",
        language="go",
        content=_go(_MODELS_GO),
        description="What every table's model shares",
    )


# ───────────────────────────────────────────────
#  handlers/ — routes.go and one file per table
# ───────────────────────────────────────────────
_HANDLERS_GO = """// REST routes for __TITLE__ — the paths the generated screens call.
// Deterministically generated by VengaiCode (no AI call); the work itself is
// in models/__SLUG___model.go.

package handlers

import (
    "database/sql"
    "net/http"

    "github.com/gin-gonic/gin"

    "__MODULE__/models"
)

func register__NAME__(api *gin.RouterGroup, db *sql.DB) {
    store := models.__NAME__Store{DB: db}

    api.GET(__BASE__, func(c *gin.Context) {
        items, err := store.List(c.Request.Context())
        if err != nil {
            fail(c, err)
            return
        }
        c.JSON(http.StatusOK, items)
    })

    api.POST(__BASE__, func(c *gin.Context) {
        body, err := readBody(c)
        if err != nil {
            fail(c, err)
            return
        }
        item, err := store.Create(c.Request.Context(), body)
        if err != nil {
            fail(c, err)
            return
        }
        c.JSON(http.StatusCreated, item)
    })

    api.GET(__ONE__, func(c *gin.Context) {
        id, err := pathID(c)
        if err != nil {
            fail(c, err)
            return
        }
        item, err := store.Find(c.Request.Context(), id)
        if err != nil {
            fail(c, err)
            return
        }
        c.JSON(http.StatusOK, item)
    })

    api.PUT(__ONE__, func(c *gin.Context) {
        id, err := pathID(c)
        if err != nil {
            fail(c, err)
            return
        }
        body, err := readBody(c)
        if err != nil {
            fail(c, err)
            return
        }
        item, err := store.Update(c.Request.Context(), id, body)
        if err != nil {
            fail(c, err)
            return
        }
        c.JSON(http.StatusOK, item)
    })

    api.DELETE(__ONE__, func(c *gin.Context) {
        id, err := pathID(c)
        if err != nil {
            fail(c, err)
            return
        }
        if err := store.Delete(c.Request.Context(), id); err != nil {
            fail(c, err)
            return
        }
        c.Status(http.StatusNoContent)
    })

    // VENGAI:CUSTOM:__SLUG___routes:start
    // Add custom, non-CRUD routes here, e.g.
    // api.GET(__EXAMPLE__, export__NAME__)
    // This block is preserved across regenerations.
    // VENGAI:CUSTOM:__SLUG___routes:end
}

// VENGAI:CUSTOM:__SLUG___handlers:start
// Add custom handlers here — this block is preserved across regenerations.
// VENGAI:CUSTOM:__SLUG___handlers:end
"""


def handlers_file(t: db_schema.ResolvedTable, module: str) -> GeneratedFile:
    base = f"/{t.sql_name}"
    content = _fill(
        _HANDLERS_GO,
        TITLE=doc(t.name),
        MODULE=module,
        BASE=go_str(base),
        ONE=go_str(base + "/:id"),
        EXAMPLE=go_str(base + "/export"),
        SLUG=t.slug,
        NAME=t.class_name,
    )
    return GeneratedFile(
        path=handlers_path(t.slug),
        language="go",
        content=_go(content),
        description=f"REST routes for {t.name}",
    )


_ROUTES_GO = """// Package handlers is the REST API: /api/<table> and /api/<table>/:id for every
// table. Written by VengaiCode.
package handlers

import (
    "database/sql"
    "encoding/json"
    "net/http"
    "strconv"

    "github.com/gin-gonic/gin"

    "__MODULE__/apierr"
)

// Register adds every table's routes to the router.
func Register(router *gin.Engine, db *sql.DB) {
    api := router.Group("/api")
__REGISTER__
}

// fail answers an error as {"error": "..."} with its HTTP status.
func fail(c *gin.Context, err error) {
    problem := apierr.From(err)
    c.JSON(problem.Status, gin.H{"error": problem.Detail})
}

// readBody reads a request's JSON object, one raw value per field.
func readBody(c *gin.Context) (map[string]json.RawMessage, error) {
    var body map[string]json.RawMessage
    if err := c.ShouldBindJSON(&body); err != nil || body == nil {
        return nil, apierr.New(http.StatusBadRequest, "Send the record as a JSON object.")
    }
    return body, nil
}

// pathID reads the :id in a route's path.
func pathID(c *gin.Context) (int64, error) {
    id, err := strconv.ParseInt(c.Param("id"), 10, 64)
    if err != nil {
        return 0, apierr.New(http.StatusBadRequest, "id: not a valid id")
    }
    return id, nil
}
"""


def routes_file(schema: db_schema.ResolvedSchema, module: str) -> GeneratedFile:
    register = "\n".join(f"    register{t.class_name}(api, db)" for t in schema.tables)
    return GeneratedFile(
        path="backend/handlers/routes.go",
        language="go",
        content=_go(_fill(_ROUTES_GO, MODULE=module, REGISTER=register)),
        description="Registers every table's routes; answers errors as {error}",
    )


# ───────────────────────────────────────────────
#  apierr/apierr.go — errors, and what each database constraint means
# ───────────────────────────────────────────────
_APIERR_GO = """// Package apierr is the API's errors: every failure answers {"error": "..."}
// with its HTTP status, which is what the generated screens show. Written by
// VengaiCode.
package apierr

import (
    "errors"
    "fmt"
    "log"
    "net/http"
    "strings"
    "unicode"
)

const internalDetail = "Something went wrong on the server."

// Error is a failure with the HTTP status to answer it with.
type Error struct {
    Status int
    Detail string
}

func (e *Error) Error() string {
    return e.Detail
}

// New is an error answered with this status and text.
func New(status int, detail string) error {
    return &Error{Status: status, Detail: detail}
}

// NotFound is the 404 for a row that isn't there.
func NotFound(label string, id int64) error {
    return New(http.StatusNotFound, fmt.Sprintf("%s %d not found.", label, id))
}

// Internal is a failure that isn't the request's fault: logged, answered as a 500.
func Internal(err error) error {
    log.Printf("internal error: %v", err)
    return New(http.StatusInternalServerError, internalDetail)
}

// From is the status and text to answer any error with: an *Error as it is,
// anything else as a 500.
func From(err error) *Error {
    var known *Error
    if errors.As(err, &known) {
        return known
    }
    log.Printf("internal error: %v", err)
    return &Error{Status: http.StatusInternalServerError, Detail: internalDetail}
}

// constraint is what one database constraint means, so a violation comes back
// as a sentence instead of a raw database error.
type constraint struct {
    key     string // its name in the database's message
    status  int
    message string
}

// Longest names first.
var constraints = []constraint{__CONSTRAINTS__}

// FromDB explains a failed read or write.
func FromDB(err error) error {
    var known *Error
    if errors.As(err, &known) {
        return err
    }
    text := err.Error()
    if !strings.Contains(text, "constraint failed") {
        return Internal(err)
    }
    return explain(text)
}

// FromDelete explains a failed delete: a foreign key refusing it means rows
// still refer to this one.
func FromDelete(err error, restrictMessage string) error {
    if strings.Contains(err.Error(), "FOREIGN KEY constraint failed") {
        return New(http.StatusConflict, restrictMessage)
    }
    return FromDB(err)
}

func explain(text string) error {
    if strings.Contains(text, "UNIQUE constraint failed") || strings.Contains(text, "CHECK constraint failed") {
        // SQLite names a failed UNIQUE by its columns, a failed CHECK by its name.
        for _, c := range constraints {
            if names(text, c.key) {
                return New(c.status, c.message)
            }
        }
    }
    if _, column, found := strings.Cut(text, "NOT NULL constraint failed: "); found {
        // The driver ends its message with the result code, e.g. " (1299)".
        column, _, _ = strings.Cut(column, " (")
        return New(http.StatusUnprocessableEntity, column+": may not be null")
    }
    if strings.Contains(text, "FOREIGN KEY constraint failed") {
        return New(http.StatusUnprocessableEntity, "A record this one refers to doesn't exist.")
    }
    return New(http.StatusConflict, "The database refused this change: "+text)
}

// names reports whether the message names key whole, not as part of a longer
// name.
func names(text, key string) bool {
    if key == "" {
        return false
    }
    from := 0
    for {
        at := strings.Index(text[from:], key)
        if at < 0 {
            return false
        }
        start := from + at
        end := start + len(key)
        before := start > 0 && namePart(rune(text[start-1]))
        after := end < len(text) && namePart(rune(text[end]))
        if !before && !after {
            return true
        }
        from = start + 1
    }
}

func namePart(r rune) bool {
    return unicode.IsLetter(r) || unicode.IsDigit(r) || r == '_' || r == '.'
}
"""


def apierr_file(constraints: list[tuple[str, int, str]]) -> GeneratedFile:
    entries = "".join(
        f"\n    {{{go_str(k)}, {s}, {go_str(m)}}},"
        for k, s, m in sorted(constraints, key=lambda e: -len(e[0]))
    )
    return GeneratedFile(
        path="backend/apierr/apierr.go",
        language="go",
        content=_go(_fill(_APIERR_GO, CONSTRAINTS=f"{entries}\n" if entries else "")),
        description="Turns every error into an {error} response with its status",
    )


# ───────────────────────────────────────────────
#  fields/fields.go — request field types and row value types
# ───────────────────────────────────────────────
_FIELDS_GO = """// Package fields holds what every table's model shares: the request field
// types and their checks, and the value types rows are answered with. Written
// by VengaiCode.
//
// Values are stored the way SQLite compares them: date-times as UTC text with
// six fractional digits ("2024-01-31 09:30:00.000000"), dates as "2024-01-31",
// booleans as 0/1 and JSON as its text. A request may leave a field out (the
// database default applies, or an update keeps the value) or send it as null;
// every request field records which.
package fields

import (
    "bytes"
    "context"
    "database/sql"
    "encoding/json"
    "errors"
    "fmt"
    "net/http"
    "strconv"
    "strings"
    "time"
    "unicode/utf8"

    "__MODULE__/apierr"
)

// A decimal keeps DecimalDigits digits, DecimalPlaces of them after the point.
const (
    DecimalDigits = __DIGITS__
    DecimalPlaces = __PLACES__
)

// NowSQL is SQL for "now" in the stored date-time form (%f is seconds with
// three decimals).
const NowSQL = "__NOW_SQL__"

// storedLayout is how a date-time is stored.
const storedLayout = "2006-01-02 15:04:05.000000"

// Presence records whether a request sent a field, and whether as null.
type Presence struct {
    Sent bool // the request has this field
    Null bool // and its value is null
}

func (p Presence) presence() Presence {
    return p
}

// start marks the field as sent, and reports whether it was sent as null.
func (p *Presence) start(data []byte) bool {
    p.Sent = true
    p.Null = bytes.Equal(bytes.TrimSpace(data), []byte("null"))
    return p.Null
}

// Field is one request field, whatever its type.
type Field interface {
    // SQLValue is the value to store: nil for null.
    SQLValue() any
    presence() Presence
    read(data []byte) error
}

func stored(p Presence, value any) any {
    if p.Null {
        return nil
    }
    return value
}

// Text is a string or text field.
type Text struct {
    Presence
    Value string
}

func (f *Text) SQLValue() any {
    return stored(f.Presence, f.Value)
}

func (f *Text) read(data []byte) error {
    if f.start(data) {
        return nil
    }
    if err := json.Unmarshal(data, &f.Value); err != nil {
        return errors.New("expected text")
    }
    return nil
}

// Integer is a whole-number field.
type Integer struct {
    Presence
    Value int64
}

func (f *Integer) SQLValue() any {
    return stored(f.Presence, f.Value)
}

func (f *Integer) read(data []byte) error {
    if f.start(data) {
        return nil
    }
    if err := json.Unmarshal(data, &f.Value); err != nil {
        return errors.New("expected a whole number")
    }
    return nil
}

// Float is a number field.
type Float struct {
    Presence
    Value float64
}

func (f *Float) SQLValue() any {
    return stored(f.Presence, f.Value)
}

func (f *Float) read(data []byte) error {
    if f.start(data) {
        return nil
    }
    if err := json.Unmarshal(data, &f.Value); err != nil {
        return errors.New("expected a number")
    }
    return nil
}

// Decimal is a fixed-point number field: a JSON number, or text like "12.50".
type Decimal struct {
    Presence
    Value float64
}

func (f *Decimal) SQLValue() any {
    return stored(f.Presence, f.Value)
}

func (f *Decimal) read(data []byte) error {
    if f.start(data) {
        return nil
    }
    text := strings.TrimSpace(string(data))
    if strings.HasPrefix(text, `"`) {
        if err := json.Unmarshal(data, &text); err != nil {
            return errNotDecimal
        }
        text = strings.TrimSpace(text)
    } else {
        // A JSON number may be written 1.25e1; its digits are what get checked.
        number, err := strconv.ParseFloat(text, 64)
        if err != nil {
            return errNotDecimal
        }
        text = strconv.FormatFloat(number, 'f', -1, 64)
    }
    value, err := parseDecimal(text)
    if err != nil {
        return err
    }
    f.Value = value
    return nil
}

var errNotDecimal = errors.New("expected a number like 12.50")

func parseDecimal(text string) (float64, error) {
    unsigned := strings.TrimPrefix(text, "-")
    whole, fraction, _ := strings.Cut(unsigned, ".")
    if whole == "" || !allDigits(whole) || !allDigits(fraction) || strings.HasSuffix(unsigned, ".") {
        return 0, errNotDecimal
    }
    if len(strings.TrimRight(fraction, "0")) > DecimalPlaces {
        return 0, fmt.Errorf("only %d decimal places are stored", DecimalPlaces)
    }
    if len(strings.TrimLeft(whole, "0")) > DecimalDigits-DecimalPlaces {
        return 0, errors.New("number is too large")
    }
    value, err := strconv.ParseFloat(text, 64)
    if err != nil {
        return 0, errNotDecimal
    }
    return value, nil
}

func allDigits(text string) bool {
    for _, r := range text {
        if r < '0' || r > '9' {
            return false
        }
    }
    return true
}

// Boolean is a true/false field.
type Boolean struct {
    Presence
    Value bool
}

func (f *Boolean) SQLValue() any {
    return stored(f.Presence, f.Value)
}

func (f *Boolean) read(data []byte) error {
    if f.start(data) {
        return nil
    }
    if err := json.Unmarshal(data, &f.Value); err != nil {
        return errors.New("expected true or false")
    }
    return nil
}

// Date is a date field ("2024-01-31"), kept in its stored form.
type Date struct {
    Presence
    Value string
}

func (f *Date) SQLValue() any {
    return stored(f.Presence, f.Value)
}

func (f *Date) read(data []byte) error {
    if f.start(data) {
        return nil
    }
    problem := errors.New("expected a date like 2024-01-31")
    var text string
    if err := json.Unmarshal(data, &text); err != nil {
        return problem
    }
    day, err := time.Parse("2006-01-02", strings.TrimSpace(text))
    if err != nil {
        return problem
    }
    f.Value = day.Format("2006-01-02")
    return nil
}

// DateTime is a date-time field: RFC 3339 ("2024-01-31T09:30:00Z", any
// offset), or without an offset, read as UTC. Kept as stored UTC text.
type DateTime struct {
    Presence
    Value string
}

func (f *DateTime) SQLValue() any {
    return stored(f.Presence, f.Value)
}

func (f *DateTime) read(data []byte) error {
    if f.start(data) {
        return nil
    }
    problem := errors.New("expected a date and time like 2024-01-31T09:30:00Z")
    var text string
    if err := json.Unmarshal(data, &text); err != nil {
        return problem
    }
    text = strings.TrimSpace(text)
    when, err := time.Parse(time.RFC3339, text)
    if err != nil {
        // No offset: UTC. Parsing accepts fractional seconds either way.
        naive := strings.Replace(text, "T", " ", 1)
        if when, err = time.Parse("2006-01-02 15:04:05", naive); err != nil {
            when, err = time.Parse("2006-01-02 15:04", naive)
        }
    }
    if err != nil {
        return problem
    }
    f.Value = when.UTC().Format(storedLayout)
    return nil
}

// JSON is a JSON field: any JSON value, kept as its text.
type JSON struct {
    Presence
    Value string
}

func (f *JSON) SQLValue() any {
    return stored(f.Presence, f.Value)
}

func (f *JSON) read(data []byte) error {
    if f.start(data) {
        return nil
    }
    var compact bytes.Buffer
    if err := json.Compact(&compact, data); err != nil {
        return errors.New("expected JSON")
    }
    f.Value = compact.String()
    return nil
}

// Read fills one request field from the body. A value of the wrong kind is
// added to problems, named by its field.
func Read(body map[string]json.RawMessage, name string, into Field, problems *[]string) {
    data, sent := body[name]
    if !sent {
        return
    }
    if err := into.read(data); err != nil {
        *problems = append(*problems, name+": "+err.Error())
    }
}

// Required checks a NOT NULL field with no default: needed on create, never
// null.
func Required(f Field, name string, creating bool, problems *[]string) {
    p := f.presence()
    switch {
    case p.Null:
        *problems = append(*problems, name+": may not be null")
    case creating && !p.Sent:
        *problems = append(*problems, name+": is required")
    }
}

// NotNull checks a NOT NULL field with a default: may be left out, never null.
func NotNull(f Field, name string, problems *[]string) {
    if f.presence().Null {
        *problems = append(*problems, name+": may not be null")
    }
}

// MaxChars checks text is no longer than its column allows.
func MaxChars(f *Text, limit int, name string, problems *[]string) {
    if f.Sent && !f.Null && utf8.RuneCountInString(f.Value) > limit {
        *problems = append(*problems, fmt.Sprintf("%s: at most %d characters", name, limit))
    }
}

// Finish is every problem found, as one 422 — or nil when there are none.
func Finish(problems []string) error {
    if len(problems) == 0 {
        return nil
    }
    return apierr.New(http.StatusUnprocessableEntity, strings.Join(problems, "\\n"))
}

// Exists checks that a foreign key the request sets points at a row that
// exists. query selects that row by the field's value; problem starts the 422.
func Exists(ctx context.Context, db *sql.DB, query string, f Field, problem string) error {
    p := f.presence()
    if !p.Sent || p.Null {
        return nil
    }
    var found int
    err := db.QueryRowContext(ctx, query, f.SQLValue()).Scan(&found)
    if errors.Is(err, sql.ErrNoRows) {
        return apierr.New(http.StatusUnprocessableEntity, fmt.Sprintf("%s %v.", problem, f.SQLValue()))
    }
    if err != nil {
        return apierr.FromDB(err)
    }
    return nil
}

// Assign adds a field the request sent to the columns and values of an INSERT
// or UPDATE.
func Assign(f Field, column string, columns *[]string, values *[]any) {
    if f.presence().Sent {
        *columns = append(*columns, column)
        *values = append(*values, f.SQLValue())
    }
}

// Placeholders is "?, ?, ?" for n values.
func Placeholders(n int) string {
    return strings.TrimSuffix(strings.Repeat("?, ", n), ", ")
}

// scanText reads a stored text value.
func scanText(src any) (string, error) {
    switch value := src.(type) {
    case string:
        return value, nil
    case []byte:
        return string(value), nil
    case time.Time:
        return value.UTC().Format(storedLayout), nil
    default:
        return "", fmt.Errorf("can't read %T as text", src)
    }
}

// Timestamp is a stored date-time, answered as RFC 3339 UTC
// ("2024-01-31T09:30:00Z").
type Timestamp string

// Scan reads the stored text.
func (t *Timestamp) Scan(src any) error {
    text, err := scanText(src)
    if err != nil {
        return err
    }
    *t = Timestamp(text)
    return nil
}

// MarshalJSON answers the date-time as RFC 3339.
func (t Timestamp) MarshalJSON() ([]byte, error) {
    when, err := time.Parse("2006-01-02 15:04:05", string(t))
    if err != nil {
        // Written some other way (by hand, say): answered as stored.
        return json.Marshal(string(t))
    }
    return json.Marshal(when.UTC().Format(time.RFC3339Nano))
}

// JSONText is a stored JSON value, answered as JSON rather than as its text.
type JSONText string

// Scan reads the stored text.
func (j *JSONText) Scan(src any) error {
    text, err := scanText(src)
    if err != nil {
        return err
    }
    *j = JSONText(text)
    return nil
}

// MarshalJSON answers the stored JSON itself.
func (j JSONText) MarshalJSON() ([]byte, error) {
    if json.Valid([]byte(j)) {
        return []byte(j), nil
    }
    return json.Marshal(string(j))
}
"""


def fields_file(module: str) -> GeneratedFile:
    content = _fill(
        _FIELDS_GO,
        MODULE=module,
        DIGITS=str(db_schema.DECIMAL_PRECISION),
        PLACES=str(db_schema.DECIMAL_SCALE),
        NOW_SQL=NOW_SQL,
    )
    return GeneratedFile(
        path="backend/fields/fields.go",
        language="go",
        content=_go(content),
        description="Request field types and row value types shared by every model",
    )


# ───────────────────────────────────────────────
#  main.go and go.mod (the Gin adapter's migrations mode)
# ───────────────────────────────────────────────
_MAIN_GO = """// __TITLE__ API, written by VengaiCode.
//
// `go run .` applies any pending database migrations, then serves the API on
// 127.0.0.1:8080 (set PORT to change it). `go run . revert` undoes the newest
// migration. The database is SQLite: app.db beside where it runs, or the file
// DATABASE_PATH names.
package main

import (
    "context"
    "database/sql"
    "fmt"
    "log"
    "net/http"
    "os"

    "github.com/gin-gonic/gin"
    _ "modernc.org/sqlite"

    "__MODULE__/handlers"
    "__MODULE__/migrations"
)

const rootMessage = __MESSAGE__

// openDatabase opens the SQLite file, creating it if it isn't there.
func openDatabase() (*sql.DB, error) {
    path := os.Getenv("DATABASE_PATH")
    if path == "" {
        path = "app.db"
    }
    // SQLite leaves foreign keys off unless every connection switches them on;
    // busy_timeout makes a writer wait for another one instead of failing.
    db, err := sql.Open("sqlite", path+"?_pragma=busy_timeout(5000)&_pragma=foreign_keys(1)")
    if err != nil {
        return nil, err
    }
    if err := db.Ping(); err != nil {
        db.Close()
        return nil, err
    }
    return db, nil
}

// allowAnyOrigin lets the screens call the API from another origin (a packaged
// app's window isn't the API's origin).
func allowAnyOrigin(c *gin.Context) {
    c.Header("Access-Control-Allow-Origin", "*")
    c.Header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
    c.Header("Access-Control-Allow-Headers", "Content-Type")
    if c.Request.Method == http.MethodOptions {
        c.AbortWithStatus(http.StatusNoContent)
        return
    }
    c.Next()
}

func run() error {
    db, err := openDatabase()
    if err != nil {
        return fmt.Errorf("can't open the database: %w", err)
    }
    defer db.Close()

    ctx := context.Background()
    if len(os.Args) > 1 && os.Args[1] == "revert" {
        if err := migrations.Revert(ctx, db); err != nil {
            return fmt.Errorf("revert failed: %w", err)
        }
        return nil
    }
    if err := migrations.Run(ctx, db); err != nil {
        return fmt.Errorf("a migration failed: %w", err)
    }

    router := gin.Default()
    router.Use(allowAnyOrigin)
    router.GET("/", func(c *gin.Context) {
        c.JSON(http.StatusOK, gin.H{"message": rootMessage})
    })
    handlers.Register(router, db)

    port := os.Getenv("PORT")
    if port == "" {
        port = "8080"
    }
    log.Printf("API listening on http://127.0.0.1:%s", port)
    return router.Run("127.0.0.1:" + port)
}

func main() {
    if err := run(); err != nil {
        log.Fatal(err)
    }
}
"""


def main_go(project_name: str) -> str:
    return _go(
        _fill(
            _MAIN_GO,
            TITLE=doc(project_name),
            MODULE=module_path(project_name),
            MESSAGE=go_str(f"{project_name} API is running"),
        )
    )


# ───────────────────────────────────────────────
#  migrations/migrate.go — the app's own migration runner. The same
#  steps, the same `_migrations` table and the same files as the Rust
#  backends' src/migrate.rs (migrations_sqlite.runner_rs), which is what
#  lets a database move between them. Go finds the files itself
#  (go:embed), so this file is the same for every project and a
#  migration added by hand is picked up too.
# ───────────────────────────────────────────────
_MIGRATE_GO = """// Package migrations applies this app's database migrations, the .sql files
// beside this one. Written by VengaiCode. Every migration is compiled into the
// binary, so a built app needs no files beside it.
//
// SQLite changes a column by rebuilding its table, and with foreign keys ON,
// dropping a parent table deletes its children. PRAGMA foreign_keys can only
// change outside a transaction, so each migration runs on one connection with
// foreign keys off around its own transaction.
package migrations

import (
    "context"
    "database/sql"
    "embed"
    "fmt"
    "log"
    "sort"
    "strconv"
    "strings"
)

//go:embed *.sql
var files embed.FS

// migration is one NNNN_name.sql file, with a `-- migrate:up` and a
// `-- migrate:down` section.
type migration struct {
    version int64
    name    string
    text    string
}

// load reads every migration, oldest first.
func load() ([]migration, error) {
    entries, err := files.ReadDir(".")
    if err != nil {
        return nil, err
    }
    var all []migration
    for _, entry := range entries {
        file := entry.Name()
        number, name, _ := strings.Cut(strings.TrimSuffix(file, ".sql"), "_")
        version, err := strconv.ParseInt(number, 10, 64)
        if err != nil {
            return nil, fmt.Errorf("migration %s: its name has to start with its number", file)
        }
        text, err := files.ReadFile(file)
        if err != nil {
            return nil, err
        }
        all = append(all, migration{version: version, name: name, text: string(text)})
    }
    sort.Slice(all, func(i, j int) bool { return all[i].version < all[j].version })
    return all, nil
}

// section is the SQL under `-- migrate:<name>`, up to the next section.
func section(text, name string) string {
    marker := "-- migrate:" + name
    start := strings.Index(text, marker)
    if start < 0 {
        return ""
    }
    rest := text[start+len(marker):]
    if end := strings.Index(rest, "-- migrate:"); end >= 0 {
        return rest[:end]
    }
    return rest
}

// applied lists the versions already applied, oldest first.
func applied(ctx context.Context, db *sql.DB) ([]int64, error) {
    _, err := db.ExecContext(ctx, "CREATE TABLE IF NOT EXISTS _migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)")
    if err != nil {
        return nil, err
    }
    rows, err := db.QueryContext(ctx, "SELECT version FROM _migrations ORDER BY version")
    if err != nil {
        return nil, err
    }
    defer rows.Close()
    var versions []int64
    for rows.Next() {
        var version int64
        if err := rows.Scan(&version); err != nil {
            return nil, err
        }
        versions = append(versions, version)
    }
    return versions, rows.Err()
}

// apply runs one migration's SQL and records it: on one connection, with
// foreign keys off around the transaction.
func apply(ctx context.Context, db *sql.DB, m migration, body, record string) error {
    conn, err := db.Conn(ctx)
    if err != nil {
        return err
    }
    defer conn.Close()
    if _, err := conn.ExecContext(ctx, "PRAGMA foreign_keys = OFF"); err != nil {
        return err
    }
    err = inTransaction(ctx, conn, m, body, record)
    if err == nil {
        warnAboutOrphans(ctx, conn, m)
    }
    // Back on before the connection returns to the pool, whatever happened.
    if _, onErr := conn.ExecContext(ctx, "PRAGMA foreign_keys = ON"); onErr != nil && err == nil {
        err = onErr
    }
    return err
}

func inTransaction(ctx context.Context, conn *sql.Conn, m migration, body, record string) error {
    tx, err := conn.BeginTx(ctx, nil)
    if err != nil {
        return err
    }
    if _, err := tx.ExecContext(ctx, body); err != nil {
        _ = tx.Rollback()
        return err
    }
    if _, err := tx.ExecContext(ctx, record, m.version, m.name); err != nil {
        _ = tx.Rollback()
        return err
    }
    return tx.Commit()
}

// warnAboutOrphans reports any row that now points at nothing: foreign keys
// were off while the tables were rebuilt (Postgres would have refused such a
// migration).
func warnAboutOrphans(ctx context.Context, conn *sql.Conn, m migration) {
    rows, err := conn.QueryContext(ctx, "PRAGMA foreign_key_check")
    if err != nil {
        return
    }
    defer rows.Close()
    broken := 0
    for rows.Next() {
        broken++
    }
    if broken > 0 {
        log.Printf("migration %04d: %d row(s) point at a row that doesn't exist", m.version, broken)
    }
}

// Run applies every pending migration, oldest first.
func Run(ctx context.Context, db *sql.DB) error {
    all, err := load()
    if err != nil {
        return err
    }
    done, err := applied(ctx, db)
    if err != nil {
        return err
    }
    ran := make(map[int64]bool, len(done))
    for _, version := range done {
        ran[version] = true
    }
    for _, m := range all {
        if ran[m.version] {
            continue
        }
        if err := apply(ctx, db, m, section(m.text, "up"), "INSERT INTO _migrations (version, name) VALUES (?, ?)"); err != nil {
            return fmt.Errorf("migration %04d %s: %w", m.version, m.name, err)
        }
        log.Printf("applied migration %04d %s", m.version, m.name)
    }
    return nil
}

// Revert undoes the newest applied migration (`go run . revert`).
func Revert(ctx context.Context, db *sql.DB) error {
    all, err := load()
    if err != nil {
        return err
    }
    done, err := applied(ctx, db)
    if err != nil {
        return err
    }
    if len(done) == 0 {
        log.Print("no migration to revert")
        return nil
    }
    newest := done[len(done)-1]
    for _, m := range all {
        if m.version != newest {
            continue
        }
        if err := apply(ctx, db, m, section(m.text, "down"), "DELETE FROM _migrations WHERE version = ? AND name = ?"); err != nil {
            return fmt.Errorf("reverting migration %04d %s: %w", m.version, m.name, err)
        }
        log.Printf("reverted migration %04d %s", m.version, m.name)
        return nil
    }
    return fmt.Errorf("applied migration %04d is missing from migrations/", newest)
}
"""


def migrate_go() -> str:
    return _go(_MIGRATE_GO)


def go_mod(project_name: str) -> str:
    """Only what the code imports; `go mod tidy` adds the rest and go.sum."""
    return (
        f"module {module_path(project_name)}\n\n"
        f"go {GO_VERSION}\n\n"
        "require (\n"
        f"\tgithub.com/gin-gonic/gin {GIN_VERSION}\n"
        f"\tmodernc.org/sqlite {SQLITE_DRIVER_VERSION}\n"
        ")\n"
    )


def backend_files(
    schema: db_schema.ResolvedSchema,
    project_name: str,
    constraints: list[tuple[str, int, str]],
    headings: dict[str, str],
) -> tuple[list[GeneratedFile], list[GeneratedFile]]:
    """(model files, other backend files) — the first backend file is the
    one that registers every table's routes, which the wiring context
    calls the routes file."""
    module = module_path(project_name)
    snapshot = db_schema.snapshot(schema)
    models = [
        model_file(t, snapshot, headings[t.sql_name], module) for t in schema.tables
    ]
    backend = [
        routes_file(schema, module),
        *[handlers_file(t, module) for t in schema.tables],
        models_file(),
        apierr_file(constraints),
        fields_file(module),
    ]
    return models, backend
