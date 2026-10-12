"""The deterministic (no-AI) Rails backend, checked without Ruby: the app's
layout, the model's FIELDS, the Active Record migrations the schema changes
become, and the names Ruby and Active Record would not accept. That the app
boots, migrates and serves is test_rails_e2e.py's job.
"""

import re

import generated_backend_e2e as e2e
import pytest
from test_deterministic_codegen import (
    REACT_GIN_STACK,
    REACT_RAILS_STACK,
    VUE_RAILS_STACK,
    FakeProject,
    _by_path,
)
from test_deterministic_migrations_e2e import SHOP, evolved
from test_deterministic_migrations_e2e import FakeProject as ShopProject
from test_gin_codegen import RICH_TABLES

from app.ai import codegen_deterministic as dc
from app.ai import codegen_rails, migrations_gen, migrations_rails
from app.ai.codegen_shared import validate_generated_content

MIGRATIONS = "backend/db/migrate/"


def _migrations(data: dict) -> dict[str, str]:
    return {p: c for p, c in _by_path(data).items() if p.startswith(MIGRATIONS)}


def test_rails_layout_and_wiring():
    data = dc.build_deterministic_codegen_data(FakeProject(), VUE_RAILS_STACK)
    assert data["validation_warnings"] == []
    files = _by_path(data)
    for path in (
        "backend/Gemfile",
        "backend/Rakefile",
        "backend/config.ru",
        "backend/bin/rails",
        "backend/config/boot.rb",
        "backend/config/application.rb",
        "backend/config/environment.rb",
        "backend/config/environments/development.rb",
        "backend/config/database.yml",
        "backend/config/puma.rb",
        "backend/config/routes.rb",
        "backend/config/initializers/cors.rb",
        "backend/config/initializers/json_bodies.rb",
        "backend/config/initializers/stored_date_time.rb",
        "backend/app/models/application_record.rb",
        "backend/app/models/book.rb",
        "backend/app/controllers/application_controller.rb",
        "backend/app/controllers/books_controller.rb",
        "backend/app/lib/api_error.rb",
        "backend/app/lib/request_fields.rb",
        "backend/app/lib/database_errors.rb",
        "backend/db/migrate/20240101000001_initial_schema.rb",
    ):
        assert path in files, path
    model = files["backend/app/models/book.rb"]
    assert "class Book < ApplicationRecord\n  self.table_name = 'books'\n" in model
    # Undeclared fields keep the by-name inference.
    assert "    'price' => { kind: :float, null: true, default: false },\n" in model
    assert "'is_available' => { kind: :boolean, " in model
    assert (
        "    'title' => { kind: :string, null: true, default: false, limit: 255 },\n"
        in model
    )
    assert (
        "  attribute :published_at, :stored_datetime\n"
        "  attribute :created_at, :stored_datetime\n"
        "  attribute :updated_at, :stored_datetime\n" in model
    )
    assert "VENGAI:CUSTOM:book_model:start" in model
    controller = files["backend/app/controllers/books_controller.rb"]
    assert (
        "class BooksController < ApplicationController\n  LABEL = 'Book'\n"
        in controller
    )
    # Models are always written ::Book, never looked up through the controller.
    assert "render json: rows(::Book.order(:id))" in controller
    assert "RequestFields.fill(record, request_body, creating: true)" in controller
    assert "VENGAI:CUSTOM:book_routes:start" in controller
    routes = files["backend/config/routes.rb"]
    assert (
        "    resources :books, only: %i[index show create update destroy]\n"
        "    resources :members, only: %i[index show create update destroy]\n" in routes
    )
    assert "message = { message: 'Library Manager API is running' }.to_json" in routes
    gemfile = files["backend/Gemfile"]
    assert "gem 'rails', '~> 8.1.0'" in gemfile and "ruby '>= 3.2'" in gemfile
    assert 'ENV.fetch("DATABASE_PATH")' in files["backend/config/database.yml"]
    assert (
        "parameter_parsers.except(:json)"
        in files["backend/config/initializers/json_bodies.rb"]
    )
    readme = files["README_SETUP.md"]
    assert "bundle exec rails db:migrate" in readme and "db:rollback" in readme
    info = migrations_gen.public_migration_info(data["migrations"])
    assert info["tool"] == "rails" and "bin/rails db:rollback" in info["run_hint"]


