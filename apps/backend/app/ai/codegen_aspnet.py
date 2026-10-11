# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Deterministic (no-AI) C# backend: ASP.NET Core over
#  EF Core + SQLite
#  ai/codegen_aspnet.py — The ASP.NET Core backend codegen_deterministic
#  dispatches to. Per table: an entity (Models/) and an [ApiController]
#  controller (Controllers/). Shared by every table: Data/AppDbContext.cs
#  (how each entity maps to its table), Data/Migrator.cs, Support/ (the
#  request reader, errors, what each database constraint means, stored
#  value formats) and Program.cs.
#
#  Follows the knowledge registry's ASP.NET rules: minimal hosting in
#  Program.cs, [ApiController] controllers returning ActionResult<T>,
#  the DbContext injected through the constructor, async EF Core calls
#  only, no property named like its class.
#
#  Same REST surface as every other generated backend: /api/<table> and
#  /api/<table>/<id>, JSON keyed by column name, PUT changes only the
#  fields it sends (a Patch tells "left out" from "sent as null"), every
#  problem with a request reported at once, the database's constraint
#  violations answered with the same sentences. Errors are RFC 7807
#  problem details — the sentence is in "detail", which the screens read.
#
#  The schema is owned by the SQL migrations — the same files, and the
#  same `_migrations` table, as the Rust and Go backends
#  (migrations_sqlite), applied by the app's own runner (Data/Migrator.cs)
#  — NOT by EF Core migrations: those are C# classes plus a model snapshot
#  that `dotnet ef` writes by comparing two compiled models, which can't
#  be produced without running the user's .NET toolchain. EF Core is the
#  data access layer over tables it didn't create, so:
#    - AppDbContext names every table and column explicitly.
#    - Values are stored the way the migrations' CHECKs and defaults
#      compare them: a date-time as UTC text with six fractional digits
#      (a converter — EF's own format trims trailing zeros, and
#      "09:30:00" sorts before "09:30:00.000000"), a decimal as REAL (a
#      double property), JSON as its text.
#    - A field the request leaves out on create gets its default from
#      the code (the same default the migration gave the column), not
#      from EF's "omit the column when the property has its CLR default":
#      that rule can't tell `false` from "not sent" for a column that
#      defaults to true, nor an explicit null from a missing field.
#    - After a write the row is read back, so the answer is what is stored.
#
#  Names. C# resolves a simple name to the nearest type, so a table
#  called Table, Support or Data must not capture a name the generated
#  code uses:
#    - Entities are never imported: every file outside Models/ writes
#      Models.<Class>, so an entity called Task or List can't shadow the
#      framework's.
#    - An entity file itself uses only a handful of simple type names;
#      name_problems refuses a table that would be one of them.
#    - A controller's own names are fixed; what a request sent lives in
#      locals called in<Field>, which no fixed name can equal.
#    - [ApiController] is written out in full: a table called "Api"
#      makes a class ApiController, which would capture the short name.
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations

import re

from app.ai import db_schema, knowledge
from app.ai.codegen_shared import GeneratedFile
from app.ai.migrations_sqlite import storage_value

NAMESPACE = "GeneratedApp"
# .NET 10 is the current long-term-support release (.NET 8's support ends
# in November 2026).
TARGET_FRAMEWORK = "net10.0"
EF_CORE_VERSION = "10.0.12"
DEFAULT_PORT = 5000

# Simple type names an entity file uses: a table whose class would be one
# of these would capture it.
_ENTITY_FILE_NAMES = frozenset(
    {
        "DateOnly",
        "DateTime",
        "JsonConverter",
        "JsonConverterAttribute",
        "JsonPropertyName",
        "JsonPropertyNameAttribute",
        "RawJsonConverter",
    }
)
# Members every C# object has: a property with one of these names hides it.
_OBJECT_MEMBERS = frozenset(
    {
        "Equals",
        "Finalize",
        "GetHashCode",
        "GetType",
        "MemberwiseClone",
        "ReferenceEquals",
        "ToString",
    }
)
# Properties every entity has.
_FIXED_PROPERTIES = {"Id": "id", "CreatedAt": "created_at", "UpdatedAt": "updated_at"}

# C# type of a column's property …
_ROW_TYPE = {
    "string": "string",
    "text": "string",
    "integer": "long",
    "float": "double",
    "decimal": "double",
    "boolean": "bool",
    "date": "DateOnly",
    "datetime": "DateTime",
    "json": "string",
}
# … and the RequestBody method that reads it from a request.
_READER = {
    "string": "ReadText",
    "text": "ReadText",
    "integer": "ReadInteger",
    "float": "ReadNumber",
    "decimal": "ReadDecimal",
    "boolean": "ReadBoolean",
    "date": "ReadDate",
    "datetime": "ReadDateTime",
    "json": "ReadJson",
}
_REFERENCE_TYPES = frozenset({"string", "text", "json"})


# ───────────────────────────────────────────────
#  C# text helpers
# ───────────────────────────────────────────────
def cs_str(text: str) -> str:
    """A C# string literal for user text. "TODO" is written with an escape
    (same string at runtime) so the generated-file check, which looks for
    leftover TODO markers, doesn't flag a table's name. Anything that
    isn't printable is escaped — C# ends a line at U+2028 too."""
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


def doc(text: str) -> str:
    """User text on one comment line."""
    line = " ".join(str(text or "").split())
    return "".join(ch for ch in line if ch.isprintable()).replace("TODO", "to-do")


def prop(slug: str) -> str:
    """A column as a property: is_available -> IsAvailable."""
    return knowledge.identifier_for(slug, "pascal")


_TOKEN = re.compile(r"__([A-Z_]+?)__")


