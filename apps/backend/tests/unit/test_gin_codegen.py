"""The deterministic (no-AI) Gin backend, checked without a Go toolchain:
layout and wiring, the names and file names Go's build rules would trip
over, user text in Go literals, and — for every generated .go file — the
things the Go compiler refuses that a grammar check can't see (an import
that isn't used, a package used without its import). The real compiler,
gofmt, go vet and a running server are test_gin_e2e.py's job.
"""

import re

import pytest
from test_deterministic_codegen import (
    REACT_ACTIX_STACK,
    REACT_GIN_STACK,
    VUE_GIN_STACK,
    FakeProject,
    _by_path,
)

from app.ai import codegen_deterministic as dc
from app.ai import codegen_gin, migrations_gen, migrations_sqlite

# Every type, a foreign key of each ON DELETE kind, a self-reference, a
# table with no fields of its own, a unique column, a unique index, a check.
RICH_TABLES = [
    {
        "name": "Author",
        "purpose": "Who wrote it",
        "key_fields": ["name", "code"],
        "field_specs": [
            {"name": "name", "type": "string", "nullable": False},
            {"name": "code", "type": "string", "nullable": False, "unique": True},
        ],
    },
    {
        "name": "Book",
        "key_fields": [
            "title",
            "author_id",
            "editor_id",
            "price",
            "is_available",
            "published_at",
            "released_on",
            "meta",
            "pages",
            "rating",
            "notes",
        ],
        "field_specs": [
            {"name": "title", "type": "string", "nullable": False},
            {"name": "price", "type": "decimal", "default": 9.5},
            {
                "name": "is_available",
                "type": "boolean",
                "nullable": False,
                "default": True,
            },
            {"name": "published_at", "type": "datetime"},
            {"name": "released_on", "type": "date"},
            {"name": "meta", "type": "json"},
            {"name": "pages", "type": "integer", "nullable": False, "default": 1},
            {"name": "rating", "type": "float"},
            {"name": "notes", "type": "text"},
        ],
        "foreign_keys": [
            {
                "field": "author_id",
                "references_table": "Author",
                "on_delete": "restrict",
            },
            {
                "field": "editor_id",
                "references_table": "Author",
                "on_delete": "set_null",
            },
        ],
        "checks": [{"name": "pages positive", "expression": "pages > 0"}],
        "indexes": [{"fields": ["title", "author_id"], "unique": True}],
    },
    {
        "name": "Category",
        "key_fields": ["label", "parent_id"],
        "foreign_keys": [
            {
                "field": "parent_id",
                "references_table": "Category",
                "on_delete": "cascade",
            }
        ],
    },
    {"name": "Marker", "key_fields": []},
]

_KNOWN_PACKAGES = {
    "apierr",
    "bytes",
    "context",
    "embed",
    "errors",
    "fields",
    "fmt",
    "gin",
    "handlers",
    "http",
    "json",
    "log",
    "migrations",
    "models",
    "os",
    "sort",
    "sql",
    "strconv",
    "strings",
    "time",
    "unicode",
    "utf8",
}
_IMPORTS = re.compile(r"^import \(\n(.*?)^\)\n", re.S | re.M)


def _go_files(data: dict) -> dict[str, str]:
    return {p: c for p, c in _by_path(data).items() if p.endswith(".go")}


def _code_only(source: str) -> str:
    """Go source with comments removed and string contents blanked."""
    out = []
    i, n = 0, len(source)
    while i < n:
        ch = source[i]
        if source.startswith("//", i):
            while i < n and source[i] != "\n":
                i += 1
        elif ch == "`":
            i = source.index("`", i + 1) + 1
            out.append("``")
        elif ch in "\"'":
            j = i + 1
            while source[j] != ch:
                j += 2 if source[j] == "\\" else 1
            i = j + 1
            out.append(ch + ch)
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _go_problems(path: str, source: str) -> list[str]:
    problems = []
    for number, line in enumerate(source.split("\n"), 1):
        if line.startswith(" "):
            problems.append(f"{path}:{number}: indented with spaces, not tabs")
        if line != line.rstrip():
            problems.append(f"{path}:{number}: trailing whitespace")
    if not source.endswith("\n") or source.endswith("\n\n"):
        problems.append(f"{path}: doesn't end with exactly one newline")
    block = _IMPORTS.search(source)
    imported: dict[str, str] = {}
    body = source
    if block:
        body = source[block.end() :]
        for line in block.group(1).splitlines():
            if line.strip():
                alias, _, quoted = line.strip().rpartition(" ")
                package = quoted.strip('"')
                imported[alias or package.rsplit("/", 1)[-1]] = package
    code = _code_only(body)
    for name, package in imported.items():
        if name != "_" and not re.search(rf"(?<![\w.]){name}\.", code):
            problems.append(f"{path}: imports {package} but never uses it")
    for name in sorted(_KNOWN_PACKAGES - set(imported)):
        if re.search(rf"(?<![\w.]){name}\.[A-Za-z]", code):
            problems.append(f"{path}: uses {name}. without importing it")
    return problems


