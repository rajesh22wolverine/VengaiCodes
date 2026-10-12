"""The deterministic (no-AI) Laravel backend, checked without PHP: the app's
layout, the model's FIELDS, the Laravel migrations the schema changes
become, and the names PHP would not accept. That the app installs,
migrates and serves is test_laravel_e2e.py's job.
"""

import json
import re

import generated_backend_e2e as e2e
import pytest
from test_deterministic_codegen import (
    REACT_GIN_STACK,
    REACT_LARAVEL_STACK,
    VUE_LARAVEL_STACK,
    FakeProject,
    _by_path,
)
from test_deterministic_migrations_e2e import SHOP, evolved
from test_deterministic_migrations_e2e import FakeProject as ShopProject
from test_gin_codegen import RICH_TABLES
from test_laravel_e2e import LARAVEL_AWKWARD_TABLES

from app.ai import codegen_deterministic as dc
from app.ai import codegen_laravel, migrations_gen, migrations_laravel
from app.ai.codegen_shared import validate_generated_content

MIGRATIONS = "backend/database/migrations/"
_NOWDOC = re.compile(r"<<<'(SQL_*)'\n(.*?)\n\1\);", re.S)


def _migrations(data: dict) -> dict[str, str]:
    return {p: c for p, c in _by_path(data).items() if p.startswith(MIGRATIONS)}


def _up_and_down(migration: str) -> tuple[str, str]:
    """The SQL of a migration's up() and down()."""
    found = _NOWDOC.findall(migration)
    assert len(found) == 2, migration
    return found[0][1], found[1][1]


def _sql_sections(sql_file: str) -> tuple[str, str]:
    """The statements of a shared SQL migration file (Gin's): up, down."""
    up, down = sql_file.split("-- migrate:down\n")
    up = up.split("-- migrate:up\n")[1]
    return up.strip(), down.strip()


def test_laravel_layout_and_wiring():
    data = dc.build_deterministic_codegen_data(FakeProject(), VUE_LARAVEL_STACK)
    assert data["validation_warnings"] == []
    files = _by_path(data)
    for path in (
        "backend/composer.json",
        "backend/.env",
        "backend/artisan",
        "backend/bootstrap/app.php",
        "backend/bootstrap/cache/.gitignore",
        "backend/config/database.php",
        "backend/config/cors.php",
        "backend/public/index.php",
        "backend/routes/api.php",
        "backend/routes/console.php",
        "backend/storage/framework/cache/data/.gitignore",
        "backend/storage/framework/views/.gitignore",
        "backend/storage/logs/.gitignore",
        "backend/app/Models/Book.php",
        "backend/app/Http/Controllers/Controller.php",
        "backend/app/Http/Controllers/BookController.php",
        "backend/app/Support/ApiError.php",
        "backend/app/Support/RequestFields.php",
        "backend/app/Support/DatabaseErrors.php",
        MIGRATIONS + "2024_01_01_000001_initial_schema.php",
    ):
        assert path in files, path
    model = files["backend/app/Models/Book.php"]
    assert "namespace App\\Models;\n" in model
    assert "class Book extends Model\n{\n    protected $table = 'books';\n" in model
    assert "    protected $dateFormat = 'Y-m-d H:i:s.u';\n" in model
    # Undeclared fields keep the by-name inference.
    assert (
        "        'price' => ['kind' => 'float', 'null' => true, 'default' => false],\n"
        in model
    )
    assert "'is_available' => ['kind' => 'boolean', " in model
    assert "VENGAI:CUSTOM:book_model:start" in model
    controller = files["backend/app/Http/Controllers/BookController.php"]
    assert "class BookController extends Controller\n{\n" in controller
    assert "    private const LABEL = 'Book';\n" in controller
    # Models are always written in full, never through an import.
    assert (
        "RequestFields::rows(\\App\\Models\\Book::query()->orderBy('id')->get())"
        in (controller)
    )
    assert "RequestFields::fill($record, $this->body($request), creating: true);" in (
        controller
    )
    assert "VENGAI:CUSTOM:book_routes:start" in controller
    routes = files["backend/routes/api.php"]
    assert (
        "Route::get('books', [\\App\\Http\\Controllers\\BookController::class, 'index']);\n"
        "Route::post('books', [\\App\\Http\\Controllers\\BookController::class, 'store']);\n"
        "Route::get('books/{id}', [\\App\\Http\\Controllers\\BookController::class, 'show']);\n"
        "Route::put('books/{id}', [\\App\\Http\\Controllers\\BookController::class, 'update']);\n"
        "Route::delete('books/{id}', [\\App\\Http\\Controllers\\BookController::class, 'destroy']);\n"
        in routes
    )
    assert "VENGAI:CUSTOM:extra_routes:start" in routes
    app = files["backend/bootstrap/app.php"]
    assert "api: __DIR__.'/../routes/api.php'," in app
    assert (
        "Route::get('/', fn () => response()->json(['message' => "
        "'Library Manager API is running']));" in app
    )
    composer = json.loads(files["backend/composer.json"])
    assert composer["require"] == {"php": "^8.3", "laravel/framework": "^13.0"}
    assert composer["autoload"] == {"psr-4": {"App\\": "app/"}}
    assert (
        "env('DATABASE_PATH', database_path('database.sqlite'))"
        in (files["backend/config/database.php"])
    )
    assert "'foreign_key_constraints' => true," in files["backend/config/database.php"]
    readme = files["README_SETUP.md"]
    assert "php artisan migrate" in readme and "migrate:rollback --step=1" in readme
    info = migrations_gen.public_migration_info(data["migrations"])
    assert (
        info["tool"] == "laravel" and "php artisan migrate:rollback" in info["run_hint"]
    )