def _fill(template: str, **values: str) -> str:
    """Every __TOKEN__ replaced in one pass, so a value (a table's label,
    say) that happens to contain a token's text is left as written."""
    return _TOKEN.sub(lambda m: values[m.group(1)], template)


def name_problems(schema: db_schema.ResolvedSchema) -> list[str]:
    problems = []
    for t in schema.tables:
        if t.class_name in _ENTITY_FILE_NAMES:
            problems.append(
                f'The table "{t.name}" would produce a class named {t.class_name}, a name the generated '
                "code already uses — rename the table in Architecture."
            )
        if t.class_name.endswith("Controller"):
            problems.append(
                f'The table "{t.name}" would produce a class named {t.class_name}, and ASP.NET treats '
                "every class named …Controller as a controller — rename the table in Architecture."
            )
        taken = dict(_FIXED_PROPERTIES)
        for c in t.columns:
            name = prop(c.column)
            if name in _FIXED_PROPERTIES:
                problems.append(
                    f'The field "{c.name}" in "{t.name}" would be the C# property {name}, which every '
                    f"generated entity already has (for {_FIXED_PROPERTIES[name]}) — rename it in Architecture."
                )
            elif name in taken:
                problems.append(
                    f'The fields "{taken[name]}" and "{c.name}" in "{t.name}" would both be the C# '
                    f"property {name} — rename one of them in Architecture."
                )
            elif name in _OBJECT_MEMBERS:
                problems.append(
                    f'The field "{c.name}" in "{t.name}" would be the C# property {name}, which would '
                    "hide a member every C# object has — rename it in Architecture."
                )
            elif name == t.class_name:
                problems.append(
                    f'The field "{c.name}" in "{t.name}" would be a C# property with its own class\'s '
                    f"name ({name}) — rename it in Architecture."
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


def _default_expr(col: dict, kind: str) -> str | None:
    """C# for the default the migration gave a column, or None."""
    default = col.get("default")
    if not default:
        return None
    if default["kind"] == "now":
        return "Stored.Now()"
    if default["kind"] == "today":
        return "Stored.Today()"
    value = default["value"]
    if kind in ("string", "text"):
        return cs_str(value)
    if kind == "integer":
        return str(int(value))
    if kind in ("float", "decimal"):
        number = repr(float(value))
        return number if "." in number or "e" in number else f"{number}.0"
    if kind == "boolean":
        return "true" if value else "false"
    if kind == "date":
        year, month, day = str(storage_value(value, "date")).split("-")
        return f"new DateOnly({int(year)}, {int(month)}, {int(day)})"
    if kind == "datetime":
        return f"Stored.ParseDateTime({cs_str(storage_value(value, 'datetime'))})"
    return cs_str(storage_value(value, "json"))


# ───────────────────────────────────────────────
#  Models/<Class>.cs
# ───────────────────────────────────────────────
def model_file(
    t: db_schema.ResolvedTable, snapshot: dict, heading: str
) -> GeneratedFile:
    tables = snapshot["tables"]
    table = tables[t.sql_name]
    label = doc(table["label"])
    members = ['    [JsonPropertyName("id")]', "    public long Id { get; set; }"]
    for c in table["column_order"]:
        col = table["columns"][c]
        kind = _base(col, tables)["type"]
        ctype = _ROW_TYPE[kind]
        members += ["", f'    [JsonPropertyName("{c}")]']
        if kind == "json":
            members.append("    [JsonConverter(typeof(RawJsonConverter))]")
        if col["nullable"]:
            members.append(f"    public {ctype}? {prop(c)} {{ get; set; }}")
        elif kind in _REFERENCE_TYPES:
            initial = '"null"' if kind == "json" else '""'
            members.append(f"    public {ctype} {prop(c)} {{ get; set; }} = {initial};")
        else:
            members.append(f"    public {ctype} {prop(c)} {{ get; set; }}")
    members += [
        "",
        '    [JsonPropertyName("created_at")]',
        "    public DateTime CreatedAt { get; set; }",
        "",
        '    [JsonPropertyName("updated_at")]',
        "    public DateTime UpdatedAt { get; set; }",
    ]
    lines = [
        f"// {doc(heading)}",
        "//",
        "// Deterministically generated by VengaiCode from the Architecture tab (no AI",
        "// call). The table is created and changed by the migrations in migrations/,",
        "// which the app applies as it starts (Data/Migrator.cs); Data/AppDbContext.cs",
        "// maps each property to its column.",
        "",
        "using System.Text.Json.Serialization;",
        f"using {NAMESPACE}.Support;",
        "",
        f"namespace {NAMESPACE}.Models;",
        "",
        f"// One row of {label} as the API answers it, keyed by column name.",
        f"public class {t.class_name}",
        "{",
        *members,
        "",
        f"    // VENGAI:CUSTOM:{t.slug}_model:start",
        f"    // Add members for {label} here. A new column belongs in the Architecture",
        "    // tab instead, so a migration adds it to the database.",
        "    // This block is preserved across future regenerations.",
        f"    // VENGAI:CUSTOM:{t.slug}_model:end",
        "}",
        "",
    ]
    return GeneratedFile(
        path=f"backend/Models/{t.class_name}.cs",
        language="csharp",
        content="\n".join(lines),
        description=f"Deterministic entity for {t.name}",
    )


# ───────────────────────────────────────────────
#  Controllers/<Class>Controller.cs
# ───────────────────────────────────────────────
_CONTROLLER_CS = """// REST routes for __TITLE__ — the paths the generated screens call.
// Deterministically generated by VengaiCode (no AI call).

using __NAMESPACE__.Data;
using __NAMESPACE__.Support;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace __NAMESPACE__.Controllers;

[Microsoft.AspNetCore.Mvc.ApiController]
[Route(__ROUTE__)]
public class __NAME__Controller : ControllerBase
{
    private const string Label = __LABEL__;
    private const string RestrictMessage = __RESTRICT__;

    private readonly AppDbContext _db;

    public __NAME__Controller(AppDbContext db)
    {
        _db = db;
    }

    [HttpGet]
    public async Task<ActionResult<List<Models.__NAME__>>> List()
    {
        return await _db.Set<Models.__NAME__>().AsNoTracking().OrderBy(row => row.Id).ToListAsync();
    }

    [HttpGet("{id}")]
    public async Task<ActionResult<Models.__NAME__>> Read(string id)
    {
        return await Find(RequestBody.ParseId(id));
    }

    [HttpPost]
    public async Task<ActionResult<Models.__NAME__>> Create()
    {
        var row = new Models.__NAME__();
        await Fill(row, creating: true);
        row.CreatedAt = Stored.Now();
        row.UpdatedAt = row.CreatedAt;
        _db.Add(row);
        await Database.SaveAsync(_db);
        // Answered as stored.
        await _db.Entry(row).ReloadAsync();
        return StatusCode(StatusCodes.Status201Created, row);
    }

    // Changes only the fields the request sends, like the other generated backends.
    [HttpPut("{id}")]
    public async Task<ActionResult<Models.__NAME__>> Update(string id)
    {
        var row = await Find(RequestBody.ParseId(id));
        await Fill(row, creating: false);
        row.UpdatedAt = Stored.Now();
        await Database.SaveAsync(_db);
        await _db.Entry(row).ReloadAsync();
        return row;
    }

    // A 404 when the row isn't there, a 409 when other rows still need it.
    [HttpDelete("{id}")]
    public async Task<IActionResult> Delete(string id)
    {
        var row = await Find(RequestBody.ParseId(id));
        _db.Remove(row);
        await Database.SaveAsync(_db, RestrictMessage);
        return NoContent();
    }

    private async Task<Models.__NAME__> Find(long id)
    {
        return await _db.Set<Models.__NAME__>().FindAsync(id) ?? throw ApiException.NotFound(Label, id);
    }

    // Reads the request body into row. Every field is checked first (every
    // problem at once, as one 422) and every foreign key has to point at a row
    // that exists; only then are the fields the request sent set. On create, a
    // field it left out gets its default.
    private async Task Fill(Models.__NAME__ row, bool creating)
    {
        var body = await RequestBody.ReadAsync(Request);
__READS____CHECKS__        body.ThrowIfInvalid();
__REFERENCES____APPLY__    }

    // VENGAI:CUSTOM:__SLUG___routes:start
    // Add custom, non-CRUD actions here, e.g.
    // [HttpGet("export")] public async Task<IActionResult> Export() => Ok(await List());
    // This block is preserved across regenerations.
    // VENGAI:CUSTOM:__SLUG___routes:end
}
"""


def controller_file(
    t: db_schema.ResolvedTable, snapshot: dict, class_names: dict[str, str]
) -> GeneratedFile:
    """class_names: every table's entity class, by its SQL name."""
    tables = snapshot["tables"]
    table = tables[t.sql_name]
    reads: list[str] = []
    checks: list[str] = []
    references: list[str] = []
    apply: list[str] = []
    for c in table["column_order"]:
        col = table["columns"][c]
        base = _base(col, tables)
        kind = base["type"]
        local = f"in{prop(c)}"
        target = f"row.{prop(c)}"
        reads.append(f"        var {local} = body.{_READER[kind]}({cs_str(c)});")
        if not col["nullable"] and col["default"] is None:
            checks.append(f"        body.Required({local}, {cs_str(c)}, creating);")
        elif not col["nullable"]:
            checks.append(f"        body.NotNull({local}, {cs_str(c)});")
        if kind == "string" and base.get("length"):
            checks.append(
                f"        body.MaxChars({local}, {base['length']}, {cs_str(c)});"
            )
        if col["fk"]:
            fk = col["fk"]
            parent = tables[fk["table"]]
            parent_class = class_names[fk["table"]]
            parent_prop = "Id" if fk["column"] == "id" else prop(fk["column"])
            message = f"{c}: no row in {parent['label']} has {fk['column']}"
            references += [
                f"        if ({local}.Sent && !{local}.IsNull && !await _db.Set<Models.{parent_class}>()"
                f".AnyAsync(parent => parent.{parent_prop} == {local}.Value))",
                "        {",
                f"            throw ApiException.MissingParent({cs_str(message)}, {local}.Value);",
                "        }",
            ]
        if col["nullable"]:
            value = (
                f"{local}.Value" if kind in _REFERENCE_TYPES else f"{local}.OrNull()"
            )
        else:
            value = f"{local}.Value!" if kind in _REFERENCE_TYPES else f"{local}.Value"
        apply += [
            f"        if ({local}.Sent)",
            "        {",
            f"            {target} = {value};",
            "        }",
        ]
        default = _default_expr(col, kind)
        if default is not None:
            apply += [
                "        else if (creating)",
                "        {",
                f"            {target} = {default};",
                "        }",
            ]

    def block(lines: list[str]) -> str:
        return "".join(f"{line}\n" for line in lines)

    content = _fill(
        _CONTROLLER_CS,
        TITLE=doc(t.name),
        NAMESPACE=NAMESPACE,
        ROUTE=cs_str(f"api/{t.sql_name}"),
        NAME=t.class_name,
        LABEL=cs_str(table["label"]),
        RESTRICT=cs_str(_restrict_message(t.sql_name, snapshot)),
        READS=block(reads),
        CHECKS=block(checks),
        REFERENCES="\n" + block(references) if references else "",
        APPLY="\n" + block(apply) if apply else "",
        SLUG=t.slug,
    )
    return GeneratedFile(
        path=f"backend/Controllers/{t.class_name}Controller.cs",
        language="csharp",
        content=content,
        description=f"REST routes for {t.name}",
    )


# ───────────────────────────────────────────────
#  Data/AppDbContext.cs — how every entity maps to its table
# ───────────────────────────────────────────────
_DB_CONTEXT_CS = """// How every entity maps to its table. The tables themselves are created and
// changed by the SQL migrations (Data/Migrator.cs), not by EF Core, so every
// table and column is named here rather than left to a convention. Written by
// VengaiCode.

using __NAMESPACE__.Support;
using Microsoft.EntityFrameworkCore;

namespace __NAMESPACE__.Data;

public class AppDbContext : DbContext
{
    public AppDbContext(DbContextOptions<AppDbContext> options) : base(options)
    {
    }

    protected override void ConfigureConventions(ModelConfigurationBuilder configurationBuilder)
    {
        // Date-times are stored as the migrations' CHECKs and defaults compare
        // them: UTC text with six fractional digits.
        configurationBuilder.Properties<DateTime>().HaveConversion<StoredDateTimeConverter>();
    }

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
__ENTITIES__    }
}
"""


def db_context_file(schema: db_schema.ResolvedSchema, snapshot: dict) -> GeneratedFile:
    blocks = []
    for t in schema.tables:
        table = snapshot["tables"][t.sql_name]
        columns = [
            ("Id", "id"),
            *[(prop(c), c) for c in table["column_order"]],
            ("CreatedAt", "created_at"),
            ("UpdatedAt", "updated_at"),
        ]
        blocks.append(
            "\n".join(
                [
                    f"        modelBuilder.Entity<Models.{t.class_name}>(entity =>",
                    "        {",
                    f"            entity.ToTable({cs_str(t.sql_name)});",
                    "            entity.HasKey(row => row.Id);",
                    *[
                        f"            entity.Property(row => row.{name}).HasColumnName({cs_str(column)});"
                        for name, column in columns
                    ],
                    "        });",
                ]
            )
        )
    return GeneratedFile(
        path="backend/Data/AppDbContext.cs",
        language="csharp",
        content=_fill(
            _DB_CONTEXT_CS,
            NAMESPACE=NAMESPACE,
            ENTITIES="".join(f"{b}\n" for b in "\n\n".join(blocks).split("\n")),
        ),
        description="EF Core DbContext — maps every entity to its table",
    )


# ───────────────────────────────────────────────
#  Data/Migrator.cs — the app's own migration runner. The same steps, the
#  same `_migrations` table and the same files as the Rust and Go
#  backends' runners, which is what lets a database move between them.
#  The files are embedded resources (see the .csproj), so this file is
#  the same for every project and a migration added by hand is picked up.
# ───────────────────────────────────────────────
_MIGRATOR_CS = """// Applies this app's database migrations, the .sql files in migrations/.
// Written by VengaiCode. Every migration is compiled into the app (see the
// EmbeddedResource item in the project file), so a published build needs no
// files beside it.
//
// SQLite changes a column by rebuilding its table, and with foreign keys ON,
// dropping a parent table deletes its children. So migrations run on a
// connection of their own that has foreign keys off; every other connection
// the app opens has them on (Program.cs).

using System.Globalization;
using Microsoft.Data.Sqlite;

namespace __NAMESPACE__.Data;

public static class Migrator
{
    private const string Folder = "migrations/";

    // One NNNN_name.sql file, with a `-- migrate:up` and a `-- migrate:down` section.
    private sealed record Migration(long Version, string Name, string Text);

    // Applies every pending migration, oldest first.
    public static void Run(string databasePath)
    {
        using var connection = Open(databasePath);
        var done = Applied(connection);
        foreach (var migration in Load())
        {
            if (done.Contains(migration.Version))
            {
                continue;
            }
            Apply(connection, migration, Section(migration.Text, "up"), "INSERT INTO _migrations (version, name) VALUES ($version, $name)");
            Console.WriteLine($"applied migration {migration.Version:D4} {migration.Name}");
        }
    }

    // Undoes the newest applied migration (`dotnet run -- revert`).
    public static void Revert(string databasePath)
    {
        using var connection = Open(databasePath);
        var done = Applied(connection);
        if (done.Count == 0)
        {
            Console.WriteLine("no migration to revert");
            return;
        }
        var newest = done[^1];
        var migration = Load().Find(candidate => candidate.Version == newest)
            ?? throw new InvalidOperationException($"applied migration {newest:D4} is missing from migrations/");
        Apply(connection, migration, Section(migration.Text, "down"), "DELETE FROM _migrations WHERE version = $version AND name = $name");
        Console.WriteLine($"reverted migration {migration.Version:D4} {migration.Name}");
    }

    private static SqliteConnection Open(string databasePath)
    {
        var settings = new SqliteConnectionStringBuilder
        {
            DataSource = databasePath,
            ForeignKeys = false,
            Pooling = false,
        };
        var connection = new SqliteConnection(settings.ToString());
        connection.Open();
        return connection;
    }

    // Every migration, oldest first.
    private static List<Migration> Load()
    {
        var assembly = typeof(Migrator).Assembly;
        var all = new List<Migration>();
        foreach (var resource in assembly.GetManifestResourceNames())
        {
            if (!resource.StartsWith(Folder, StringComparison.Ordinal) || !resource.EndsWith(".sql", StringComparison.Ordinal))
            {
                continue;
            }
            var file = resource[Folder.Length..^4];
            var split = file.IndexOf('_');
            var number = split < 0 ? file : file[..split];
            if (!long.TryParse(number, NumberStyles.None, CultureInfo.InvariantCulture, out var version))
            {
                throw new InvalidOperationException($"migration {file}.sql: its name has to start with its number");
            }
            using var stream = assembly.GetManifestResourceStream(resource)
                ?? throw new InvalidOperationException($"migration {file}.sql can't be read");
            using var reader = new StreamReader(stream);
            all.Add(new Migration(version, split < 0 ? "" : file[(split + 1)..], reader.ReadToEnd()));
        }
        all.Sort((left, right) => left.Version.CompareTo(right.Version));
        return all;
    }

    // The SQL under `-- migrate:<name>`, up to the next section.
    private static string Section(string text, string name)
    {
        var marker = "-- migrate:" + name;
        var start = text.IndexOf(marker, StringComparison.Ordinal);
        if (start < 0)
        {
            return "";
        }
        var rest = text[(start + marker.Length)..];
        var end = rest.IndexOf("-- migrate:", StringComparison.Ordinal);
        return end < 0 ? rest : rest[..end];
    }

    // The versions already applied, oldest first.
    private static List<long> Applied(SqliteConnection connection)
    {
        using (var create = connection.CreateCommand())
        {
            create.CommandText = "CREATE TABLE IF NOT EXISTS _migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)";
            create.ExecuteNonQuery();
        }
        var versions = new List<long>();
        using var select = connection.CreateCommand();
        select.CommandText = "SELECT version FROM _migrations ORDER BY version";
        using var rows = select.ExecuteReader();
        while (rows.Read())
        {
            versions.Add(rows.GetInt64(0));
        }
        return versions;
    }

    // Runs one migration's SQL and records it, in one transaction.
    private static void Apply(SqliteConnection connection, Migration migration, string sql, string record)
    {
        using (var transaction = connection.BeginTransaction())
        {
            if (!string.IsNullOrWhiteSpace(sql))
            {
                using var change = connection.CreateCommand();
                change.Transaction = transaction;
                change.CommandText = sql;
                change.ExecuteNonQuery();
            }
            using var bookkeeping = connection.CreateCommand();
            bookkeeping.Transaction = transaction;
            bookkeeping.CommandText = record;
            bookkeeping.Parameters.AddWithValue("$version", migration.Version);
            bookkeeping.Parameters.AddWithValue("$name", migration.Name);
            bookkeeping.ExecuteNonQuery();
            transaction.Commit();
        }

        // Foreign keys were off while the tables were rebuilt: report any row that
        // now points at nothing (Postgres would have refused such a migration).
        using var check = connection.CreateCommand();
        check.CommandText = "PRAGMA foreign_key_check";
        using var broken = check.ExecuteReader();
        var count = 0;
        while (broken.Read())
        {
            count++;
        }
        if (count > 0)
        {
            Console.Error.WriteLine($"migration {migration.Version:D4}: {count} row(s) point at a row that doesn't exist");
        }
    }
}
"""


def migrator_cs() -> str:
    return _fill(_MIGRATOR_CS, NAMESPACE=NAMESPACE)


# ───────────────────────────────────────────────
#  Support/ — the same for every project, except the constraint table
# ───────────────────────────────────────────────
_API_EXCEPTION_CS = """// A failure with the HTTP status to answer it with. Program.cs turns one into
// a problem-details response whose "detail" is the sentence the generated
// screens show. Written by VengaiCode.

using System.Globalization;

namespace __NAMESPACE__.Support;

public sealed class ApiException : Exception
{
    public ApiException(int status, string detail) : base(detail)
    {
        Status = status;
        Detail = detail;
    }

    public int Status { get; }

    public string Detail { get; }

    // The 404 for a row that isn't there.
    public static ApiException NotFound(string label, long id)
    {
        return new ApiException(StatusCodes.Status404NotFound, string.Create(CultureInfo.InvariantCulture, $"{label} {id} not found."));
    }

    // The 422 for a foreign key that points at no row. problem starts the sentence.
    public static ApiException MissingParent(string problem, object? value)
    {
        return new ApiException(StatusCodes.Status422UnprocessableEntity, string.Create(CultureInfo.InvariantCulture, $"{problem} {value}."));
    }
}
"""

_REQUEST_BODY_CS = """// Reads a request's JSON object one field at a time, noting every problem so
// they can be answered at once. Written by VengaiCode.
//
// A request may leave a field out (the default applies, or an update keeps the
// value) or send it as null; a Patch records which.

using System.Globalization;
using System.Text.Encodings.Web;
using System.Text.Json;

namespace __NAMESPACE__.Support;

// A request field: Sent is false when the request left it out; IsNull is true
// when it sent null.
public readonly record struct Patch<T>(bool Sent, bool IsNull, T? Value);

public static class PatchExtensions
{
    // The value of a number, true/false or date field, or null.
    public static T? OrNull<T>(this Patch<T> field) where T : struct
    {
        return field.IsNull ? null : field.Value;
    }
}

public sealed class RequestBody
{
    // Digits a decimal keeps, and how many of them follow the point.
    private const int DecimalDigits = __DIGITS__;
    private const int DecimalPlaces = __PLACES__;

    private const string NotADecimal = "expected a number like 12.50";

    private static readonly string[] DateTimeFormats =
    {
        "yyyy-MM-dd'T'HH:mm:ss.FFFFFFFK",
        "yyyy-MM-dd HH:mm:ss.FFFFFFFK",
        "yyyy-MM-dd'T'HH:mmK",
        "yyyy-MM-dd HH:mmK",
    };

    private static readonly JsonSerializerOptions Compact = new()
    {
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
    };

    private readonly JsonElement _fields;
    private readonly List<string> _problems = new();

    private RequestBody(JsonElement fields)
    {
        _fields = fields;
    }

    // The request's JSON object; a 400 for anything else.
    public static async Task<RequestBody> ReadAsync(HttpRequest request)
    {
        try
        {
            using var document = await JsonDocument.ParseAsync(request.Body, cancellationToken: request.HttpContext.RequestAborted);
            if (document.RootElement.ValueKind == JsonValueKind.Object)
            {
                return new RequestBody(document.RootElement.Clone());
            }
        }
        catch (JsonException)
        {
            // Answered below, like any other body that isn't an object.
        }
        throw new ApiException(StatusCodes.Status400BadRequest, "Send the record as a JSON object.");
    }

    // The {id} in a route's path.
    public static long ParseId(string text)
    {
        if (long.TryParse(text, NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out var id))
        {
            return id;
        }
        throw new ApiException(StatusCodes.Status400BadRequest, "id: not a valid id");
    }

    public Patch<string> ReadText(string name)
    {
        return Read(name, value => value.ValueKind == JsonValueKind.String
            ? value.GetString()!
            : throw new FormatException("expected text"));
    }

    public Patch<long> ReadInteger(string name)
    {
        return Read(name, value => value.ValueKind == JsonValueKind.Number && value.TryGetInt64(out var number)
            ? number
            : throw new FormatException("expected a whole number"));
    }

    public Patch<double> ReadNumber(string name)
    {
        return Read(name, value => value.ValueKind == JsonValueKind.Number && value.TryGetDouble(out var number) && double.IsFinite(number)
            ? number
            : throw new FormatException("expected a number"));
    }

    // A fixed-point number: a JSON number, or text like "12.50".
    public Patch<double> ReadDecimal(string name)
    {
        return Read(name, value =>
        {
            string text;
            if (value.ValueKind == JsonValueKind.String)
            {
                text = value.GetString()!.Trim();
            }
            else if (value.ValueKind == JsonValueKind.Number)
            {
                // A JSON number may be written 1.25e1; its digits are what get checked.
                text = decimal.TryParse(value.GetRawText(), NumberStyles.Float, CultureInfo.InvariantCulture, out var exact)
                    ? exact.ToString(CultureInfo.InvariantCulture)
                    : throw new FormatException("number is too large");
            }
            else
            {
                throw new FormatException(NotADecimal);
            }
            return ParseDecimal(text);
        });
    }

    public Patch<bool> ReadBoolean(string name)
    {
        return Read(name, value => value.ValueKind switch
        {
            JsonValueKind.True => true,
            JsonValueKind.False => false,
            _ => throw new FormatException("expected true or false"),
        });
    }

    // A date: "2024-01-31".
    public Patch<DateOnly> ReadDate(string name)
    {
        return Read(name, value => value.ValueKind == JsonValueKind.String
            && DateOnly.TryParseExact(value.GetString()!.Trim(), "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var day)
            ? day
            : throw new FormatException("expected a date like 2024-01-31"));
    }

    // A date-time: RFC 3339 ("2024-01-31T09:30:00Z", any offset), or without an
    // offset, read as UTC. Kept in UTC, to the microsecond it is stored with.
    public Patch<DateTime> ReadDateTime(string name)
    {
        return Read(name, value => value.ValueKind == JsonValueKind.String
            && DateTimeOffset.TryParseExact(value.GetString()!.Trim(), DateTimeFormats, CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal, out var when)
            ? Stored.Truncate(when.UtcDateTime)
            : throw new FormatException("expected a date and time like 2024-01-31T09:30:00Z"));
    }

    // Any JSON value, kept as its text.
    public Patch<string> ReadJson(string name)
    {
        return Read(name, value => JsonSerializer.Serialize(value, Compact));
    }

    // A NOT NULL field with no default: needed on create, never null.
    public void Required<T>(Patch<T> field, string name, bool creating)
    {
        if (field.IsNull)
        {
            _problems.Add($"{name}: may not be null");
        }
        else if (creating && !field.Sent)
        {
            _problems.Add($"{name}: is required");
        }
    }

    // A NOT NULL field with a default: may be left out, never null.
    public void NotNull<T>(Patch<T> field, string name)
    {
        if (field.IsNull)
        {
            _problems.Add($"{name}: may not be null");
        }
    }

    // Text no longer than its column allows.
    public void MaxChars(Patch<string> field, int limit, string name)
    {
        if (field.Value is { } text && text.EnumerateRunes().Count() > limit)
        {
            _problems.Add(string.Create(CultureInfo.InvariantCulture, $"{name}: at most {limit} characters"));
        }
    }

    // Every problem found, as one 422 — or nothing.
    public void ThrowIfInvalid()
    {
        if (_problems.Count > 0)
        {
            throw new ApiException(StatusCodes.Status422UnprocessableEntity, string.Join("\\n", _problems));
        }
    }

    private Patch<T> Read<T>(string name, Func<JsonElement, T> parse)
    {
        if (!_fields.TryGetProperty(name, out var value))
        {
            return default;
        }
        if (value.ValueKind == JsonValueKind.Null)
        {
            return new Patch<T>(true, true, default);
        }
        try
        {
            return new Patch<T>(true, false, parse(value));
        }
        catch (FormatException problem)
        {
            // A value of the wrong kind, named by its field.
            _problems.Add($"{name}: {problem.Message}");
            return new Patch<T>(true, false, default);
        }
    }

    private static double ParseDecimal(string text)
    {
        var unsigned = text.StartsWith('-') ? text[1..] : text;
        var point = unsigned.IndexOf('.');
        var whole = point < 0 ? unsigned : unsigned[..point];
        var fraction = point < 0 ? "" : unsigned[(point + 1)..];
        if (whole.Length == 0 || !whole.All(char.IsAsciiDigit) || !fraction.All(char.IsAsciiDigit) || unsigned.EndsWith('.'))
        {
            throw new FormatException(NotADecimal);
        }
        if (fraction.TrimEnd('0').Length > DecimalPlaces)
        {
            throw new FormatException(string.Create(CultureInfo.InvariantCulture, $"only {DecimalPlaces} decimal places are stored"));
        }
        if (whole.TrimStart('0').Length > DecimalDigits - DecimalPlaces)
        {
            throw new FormatException("number is too large");
        }
        return double.Parse(text, NumberStyles.Float, CultureInfo.InvariantCulture);
    }
}
"""

_STORED_CS = """// How values are stored, and how a failed write is explained. Written by
// VengaiCode.
//
// Values are stored the way SQLite compares them: date-times as UTC text with
// six fractional digits ("2024-01-31 09:30:00.000000"), dates as "2024-01-31",
// booleans as 0/1 and JSON as its text.

using System.Globalization;
using System.Text.Json;
using System.Text.Json.Serialization;
using Microsoft.Data.Sqlite;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Storage.ValueConversion;

namespace __NAMESPACE__.Support;

public static class Stored
{
    private const string DateTimeFormat = "yyyy-MM-dd HH:mm:ss.ffffff";

    // Now, in UTC, to the microsecond it is stored with.
    public static DateTime Now()
    {
        return Truncate(DateTime.UtcNow);
    }

    // Today's date in UTC, like SQLite's CURRENT_DATE.
    public static DateOnly Today()
    {
        return DateOnly.FromDateTime(DateTime.UtcNow);
    }

    public static DateTime Truncate(DateTime value)
    {
        return new DateTime(value.Ticks - (value.Ticks % 10), DateTimeKind.Utc);
    }

    public static string FormatDateTime(DateTime value)
    {
        return value.ToString(DateTimeFormat, CultureInfo.InvariantCulture);
    }

    public static DateTime ParseDateTime(string text)
    {
        return DateTime.Parse(text, CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal);
    }
}

// Stores a DateTime as Stored's UTC text, and reads it back as UTC.
public sealed class StoredDateTimeConverter : ValueConverter<DateTime, string>
{
    public StoredDateTimeConverter()
        : base(value => Stored.FormatDateTime(value), text => Stored.ParseDateTime(text))
    {
    }
}

// Answers a stored JSON value as JSON rather than as its text.
public sealed class RawJsonConverter : JsonConverter<string>
{
    public override string? Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options)
    {
        using var document = JsonDocument.ParseValue(ref reader);
        return document.RootElement.GetRawText();
    }

    public override void Write(Utf8JsonWriter writer, string value, JsonSerializerOptions options)
    {
        try
        {
            writer.WriteRawValue(value);
        }
        catch (Exception problem) when (problem is JsonException or ArgumentException)
        {
            // Not JSON (written by hand, say): answered as stored.
            writer.WriteStringValue(value);
        }
    }
}

public static class Database
{
    // Saves, explaining a refusal by the database. For a delete, restrictMessage
    // is what a foreign key's refusal means: rows still refer to this one.
    public static async Task SaveAsync(DbContext db, string? restrictMessage = null)
    {
        try
        {
            await db.SaveChangesAsync();
        }
        catch (DbUpdateException failure) when (failure.InnerException is SqliteException refusal)
        {
            throw Explain(refusal.Message, restrictMessage);
        }
    }

    // What each database constraint means, so a violation comes back as a
    // sentence instead of a raw database error: (its name in the database's
    // message, HTTP status, sentence). Longest names first.
    private static readonly (string Key, int Status, string Message)[] Constraints =
    {
__CONSTRAINTS__    };

    private static ApiException Explain(string text, string? restrictMessage)
    {
        const string notNull = "NOT NULL constraint failed: ";
        if (text.Contains("UNIQUE constraint failed", StringComparison.Ordinal) || text.Contains("CHECK constraint failed", StringComparison.Ordinal))
        {
            // SQLite names a failed UNIQUE by its columns, a failed CHECK by its name.
            foreach (var constraint in Constraints)
            {
                if (Names(text, constraint.Key))
                {
                    return new ApiException(constraint.Status, constraint.Message);
                }
            }
        }
        var at = text.IndexOf(notNull, StringComparison.Ordinal);
        if (at >= 0)
        {
            var column = text[(at + notNull.Length)..].TrimEnd('.', '\\'');
            return new ApiException(StatusCodes.Status422UnprocessableEntity, column + ": may not be null");
        }
        if (text.Contains("FOREIGN KEY constraint failed", StringComparison.Ordinal))
        {
            return restrictMessage is null
                ? new ApiException(StatusCodes.Status422UnprocessableEntity, "A record this one refers to doesn't exist.")
                : new ApiException(StatusCodes.Status409Conflict, restrictMessage);
        }
        return new ApiException(StatusCodes.Status409Conflict, "The database refused this change: " + text);
    }

    // Whether the message names key whole, not as part of a longer name.
    private static bool Names(string text, string key)
    {
        if (key.Length == 0)
        {
            return false;
        }
        for (var at = text.IndexOf(key, StringComparison.Ordinal); at >= 0; at = text.IndexOf(key, at + 1, StringComparison.Ordinal))
        {
            var end = at + key.Length;
            var before = at > 0 && NamePart(text[at - 1]);
            var after = end < text.Length && NamePart(text[end]);
            if (!before && !after)
            {
                return true;
            }
        }
        return false;
    }

    private static bool NamePart(char c)
    {
        return char.IsLetterOrDigit(c) || c == '_' || c == '.';
    }
}
"""


def support_files(constraints: list[tuple[str, int, str]]) -> list[GeneratedFile]:
    entries = "".join(
        f"        ({cs_str(k)}, {s}, {cs_str(m)}),\n"
        for k, s, m in sorted(constraints, key=lambda e: -len(e[0]))
    )
    return [
        GeneratedFile(
            path="backend/Support/ApiException.cs",
            language="csharp",
            content=_fill(_API_EXCEPTION_CS, NAMESPACE=NAMESPACE),
            description="A failure with the HTTP status to answer it with",
        ),
        GeneratedFile(
            path="backend/Support/RequestBody.cs",
            language="csharp",
            content=_fill(
                _REQUEST_BODY_CS,
                NAMESPACE=NAMESPACE,
                DIGITS=str(db_schema.DECIMAL_PRECISION),
                PLACES=str(db_schema.DECIMAL_SCALE),
            ),
            description="Reads and checks a request's fields, one Patch each",
        ),
        GeneratedFile(
            path="backend/Support/Stored.cs",
            language="csharp",
            content=_fill(_STORED_CS, NAMESPACE=NAMESPACE, CONSTRAINTS=entries),
            description="Stored value formats, and what each database constraint means",
        ),
    ]


# ───────────────────────────────────────────────
#  Program.cs, the project file and appsettings.json (the ASP.NET
#  adapter's migrations mode)
# ───────────────────────────────────────────────
_PROGRAM_CS = """// __TITLE__ API, written by VengaiCode.
//
// `dotnet run` applies any pending database migrations, then serves the API on
// 127.0.0.1:__PORT__ (set PORT to change it). `dotnet run -- revert` undoes the
// newest migration. The database is SQLite: app.db beside where it runs, or the
// file DATABASE_PATH names.

using __NAMESPACE__.Data;
using __NAMESPACE__.Support;
using Microsoft.Data.Sqlite;
using Microsoft.EntityFrameworkCore;

const string RootMessage = __MESSAGE__;

var databasePath = Environment.GetEnvironmentVariable("DATABASE_PATH");
if (string.IsNullOrEmpty(databasePath))
{
    databasePath = "app.db";
}

if (args.Length > 0 && args[0] == "revert")
{
    Migrator.Revert(databasePath);
    return;
}
Migrator.Run(databasePath);

var port = Environment.GetEnvironmentVariable("PORT");
if (string.IsNullOrEmpty(port))
{
    port = "__PORT__";
}

var builder = WebApplication.CreateBuilder(args);
builder.WebHost.UseUrls($"http://127.0.0.1:{port}");
builder.Services.AddControllers();

// SQLite enforces foreign keys only on connections that ask for it.
var connection = new SqliteConnectionStringBuilder { DataSource = databasePath, ForeignKeys = true };
builder.Services.AddDbContext<AppDbContext>(options => options.UseSqlite(connection.ToString()));

// The screens may call the API from another origin (a packaged app's window
// isn't the API's origin).
builder.Services.AddCors(options => options.AddDefaultPolicy(policy => policy.AllowAnyOrigin().AllowAnyMethod().AllowAnyHeader()));

var app = builder.Build();
app.UseCors();

// Every failure answers problem details with its HTTP status; "detail" is the
// sentence the generated screens show.
app.Use(async (context, next) =>
{
    try
    {
        await next(context);
    }
    catch (ApiException problem)
    {
        await Results.Problem(detail: problem.Detail, statusCode: problem.Status).ExecuteAsync(context);
    }
    catch (Exception failure) when (!context.Response.HasStarted)
    {
        app.Logger.LogError(failure, "internal error");
        await Results.Problem(detail: "Something went wrong on the server.", statusCode: StatusCodes.Status500InternalServerError).ExecuteAsync(context);
    }
});

app.MapGet("/", () => Results.Json(new { message = RootMessage }));
app.MapControllers();
app.Run();
"""

_CSPROJ = """<Project Sdk="Microsoft.NET.Sdk.Web">

  <PropertyGroup>
    <TargetFramework>__FRAMEWORK__</TargetFramework>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
    <RootNamespace>__NAMESPACE__</RootNamespace>
    <InvariantGlobalization>true</InvariantGlobalization>
  </PropertyGroup>

  <ItemGroup>
    <PackageReference Include="Microsoft.EntityFrameworkCore.Sqlite" Version="__EF_VERSION__" />
  </ItemGroup>

  <!-- The SQL migrations are compiled into the app (Data/Migrator.cs reads them),
       so a published build needs no files beside it. -->
  <ItemGroup>
    <EmbeddedResource Include="migrations/*.sql" LogicalName="migrations/%(Filename)%(Extension)" />
  </ItemGroup>

</Project>
"""

_APPSETTINGS = """{
  "Logging": {
    "LogLevel": {
      "Default": "Information",
      "Microsoft.AspNetCore": "Warning",
      "Microsoft.EntityFrameworkCore.Database.Command": "Warning"
    }
  },
  "AllowedHosts": "*"
}
"""


def program_cs(project_name: str) -> str:
    return _fill(
        _PROGRAM_CS,
        TITLE=doc(project_name),
        NAMESPACE=NAMESPACE,
        PORT=str(DEFAULT_PORT),
        MESSAGE=cs_str(f"{project_name} API is running"),
    )


def csproj() -> str:
    return _fill(
        _CSPROJ,
        FRAMEWORK=TARGET_FRAMEWORK,
        NAMESPACE=NAMESPACE,
        EF_VERSION=EF_CORE_VERSION,
    )


def appsettings_json() -> str:
    return _APPSETTINGS


def backend_files(
    schema: db_schema.ResolvedSchema,
    constraints: list[tuple[str, int, str]],
    headings: dict[str, str],
) -> tuple[list[GeneratedFile], list[GeneratedFile]]:
    """(model files, other backend files) — the first backend file is the
    DbContext, which the wiring context calls the routes file."""
    snapshot = db_schema.snapshot(schema)
    class_names = {t.sql_name: t.class_name for t in schema.tables}
    models = [model_file(t, snapshot, headings[t.sql_name]) for t in schema.tables]
    backend = [
        db_context_file(schema, snapshot),
        *[controller_file(t, snapshot, class_names) for t in schema.tables],
        *support_files(constraints),
    ]
    return models, backend