@pytest.mark.parametrize(
    "tables", [None, RICH_TABLES], ids=["inferred-types", "every-shape"]
)
def test_gin_files_have_only_the_imports_they_use_and_tab_indentation(tables):
    project = FakeProject() if tables is None else FakeProject(tables=tables)
    data = dc.build_deterministic_codegen_data(project, REACT_GIN_STACK)
    assert data["validation_warnings"] == []
    files = _go_files(data)
    assert len(files) >= 9
    problems = [p for path, src in files.items() for p in _go_problems(path, src)]
    assert problems == []


def test_the_static_go_check_catches_what_it_is_for():
    source = (
        'package x\n\nimport (\n\t"fmt"\n\t"strings"\n)\n\n'
        '// strings.Join is only mentioned here, and "fmt." there\n'
        'func f() string {\n\treturn os.Getenv("strings.x")\n}\n'
    )
    assert _go_problems("x.go", source) == [
        "x.go: imports fmt but never uses it",
        "x.go: imports strings but never uses it",
        "x.go: uses os. without importing it",
    ]


def test_gin_layout_and_wiring():
    data = dc.build_deterministic_codegen_data(FakeProject(), VUE_GIN_STACK)
    files = _by_path(data)
    for path in (
        "backend/go.mod",
        "backend/main.go",
        "backend/apierr/apierr.go",
        "backend/fields/fields.go",
        "backend/models/models.go",
        "backend/models/book_model.go",
        "backend/models/member_model.go",
        "backend/handlers/routes.go",
        "backend/handlers/book_handlers.go",
        "backend/migrations/migrate.go",
        "backend/migrations/0001_initial.sql",
    ):
        assert path in files, path
    model = files["backend/models/book_model.go"]
    assert '\t"librarymanager/fields"\n' in model
    assert "type Book struct {" in model and "type BookInput struct {" in model
    # Undeclared fields keep the by-name inference; gofmt's column alignment.
    assert '\tPrice       *float64          `json:"price"`\n' in model
    assert '\tIsAvailable *bool             `json:"is_available"`\n' in model
    assert '\tPublishedAt *fields.Timestamp `json:"published_at"`\n' in model
    assert '\tCreatedAt   fields.Timestamp  `json:"created_at"`\n' in model
    assert "\tPublishedAt fields.DateTime\n" in model
    assert '\tfields.MaxChars(&in.Title, 255, "title", &problems)\n' in model
    assert 'const bookFindSQL = `SELECT "id", "title",' in model
    # One Scan destination per selected column.
    select = re.search(r"const bookListSQL = `SELECT (.*?) FROM", model).group(1)
    scan = re.search(r"row\.Scan\(\n(.*?)\n\t\)", model, re.S).group(1)
    assert len(select.split(", ")) == len(scan.splitlines()) == 9
    assert "VENGAI:CUSTOM:book_model:start" in model
    handlers = files["backend/handlers/book_handlers.go"]
    assert 'api.PUT("/books/:id", func(c *gin.Context) {' in handlers
    assert "VENGAI:CUSTOM:book_routes:start" in handlers
    routes = files["backend/handlers/routes.go"]
    assert "\tregisterBook(api, db)\n\tregisterMember(api, db)\n" in routes
    assert 'c.JSON(problem.Status, gin.H{"error": problem.Detail})' in routes
    assert "c.ShouldBindJSON(&body)" in routes
    main = files["backend/main.go"]
    assert "migrations.Run(ctx, db)" in main and 'os.Args[1] == "revert"' in main
    assert '_ "modernc.org/sqlite"' in main and "_pragma=foreign_keys(1)" in main
    assert "router.Use(allowAnyOrigin)" in main
    assert files["backend/go.mod"] == (
        "module librarymanager\n\ngo 1.21\n\nrequire (\n"
        "\tgithub.com/gin-gonic/gin v1.10.1\n\tmodernc.org/sqlite v1.34.5\n)\n"
    )
    assert (
        "//go:embed *.sql\nvar files embed.FS\n"
        in files["backend/migrations/migrate.go"]
    )
    assert (
        "`go run . revert` undoes the newest"
        in files["backend/migrations/0001_initial.sql"]
    )
    readme = files["README_SETUP.md"]
    assert "go mod tidy" in readme and "go run . revert" in readme
    info = migrations_gen.public_migration_info(data["migrations"])
    assert info["tool"] == "sqlite-go" and "go run . revert" in info["run_hint"]