def test_laravel_initial_migration_runs_the_shared_sqlite_statements():
    """The SQL is the statements the Go, Rust and C# backends run (one
    renderer, already exercised against real databases), inside a
    migration that switches foreign keys off around its own transaction."""
    data = dc.build_deterministic_codegen_data(ShopProject(SHOP), VUE_LARAVEL_STACK)
    assert data["validation_warnings"] == []
    migration = _migrations(data)[MIGRATIONS + "2024_01_01_000001_initial_schema.php"]
    assert "return new class extends Migration\n{\n" in migration
    assert "    public $withinTransaction = false;\n" in migration
    assert (
        "        Schema::disableForeignKeyConstraints();\n"
        "        try {\n"
        "            DB::transaction(fn () => DB::unprepared($sql));\n"
        "        } finally {\n"
        "            Schema::enableForeignKeyConstraints();\n"
        "        }\n" in migration
    )
    gin = dc.build_deterministic_codegen_data(ShopProject(SHOP), REACT_GIN_STACK)
    sql_file = next(
        c
        for p, c in _by_path(gin).items()
        if p.startswith("backend/migrations/0001_") and p.endswith(".sql")
    )
    assert _up_and_down(migration) == _sql_sections(sql_file)


def test_laravel_later_migrations_change_the_schema_in_place():
    first = dc.build_deterministic_codegen_data(ShopProject(SHOP), VUE_LARAVEL_STACK)
    second = dc.build_deterministic_codegen_data(
        ShopProject(evolved(SHOP), first), VUE_LARAVEL_STACK
    )
    added = set(_migrations(second)) - set(_migrations(first))
    assert added == {MIGRATIONS + "2024_01_01_000002_create_reviews_and_more.php"}
    for path, content in _migrations(first).items():
        assert _migrations(second)[path] == content, "an earlier revision was rewritten"
    up, down = _up_and_down(_migrations(second)[added.pop()])
    assert up.startswith('CREATE TABLE "reviews" (')
    # customers.name becomes required: rebuilt, with the default where it was empty.
    assert "COALESCE(\"name\", 'anon')" in up
    assert 'ALTER TABLE "_vc_new_products" RENAME TO "products";' in up
    assert 'CREATE INDEX "ix_products_title" ON "products" ("title");' in up
    assert down.startswith('DROP TABLE "reviews";')

    dropped = evolved(SHOP)
    dropped[3]["key_fields"].remove("stock_count")
    third = dc.build_deterministic_codegen_data(
        ShopProject(dropped, second),
        VUE_LARAVEL_STACK,
        allow_destructive_migration=True,
    )
    migration = _migrations(third)[
        MIGRATIONS + "2024_01_01_000003_drop_products_stock_count.php"
    ]
    assert (
        "// Permanently changes existing data (confirmed when it was generated):\n"
        in (migration)
    )
    up, down = _up_and_down(migration)
    assert '"stock_count"' not in up.split("SELECT")[0] and '"stock_count"' in down
    for content in _migrations(third).values():
        assert validate_generated_content("php", content, "x.php") is None


