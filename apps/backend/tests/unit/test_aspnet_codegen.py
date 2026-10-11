"""The deterministic (no-AI) ASP.NET Core backend, checked without a .NET
SDK: layout and wiring, the names C# would resolve to the wrong thing, user
text in C# literals, and the migration history it shares with the other
SQLite backends. The real compiler and a running server are
test_aspnet_e2e.py's job.
"""

import re

import generated_backend_e2e as e2e
import pytest
from test_deterministic_codegen import (
    REACT_ASPNET_STACK,
    REACT_GIN_STACK,
    VUE_ASPNET_STACK,
    FakeProject,
    _by_path,
)
from test_gin_codegen import RICH_TABLES

from app.ai import codegen_aspnet, codegen_gin, migrations_gen
from app.ai import codegen_deterministic as dc


def _cs_files(data: dict) -> dict[str, str]:
    return {p: c for p, c in _by_path(data).items() if p.endswith(".cs")}


def test_aspnet_layout_and_wiring():
    data = dc.build_deterministic_codegen_data(FakeProject(), VUE_ASPNET_STACK)
    assert data["validation_warnings"] == []
    files = _by_path(data)
    for path in (
        "backend/GeneratedApp.csproj",
        "backend/appsettings.json",
        "backend/Program.cs",
        "backend/Data/AppDbContext.cs",
        "backend/Data/Migrator.cs",
        "backend/Models/Book.cs",
        "backend/Models/Member.cs",
        "backend/Controllers/BookController.cs",
        "backend/Support/ApiException.cs",
        "backend/Support/RequestBody.cs",
        "backend/Support/Stored.cs",
        "backend/migrations/0001_initial.sql",
    ):
        assert path in files, path
    model = files["backend/Models/Book.cs"]
    assert "namespace GeneratedApp.Models;" in model and "public class Book\n" in model
    assert (
        '    [JsonPropertyName("title")]\n    public string? Title { get; set; }\n'
        in model
    )
    # Undeclared fields keep the by-name inference.
    assert "    public double? Price { get; set; }\n" in model
    assert "    public bool? IsAvailable { get; set; }\n" in model
    assert "    public DateTime? PublishedAt { get; set; }\n" in model
    assert "    public DateTime CreatedAt { get; set; }\n" in model
    assert "VENGAI:CUSTOM:book_model:start" in model
    controller = files["backend/Controllers/BookController.cs"]
    assert (
        '[Microsoft.AspNetCore.Mvc.ApiController]\n[Route("api/books")]' in controller
    )
    assert "public class BookController : ControllerBase" in controller
    assert 'var inPrice = body.ReadNumber("price");' in controller
    assert 'body.MaxChars(inTitle, 255, "title");' in controller
    assert "VENGAI:CUSTOM:book_routes:start" in controller
    # Entities are always written Models.<Class>, never imported.
    assert "Task<ActionResult<List<Models.Book>>> List()" in controller
    for path, content in _cs_files(data).items():
        assert "using GeneratedApp.Models;" not in content, path
    context = files["backend/Data/AppDbContext.cs"]
    assert 'entity.ToTable("books");' in context
    assert (
        'entity.Property(row => row.IsAvailable).HasColumnName("is_available");'
        in context
    )
    assert "HaveConversion<StoredDateTimeConverter>()" in context
    program = files["backend/Program.cs"]
    assert "Migrator.Run(databasePath);" in program and '== "revert"' in program
    assert "ForeignKeys = true" in program and "app.UseCors();" in program
    csproj = files["backend/GeneratedApp.csproj"]
    assert "<TargetFramework>net10.0</TargetFramework>" in csproj
    assert (
        '<EmbeddedResource Include="migrations/*.sql" LogicalName="migrations/%(Filename)%(Extension)" />'
        in csproj
    )
    assert (
        "`dotnet run -- revert` undoes the newest"
        in files["backend/migrations/0001_initial.sql"]
    )
    readme = files["README_SETUP.md"]
    assert "dotnet run -- revert" in readme and "net10.0" in readme
    info = migrations_gen.public_migration_info(data["migrations"])
    assert info["tool"] == "sqlite-cs" and "dotnet run -- revert" in info["run_hint"]