def test_gin_models_skip_what_a_table_doesnt_need():
    files = _by_path(
        dc.build_deterministic_codegen_data(
            FakeProject(tables=RICH_TABLES), REACT_GIN_STACK
        )
    )
    marker = files["backend/models/marker_model.go"]
    assert "type MarkerInput struct{}\n" in marker
    assert "checkReferences" not in marker
    book = files["backend/models/book_model.go"]
    assert book.count("in.checkReferences(ctx, s.DB)") == 2, "create and update"
    assert (
        'fields.Exists(ctx, db, `SELECT 1 FROM "authors" WHERE "id" = ?`, &in.AuthorId, '
        '"author_id: no row in Author has id")' in book
    )
    author = files["backend/models/author_model.go"]
    assert (
        'const authorRestrictMessage = "Can\'t delete this record: Book still refer to it."'
        in author
    )
    apierr = files["backend/apierr/apierr.go"]
    assert '\t{"books.title, books.author_id", 409, ' in apierr
    assert '\t{"ck_books_pages_positive", 422, ' in apierr


# Go builds x_test.go as a test and x_linux.go / x_amd64.go on that platform
# only — a table must never produce such a file name.
@pytest.mark.parametrize(
    "name", ["load test", "order linux", "report windows amd64", "page js", "wasm"]
)
def test_gin_file_names_never_carry_a_go_build_suffix(name):
    files = _go_files(
        dc.build_deterministic_codegen_data(
            FakeProject(tables=[{"name": name, "key_fields": ["title"]}]),
            REACT_GIN_STACK,
        )
    )
    slug = name.replace(" ", "_")
    assert f"backend/models/{slug}_model.go" in files
    assert f"backend/handlers/{slug}_handlers.go" in files
    reserved = re.compile(
        r"_(test|aix|android|darwin|dragonfly|freebsd|illumos|ios|js|linux|netbsd|openbsd|plan9|"
        r"solaris|wasip1|windows|386|amd64|arm|arm64|loong64|mips|mips64|mips64le|mipsle|ppc64|"
        r"ppc64le|riscv64|s390x|wasm)\.go$"
    )
    assert [path for path in files if reserved.search(path)] == []


@pytest.mark.parametrize(
    "tables,message",
    [
        (
            [{"name": "thing", "key_fields": ["a_1", "a1"]}],
            'The fields "a_1" and "a1" in "thing" would both be the Go struct field A1',
        ),
        (
            [{"name": "thing", "key_fields": ["i_d"]}],
            'The field "i_d" in "thing" would be the Go struct field ID',
        ),
        (
            [
                {"name": "book", "key_fields": ["title"]},
                {"name": "book store", "key_fields": ["title"]},
            ],
            "would both produce a class named BookStore",
        ),
    ],
    ids=["same-field", "fixed-field", "type-suffix"],
)
def test_gin_refuses_names_that_would_collide_in_go(tables, message):
    with pytest.raises(dc.DeterministicCodegenError, match=re.escape(message)):
        dc.build_deterministic_codegen_data(FakeProject(tables=tables), REACT_GIN_STACK)