def test_rails_initial_migration_is_the_active_record_dsl():
    data = dc.build_deterministic_codegen_data(ShopProject(SHOP), VUE_RAILS_STACK)
    assert data["validation_warnings"] == []
    migration = _migrations(data)[MIGRATIONS + "20240101000001_initial_schema.rb"]
    assert "class InitialSchema < ActiveRecord::Migration[8.1]\n" in migration
    assert "  disable_ddl_transaction!\n" in migration
    assert (
        "    connection.disable_referential_integrity { connection.transaction(&block) }\n"
        in migration
    )
    for line in (
        "      create_table :customers do |t|",
        "        t.string :email, limit: 255, null: false",
        "        t.boolean :is_active, default: true",
        # A JSON or date-time default is the exact text to store.
        """        t.json :profile, default: -> { '\\'{"tier":"basic"}\\'' }""",
        "        t.index [:email], name: 'uq_customers_email', unique: true",
        "        t.check_constraint '\"email\" LIKE \\'%@%\\'', name: 'ck_customers_email_has_at'",
        "        t.integer :customer_id, null: false",
        "        t.decimal :total, precision: 12, scale: 2, null: false, default: '0.00'",
        "        t.datetime :placed_at, precision: 6, default: -> { 'strftime(\\'%Y-%m-%d %H:%M:%f000\\', \\'now\\')' }",
        "        t.date :ship_date",
        "        t.index [:status, :placed_at], name: 'ix_orders_status_placed_at'",
        "        t.foreign_key :customers, column: :customer_id, primary_key: :id, "
        "on_delete: :cascade, name: 'fk_orders_customer_id'",
        "        t.foreign_key :coupons, column: :coupon_id, primary_key: :id, "
        "on_delete: :nullify, name: 'fk_orders_coupon_id'",
        "        t.foreign_key :products, column: :product_id, primary_key: :id, "
        "on_delete: :restrict, name: 'fk_order_items_product_id'",
        "        t.index [:order_id, :product_id], name: 'uq_order_items_order_id_product_id', unique: true",
        # Seed rows, in the stored form.
        '      execute \'INSERT INTO "customers" ("email", "name", "is_active") '
        "VALUES (\\'b@x.io\\', \\'Bob\\', 0)'",
        # Down: children before parents.
        "      drop_table :order_items\n      drop_table :products\n      drop_table :orders",
    ):
        assert line in migration, line
    # Every table's own timestamps default in the database too, so a row
    # inserted by hand is still valid.
    assert (
        migration.count(
            "t.datetime :created_at, precision: 6, null: false, default: ->"
        )
        == 7
    )


def test_rails_later_migrations_change_the_schema_in_place():
    first = dc.build_deterministic_codegen_data(ShopProject(SHOP), VUE_RAILS_STACK)
    second = dc.build_deterministic_codegen_data(
        ShopProject(evolved(SHOP), first), VUE_RAILS_STACK
    )
    added = set(_migrations(second)) - set(_migrations(first))
    assert added == {MIGRATIONS + "20240101000002_create_reviews_and_more_2.rb"}
    for path, content in _migrations(first).items():
        assert _migrations(second)[path] == content, "an earlier revision was rewritten"
    migration = _migrations(second)[added.pop()]
    assert "class CreateReviewsAndMore2 < ActiveRecord::Migration[8.1]" in migration
    up, down = migration.split("  def down\n")
    for line in (
        "      create_table :reviews do |t|",
        "      add_column :products, :is_featured, :boolean, null: false, default: false",
        # Rows that have it empty get the default before it becomes required.
        '      execute \'UPDATE "customers" SET "name" = \\\'anon\\\' WHERE "name" IS NULL\'\n'
        "      change_column :customers, :name, :string, limit: 255, null: false, default: 'anon'",
        '      add_check_constraint :products, \'"price" IS NULL OR "price" > 0\', '
        "name: 'ck_products_price_positive'",
        "      add_index :products, [:title], name: 'ix_products_title'",
    ):
        assert line in up, line
    for line in (
        "      remove_index :products, name: 'ix_products_title'",
        "      remove_check_constraint :products, name: 'ck_products_price_positive'",
        "      drop_table :reviews",
        "      change_column :customers, :name, :string, limit: 255",
        "      remove_column :products, :is_featured",
    ):
        assert line in down, line

    dropped = evolved(SHOP)
    dropped[3]["key_fields"].remove("stock_count")
    third = dc.build_deterministic_codegen_data(
        ShopProject(dropped, second), VUE_RAILS_STACK, allow_destructive_migration=True
    )
    migration = _migrations(third)[
        MIGRATIONS + "20240101000003_drop_products_stock_count_3.rb"
    ]
    assert "      remove_column :products, :stock_count\n" in migration
    assert "      add_column :products, :stock_count, :integer\n" in migration
    for content in _migrations(third).values():
        assert validate_generated_content("ruby", content, "x.rb") is None