def test_aspnet_controller_covers_every_kind_of_column():
    files = _by_path(
        dc.build_deterministic_codegen_data(
            FakeProject(tables=RICH_TABLES), REACT_ASPNET_STACK
        )
    )
    model = files["backend/Models/Book.cs"]
    assert '    public string Title { get; set; } = "";\n' in model
    assert "    public long Pages { get; set; }\n" in model
    assert "    public DateOnly? ReleasedOn { get; set; }\n" in model
    assert (
        "    [JsonConverter(typeof(RawJsonConverter))]\n    public string? Meta { get; set; }\n"
        in model
    )
    controller = files["backend/Controllers/BookController.cs"]
    assert 'body.Required(inTitle, "title", creating);' in controller
    assert 'body.NotNull(inPages, "pages");' in controller
    # Set only when sent; on create, a field left out gets the column's default.
    assert (
        "        if (inPrice.Sent)\n        {\n            row.Price = inPrice.OrNull();\n        }\n"
        "        else if (creating)\n        {\n            row.Price = 9.5;\n        }\n"
        in controller
    )
    assert "row.IsAvailable = true;" in controller and "row.Pages = 1;" in controller
    assert "row.Title = inTitle.Value!;" in controller
    assert "row.Notes = inNotes.Value;" in controller
    assert (
        "!await _db.Set<Models.Author>().AnyAsync(parent => parent.Id == inAuthorId.Value))"
        in controller
    )
    assert (
        'throw ApiException.MissingParent("author_id: no row in Author has id", inAuthorId.Value);'
        in controller
    )
    author = files["backend/Controllers/AuthorController.cs"]
    assert (
        'private const string RestrictMessage = "Can\'t delete this record: Book still refer to it.";'
        in author
    )
    stored = files["backend/Support/Stored.cs"]
    assert '        ("books.title, books.author_id", 409, ' in stored
    assert '        ("ck_books_pages_positive", 422, ' in stored
    marker = files["backend/Controllers/MarkerController.cs"]
    assert (
        "        var body = await RequestBody.ReadAsync(Request);\n"
        "        body.ThrowIfInvalid();\n    }\n" in marker
    )


def test_aspnet_defaults_are_the_migrations_defaults():
    tables = [
        {
            "name": "Thing",
            "key_fields": ["label", "seen_at", "due", "started", "tags", "ratio", "n"],
            "field_specs": [
                {"name": "label", "type": "string", "default": 'a "b" \\'},
                {"name": "seen_at", "type": "datetime", "default": "now"},
                {"name": "due", "type": "date", "default": "today"},
                {"name": "started", "type": "date", "default": "2024-01-31"},
                {"name": "tags", "type": "json", "default": ["x", 1]},
                {"name": "ratio", "type": "float", "default": 2},
                {"name": "n", "type": "integer", "default": -7},
            ],
        }
    ]
    files = _by_path(
        dc.build_deterministic_codegen_data(
            FakeProject(tables=tables), REACT_ASPNET_STACK
        )
    )
    controller = files["backend/Controllers/ThingController.cs"]
    for line in (
        'row.Label = "a \\"b\\" \\\\";',
        "row.SeenAt = Stored.Now();",
        "row.Due = Stored.Today();",
        "row.Started = new DateOnly(2024, 1, 31);",
        'row.Tags = "[\\"x\\",1]";',
        "row.Ratio = 2.0;",
        "row.N = -7;",
    ):
        assert line in controller, line
    sql = files["backend/migrations/0001_initial.sql"]
    assert """DEFAULT '["x",1]'""" in sql and "DEFAULT -7" in sql


@pytest.mark.parametrize(
    "tables,message",
    [
        (
            [{"name": "thing", "key_fields": ["a_1", "a1"]}],
            'The fields "a_1" and "a1" in "thing" would both be the C# property A1',
        ),
        (
            [{"name": "thing", "key_fields": ["to_string"]}],
            "would hide a member every C# object has",
        ),
        (
            [{"name": "date only", "key_fields": ["title"]}],
            "would produce a class named DateOnly",
        ),
        (
            [{"name": "book controller", "key_fields": ["title"]}],
            "ASP.NET treats every class named …Controller as a controller",
        ),
    ],
    ids=["same-property", "object-member", "used-type", "controller"],
)
def test_aspnet_refuses_names_csharp_would_resolve_wrongly(tables, message):
    with pytest.raises(dc.DeterministicCodegenError, match=re.escape(message)):
        dc.build_deterministic_codegen_data(
            FakeProject(tables=tables), REACT_ASPNET_STACK
        )