def test_gin_user_text_is_escaped_and_cant_trip_the_generated_file_check():
    name = 'TODO `items` "x" \\ %d'
    tables = [
        {
            "name": name,
            "purpose": "TODO (later﻿",
            "key_fields": ["title", "parent_id"],
            "foreign_keys": [{"field": "parent_id", "references_table": name}],
        }
    ]
    data = dc.build_deterministic_codegen_data(
        FakeProject(tables=tables), VUE_GIN_STACK
    )
    assert data["validation_warnings"] == []
    files = _go_files(data)
    assert [p for path, src in files.items() for p in _go_problems(path, src)] == []
    model = files["backend/models/todo_items_x_d_model.go"]
    assert 'const todoItemsXDLabel = "TOD\\u004f `items` \\"x\\" \\\\ %d"\n' in model
    assert model.startswith('// to-do `items` "x" \\ %d: to-do (later\n')
    assert '"parent_id: no row in TOD\\u004f `items` \\"x\\" \\\\ %d has id")' in model
    assert "TODO" not in "".join(files.values())


def test_go_string_literals():
    assert codegen_gin.go_str('a"b\\c\n\t') == '"a\\"b\\\\c\\n\\t"'
    assert codegen_gin.go_str("\x00﻿\U0001f600é") == '"\\u0000\\ufeff😀é"'
    assert codegen_gin.go_str("\ud800") == '"\\ufffd"'
    assert codegen_gin.go_sql('SELECT "a"') == '`SELECT "a"`'
    assert codegen_gin.go_sql("a`b") == '"a`b"'


@pytest.mark.parametrize(
    "project,module",
    [
        ("Library Manager", "librarymanager"),
        ("Time", "timeapp"),
        ("3D Notes", "app3dnotes"),
        ("", "vengaicodeapp"),
        ("Café-Ünïcode!", "cafncode"),
    ],
)
def test_gin_module_path_is_always_importable(project, module):
    assert codegen_gin.module_path(project) == module
    assert f'"{module}/handlers"' in codegen_gin.main_go(project)
    assert codegen_gin.go_mod(project).startswith(f"module {module}\n")


def test_gin_shares_its_migration_history_with_the_rust_backends():
    """Same SQL files, same `_migrations` table: a project that moves from
    Actix to Gin keeps its history (and its app.db) instead of starting a
    second 0001 the database would think it had already run."""
    first = dc.build_deterministic_codegen_data(FakeProject(), REACT_ACTIX_STACK)
    assert first["migrations"]["tool"] == "sqlite-rs"
    initial = _by_path(first)["backend/migrations/0001_initial.sql"]

    tables = [
        dict(FakeProject().architecture_data["architecture"]["database_tables"][0]),
        FakeProject().architecture_data["architecture"]["database_tables"][1],
    ]
    tables[0] = dict(tables[0], key_fields=tables[0]["key_fields"] + ["genre"])
    second = dc.build_deterministic_codegen_data(
        FakeProject(tables=tables, codegen_data=first), REACT_GIN_STACK
    )
    files = _by_path(second)
    assert second["migrations"]["tool"] == "sqlite-go"
    assert [r["id"] for r in second["migrations"]["revisions"]] == ["0001", "0002"]
    assert files["backend/migrations/0001_initial.sql"] == initial, "carried over"
    added = files["backend/migrations/0002_add_books_genre.sql"]
    assert 'ALTER TABLE "_vc_new_books" RENAME TO "books";' in added
    assert "`go run . revert`" in added and "cargo" not in added
    assert "backend/src/migrate.rs" not in files
    assert "backend/migrations/migrate.go" in files

    # Both runners keep the same bookkeeping table.
    ddl = re.compile(r"CREATE TABLE IF NOT EXISTS _migrations \([^\"]*?\)\)?", re.S)
    rust = " ".join(
        ddl.search(migrations_sqlite.runner_rs([])).group(0).replace("\\", "").split()
    )
    go = " ".join(ddl.search(codegen_gin.migrate_go()).group(0).split())
    assert rust == go
    for statement in (
        "INSERT INTO _migrations (version, name) VALUES (?, ?)",
        "DELETE FROM _migrations WHERE version = ? AND name = ?",
        "SELECT version FROM _migrations ORDER BY version",
    ):
        assert statement in migrations_sqlite.runner_rs([])
        assert statement in codegen_gin.migrate_go()