def test_rails_columns_whose_default_is_an_expression_are_added_in_three_steps():
    """SQLite's ALTER TABLE ADD COLUMN refuses a default that is an
    expression, so the column is added bare, filled, then given its real
    definition (which rebuilds the table)."""
    tables = [{"name": "note", "key_fields": ["title"]}]
    first = dc.build_deterministic_codegen_data(
        FakeProject(tables=tables), VUE_RAILS_STACK
    )
    tables = [
        {
            "name": "note",
            "key_fields": ["title", "seen_at", "due"],
            "field_specs": [
                {
                    "name": "seen_at",
                    "type": "datetime",
                    "nullable": False,
                    "default": "now",
                },
                {"name": "due", "type": "date", "default": "today"},
            ],
        }
    ]
    second = dc.build_deterministic_codegen_data(
        FakeProject(tables=tables, codegen_data=first), VUE_RAILS_STACK
    )
    migration = _migrations(second)[
        MIGRATIONS + "20240101000002_add_notes_seen_at_and_more_2.rb"
    ]
    now = "strftime(\\'%Y-%m-%d %H:%M:%f000\\', \\'now\\')"
    assert (
        "      add_column :notes, :seen_at, :datetime, precision: 6\n"
        f'      execute \'UPDATE "notes" SET "seen_at" = {now}\'\n'
        f"      change_column :notes, :seen_at, :datetime, precision: 6, null: false, default: -> {{ '{now}' }}\n"
        "      add_column :notes, :due, :date\n"
        '      execute \'UPDATE "notes" SET "due" = CURRENT_DATE\'\n'
        "      change_column :notes, :due, :date, default: -> { 'CURRENT_DATE' }\n"
        in migration
    )


def test_rails_model_fields_cover_every_kind_of_column():
    files = _by_path(
        dc.build_deterministic_codegen_data(
            FakeProject(tables=RICH_TABLES), REACT_RAILS_STACK
        )
    )
    model = files["backend/app/models/book.rb"]
    for line in (
        "    'title' => { kind: :string, null: false, default: false, limit: 255 },",
        "    'author_id' => { kind: :integer, null: true, default: false, "
        "references: { model: 'Author', column: 'id', label: 'Author' } },",
        "    'price' => { kind: :decimal, null: true, default: true },",
        "    'is_available' => { kind: :boolean, null: false, default: true },",
        "    'published_at' => { kind: :datetime, null: true, default: false },",
        "    'released_on' => { kind: :date, null: true, default: false },",
        "    'meta' => { kind: :json, null: true, default: false },",
        "    'notes' => { kind: :string, null: true, default: false },",
    ):
        assert line in model, line
    assert "  FIELDS = {}.freeze\n" in files["backend/app/models/marker.rb"]
    author = files["backend/app/controllers/authors_controller.rb"]
    assert (
        "RESTRICT_MESSAGE = 'Can\\'t delete this record: Book still refer to it.'"
        in author
    )
    errors = files["backend/app/lib/database_errors.rb"]
    assert "    ['books.title, books.author_id', 409, " in errors
    assert "    ['ck_books_pages_positive', 422, " in errors


@pytest.mark.parametrize(
    "tables,message",
    [
        (
            [{"name": "data", "key_fields": ["title"]}],
            "would produce a class named Data",
        ),
        (
            [{"name": "api error", "key_fields": ["title"]}],
            "would produce a class named ApiError",
        ),
        (
            [{"name": "books controller", "key_fields": ["title"]}],
            "a name Rails keeps for controllers",
        ),
        (
            [{"name": "thing", "key_fields": ["changed"]}],
            'The field "changed" in "thing" would replace a method every Rails record',
        ),
        (
            [
                {
                    "name": "thing",
                    "key_fields": ["note"],
                    "checks": [{"name": "no smiley", "expression": "note <> ':)'"}],
                }
            ],
            'The rule "no smiley" on "thing" can\'t be kept by Rails on SQLite',
        ),
    ],
    ids=["ruby-constant", "own-constant", "controller", "record-method", "check"],
)
def test_rails_refuses_names_ruby_or_active_record_already_use(tables, message):
    with pytest.raises(dc.DeterministicCodegenError, match=re.escape(message)):
        dc.build_deterministic_codegen_data(
            FakeProject(tables=tables), REACT_RAILS_STACK
        )