def test_laravel_model_fields_cover_every_kind_of_column():
    files = _by_path(
        dc.build_deterministic_codegen_data(
            FakeProject(tables=RICH_TABLES), REACT_LARAVEL_STACK
        )
    )
    model = files["backend/app/Models/Book.php"]
    for line in (
        "        'title' => ['kind' => 'string', 'null' => false, 'default' => false, 'limit' => 255],",
        "        'author_id' => ['kind' => 'integer', 'null' => true, 'default' => false, "
        "'references' => ['model' => \\App\\Models\\Author::class, 'column' => 'id', "
        "'label' => 'Author']],",
        "        'price' => ['kind' => 'decimal', 'null' => true, 'default' => true],",
        "        'is_available' => ['kind' => 'boolean', 'null' => false, 'default' => true],",
        "        'published_at' => ['kind' => 'datetime', 'null' => true, 'default' => false],",
        "        'released_on' => ['kind' => 'date', 'null' => true, 'default' => false],",
        "        'meta' => ['kind' => 'json', 'null' => true, 'default' => false],",
        "        'notes' => ['kind' => 'string', 'null' => true, 'default' => false],",
    ):
        assert line in model, line
    assert "    public const FIELDS = [];\n" in files["backend/app/Models/Marker.php"]
    author = files["backend/app/Http/Controllers/AuthorController.php"]
    assert (
        "RESTRICT_MESSAGE = 'Can\\'t delete this record: Book still refer to it.';"
        in author
    )
    errors = files["backend/app/Support/DatabaseErrors.php"]
    assert "        ['books.title, books.author_id', 409, " in errors
    assert "        ['ck_books_pages_positive', 422, " in errors
    fields = files["backend/app/Support/RequestFields.php"]
    assert "    public const DECIMAL_DIGITS = 12;\n" in fields
    assert "    public const DECIMAL_PLACES = 2;\n" in fields


@pytest.mark.parametrize(
    "tables,message",
    [
        (
            [{"name": "self", "key_fields": ["title"]}],
            'The table "self" would produce a class named Self, a name PHP keeps',
        ),
        (
            [{"name": "parent", "key_fields": ["title"]}],
            "a class named Parent, a name PHP keeps",
        ),
        (
            [
                {"name": "a b", "key_fields": ["title"]},
                {"name": "ab", "key_fields": ["title"]},
            ],
            'The table "ab" would produce a class named Ab, which PHP can\'t tell apart '
            'from AB (the table "a b")',
        ),
        (
            [{"name": "model", "key_fields": ["title"]}],
            "Model",
        ),
    ],
    ids=["self", "parent", "case", "framework-type"],
)
def test_laravel_refuses_class_names_php_would_not_accept(tables, message):
    with pytest.raises(
        (dc.DeterministicCodegenError, ValueError), match=re.escape(message)
    ):
        dc.build_deterministic_codegen_data(
            FakeProject(tables=tables), REACT_LARAVEL_STACK
        )