def test_aspnet_user_text_is_escaped_and_cant_trip_the_generated_file_check():
    # A line separator in the middle: C# ends a line there, even in a string.
    name = "TODO {items}" + chr(0x2028) + '"x" \\ %d'
    tables = [
        {
            "name": name,
            "purpose": "TODO (later */",
            "key_fields": ["title", "parent_id"],
            "foreign_keys": [{"field": "parent_id", "references_table": name}],
        }
    ]
    data = dc.build_deterministic_codegen_data(
        FakeProject(tables=tables), VUE_ASPNET_STACK
    )
    assert data["validation_warnings"] == []
    files = _cs_files(data)
    controller = files["backend/Controllers/TodoItemsXDController.cs"]
    assert (
        'private const string Label = "TOD\\u004f {items}\\u2028\\"x\\" \\\\ %d";'
        in controller
    )
    assert (
        '"parent_id: no row in TOD\\u004f {items}\\u2028\\"x\\" \\\\ %d has id", inParentId.Value);'
        in controller
    )
    assert chr(0x2028) not in "".join(files.values())
    assert files["backend/Models/TodoItemsXD.cs"].startswith(
        '// to-do {items} "x" \\ %d: to-do (later */\n'
    )
    assert "TODO" not in "".join(files.values())


def test_csharp_string_literals():
    assert codegen_aspnet.cs_str('a"b\\c\n\t') == '"a\\"b\\\\c\\n\\t"'
    assert (
        codegen_aspnet.cs_str("\x00" + chr(0x2028) + "\U0001f600é")
        == '"\\u0000\\u2028😀é"'
    )
    assert codegen_aspnet.cs_str("\ud800") == '"\\ufffd"'


def test_aspnet_survives_tables_and_fields_named_like_its_own_code():
    """Locally: every file parses. That the result compiles is
    test_aspnet_e2e.py's job, with the real SDK."""
    tables = e2e.awkward_tables("aspnet_core")
    # "Type" would shadow System.Type, which the schema check already refuses.
    assert [t["name"] for t in tables] == [
        t["name"] for t in e2e.AWKWARD_TABLES if t["name"] != "Type"
    ]
    data = dc.build_deterministic_codegen_data(
        FakeProject(tables=tables), REACT_ASPNET_STACK
    )
    assert data["validation_warnings"] == []
    files = _by_path(data)
    # A property may share its type's name; the class is never imported.
    assert (
        "    public DateTime? DateTime { get; set; }\n"
        in files["backend/Models/Models.cs"]
    )
    assert (
        "public class ApiController : ControllerBase"
        in files["backend/Controllers/ApiController.cs"]
    )
    assert (
        'var inClass = body.ReadText("class");'
        in files["backend/Controllers/TableController.cs"]
    )


def test_aspnet_shares_its_migration_history_with_the_other_sqlite_backends():
    first = dc.build_deterministic_codegen_data(FakeProject(), REACT_GIN_STACK)
    initial = _by_path(first)["backend/migrations/0001_initial.sql"]
    tables = list(FakeProject().architecture_data["architecture"]["database_tables"])
    tables[0] = dict(tables[0], key_fields=tables[0]["key_fields"] + ["genre"])
    second = dc.build_deterministic_codegen_data(
        FakeProject(tables=tables, codegen_data=first), REACT_ASPNET_STACK
    )
    files = _by_path(second)
    assert second["migrations"]["tool"] == "sqlite-cs"
    assert [r["id"] for r in second["migrations"]["revisions"]] == ["0001", "0002"]
    assert files["backend/migrations/0001_initial.sql"] == initial, "carried over"
    assert (
        "`dotnet run -- revert`" in files["backend/migrations/0002_add_books_genre.sql"]
    )
    assert "backend/migrations/migrate.go" not in files
    assert "backend/Data/Migrator.cs" in files

    # The same bookkeeping table as the Go runner's.
    ddl = re.compile(r'CREATE TABLE IF NOT EXISTS _migrations \([^"]*\)')
    assert ddl.search(codegen_aspnet.migrator_cs()).group(0) == ddl.search(
        codegen_gin.migrate_go()
    ).group(0)