def test_rails_user_text_is_escaped_and_cant_trip_the_generated_file_check():
    name = "TODO #{items} 'x' \\ %d"
    tables = [
        {
            "name": name,
            "purpose": "TODO (later",
            "key_fields": ["title", "parent_id"],
            "foreign_keys": [{"field": "parent_id", "references_table": name}],
        }
    ]
    data = dc.build_deterministic_codegen_data(
        FakeProject(tables=tables), VUE_RAILS_STACK
    )
    assert data["validation_warnings"] == []
    files = _by_path(data)
    # Single quotes: #{...} is never interpolated; "TODO" is split in two.
    label = "'TO' + 'DO #{items} \\'x\\' \\\\ %d'"
    model = files["backend/app/models/todo_items_x_d.rb"]
    assert model.startswith("# to-do #{items} 'x' \\ %d: to-do (later\n")
    assert "class TodoItemsXD < ApplicationRecord" in model
    assert (
        f"references: {{ model: 'TodoItemsXD', column: 'id', label: {label} }}" in model
    )
    controller = files["backend/app/controllers/todo_items_x_ds_controller.rb"]
    assert "class TodoItemsXDsController < ApplicationController" in controller
    assert f"  LABEL = {label}\n" in controller
    assert "TODO" not in "".join(
        c for p, c in files.items() if p.startswith("backend/")
    )


def test_ruby_strings_and_names():
    assert migrations_rails.ruby_str("it's \\ #{x}") == "'it\\'s \\\\ #{x}'"
    assert migrations_rails.ruby_str("a TODO b") == "'a TO' + 'DO b'"
    assert migrations_rails.camelize("order_items") == "OrderItems"
    assert migrations_rails.camelize("a1_b") == "A1B"
    assert codegen_rails.controller_class("order_items") == "OrderItemsController"
    assert migrations_rails.check_problem("\"note\" <> ':)'") is not None
    assert migrations_rails.check_problem("(\"a\" > 0) AND \"b\" IN ('x', 'y')") is None
    # Two revisions that do the same thing must still be two class names.
    assert migrations_rails.name("0002", "add_books_genre") == "add_books_genre_2"
    assert migrations_rails.name("0007", "add_books_genre") == "add_books_genre_7"
    assert migrations_rails.filename("0007", "add_books_genre") == (
        MIGRATIONS + "20240101000007_add_books_genre_7.rb"
    )


def test_rails_keeps_its_own_migration_history():
    """Active Record migrations are not the SQL files the Rust, Go and C#
    backends share, so a project that moves to Rails starts at 0001."""
    first = dc.build_deterministic_codegen_data(FakeProject(), REACT_GIN_STACK)
    second = dc.build_deterministic_codegen_data(
        FakeProject(codegen_data=first), REACT_RAILS_STACK
    )
    assert second["migrations"]["tool"] == "rails"
    assert [r["id"] for r in second["migrations"]["revisions"]] == ["0001"]
    assert list(_migrations(second)) == [
        MIGRATIONS + "20240101000001_initial_schema.rb"
    ]
    assert not any(p.startswith("backend/migrations/") for p in _by_path(second))


def test_rails_survives_tables_and_fields_named_like_its_own_code():
    """Locally: every file parses. That the app runs is test_rails_e2e.py's
    job, with real Ruby."""
    tables = e2e.awkward_tables("rails")
    names = [t["name"] for t in tables]
    # Data is a class of Ruby's own; `class` is a method every object has.
    assert "Data" not in names and len(names) == len(e2e.AWKWARD_TABLES) - 1
    table = next(t for t in tables if t["name"] == "Table")
    assert "class" not in table["key_fields"] and "event" in table["key_fields"]
    data = dc.build_deterministic_codegen_data(
        FakeProject(tables=tables), REACT_RAILS_STACK
    )
    assert data["validation_warnings"] == []
    files = _by_path(data)
    assert "class System < ApplicationRecord" in files["backend/app/models/system.rb"]
    assert (
        "class TypesController < ApplicationController"
        in files["backend/app/controllers/types_controller.rb"]
    )