def test_laravel_user_text_is_escaped_and_cant_trip_the_generated_file_check():
    name = "TODO $items 'x' \\ ?> {id}"
    tables = [
        {
            "name": name,
            "purpose": "TODO ?> (later",
            "key_fields": ["title", "parent_id"],
            "foreign_keys": [{"field": "parent_id", "references_table": name}],
            "checks": [{"name": "no todo", "expression": "title <> 'TODO'"}],
        }
    ]
    data = dc.build_deterministic_codegen_data(
        FakeProject(tables=tables), VUE_LARAVEL_STACK
    )
    assert data["validation_warnings"] == []
    files = _by_path(data)
    # Single quotes: $items is never interpolated; "TODO" is split in two.
    label = "'TO'.'DO $items \\'x\\' \\\\ ?> {id}'"
    model = next(c for p, c in files.items() if p.startswith("backend/app/Models/"))
    # ?> would end PHP even inside a // comment.
    assert model.startswith(
        "<?php\n\n// to-do $items 'x' \\ ? > {id}: to-do ? > (later\n"
    )
    assert f"'label' => {label}]" in model
    controller = next(
        c
        for p, c in files.items()
        if p.startswith("backend/app/Http/Controllers/")
        and not p.endswith("/Controller.php")
    )
    assert f"    private const LABEL = {label};\n" in controller
    migration = next(iter(_migrations(data).values()))
    assert "\"title\" <> 'TO' || 'DO'" in migration
    assert "TODO" not in "".join(
        c for p, c in files.items() if p.startswith("backend/")
    )


def test_php_strings_and_migration_names():
    assert codegen_laravel.php_str("it's \\ $x {y}") == "'it\\'s \\\\ $x {y}'"
    assert codegen_laravel.php_str("a TODO b") == "'a TO'.'DO b'"
    assert migrations_laravel.comment("a ?> b\nc\x00 TODO") == "a ? > b c to-do"
    assert migrations_laravel.filename("0001", "create_books") == (
        MIGRATIONS + "2024_01_01_000001_initial_schema.php"
    )
    assert migrations_laravel.filename("0012", "add_books_genre") == (
        MIGRATIONS + "2024_01_01_000012_add_books_genre.php"
    )


def test_laravel_nowdoc_marker_never_ends_early():
    """A line of SQL (a multi-line text default, say) that starts with the
    closing marker would end the nowdoc; a longer marker is chosen."""
    lines = migrations_laravel._nowdoc(["SELECT 'a", "SQL);", "  SQL_ x'"])
    assert lines[0] == "        $this->runStatements(<<<'SQL__'"
    assert lines[-1] == "SQL__);"
    assert migrations_laravel._nowdoc(["SELECT 'SQLite'"])[-1] == "SQL);"


def test_laravel_keeps_its_own_migration_history():
    """Laravel migrations are not the SQL files the Rust, Go and C# backends
    share, so a project that moves to Laravel starts at 0001."""
    first = dc.build_deterministic_codegen_data(FakeProject(), REACT_GIN_STACK)
    second = dc.build_deterministic_codegen_data(
        FakeProject(codegen_data=first), REACT_LARAVEL_STACK
    )
    assert second["migrations"]["tool"] == "laravel"
    assert [r["id"] for r in second["migrations"]["revisions"]] == ["0001"]
    assert list(_migrations(second)) == [
        MIGRATIONS + "2024_01_01_000001_initial_schema.php"
    ]
    assert not any(p.startswith("backend/migrations/") for p in _by_path(second))


def test_laravel_survives_tables_and_fields_named_like_its_own_code():
    """Locally: every file parses. That the app runs is test_laravel_e2e.py's
    job, with real PHP."""
    tables = e2e.awkward_tables("laravel", LARAVEL_AWKWARD_TABLES)
    names = [t["name"] for t in tables]
    assert len(names) == len(e2e.AWKWARD_TABLES) + len(LARAVEL_AWKWARD_TABLES), names
    data = dc.build_deterministic_codegen_data(
        FakeProject(tables=tables), REACT_LARAVEL_STACK
    )
    assert data["validation_warnings"] == []
    files = _by_path(data)
    assert (
        "class Controller extends Model" in files["backend/app/Models/Controller.php"]
    )
    assert (
        "class ControllerController extends Controller"
        in files["backend/app/Http/Controllers/ControllerController.php"]
    )
    assert "class ApiError extends Model" in files["backend/app/Models/ApiError.php"]
