"""Coverage for the AI-less, schema-driven code generator
(app/ai/codegen_deterministic.py), across both supported pairings:
React+FastAPI (SQLAlchemy/relational) and Vue+Express (Mongoose/
document). Three things matter here, mirroring why the deterministic
Page Engine has the same kind of test file: real syntax/shape validity
(not just "didn't crash"), correct field-type inference from field
names for EACH backend's own type system, and — the one property that
makes this safe to run against an already-hand-edited project — that a
VENGAI:CUSTOM slot survives a regeneration untouched while the
template around it still picks up a real schema change.
"""

import ast
import json

import pytest

from app.ai import codegen_deterministic as dc
from app.ai.codegen_shared import validate_generated_content

FASTAPI_STACK = {
    "frontend_framework": "react",
    "frontend_language": "javascript",
    "backend_framework": "fastapi",
    "backend_language": "python",
    "api_style": "rest",
    "codegen_target": "react__fastapi__rest",
    "source": "selected_stack",
    "fallback_reason": None,
}

EXPRESS_STACK = {
    "frontend_framework": "vue",
    "frontend_language": "javascript",
    "backend_framework": "express",
    "backend_language": "javascript",
    "api_style": "rest",
    "codegen_target": "vue__express__rest",
    "source": "selected_stack",
    "fallback_reason": None,
}

# The cross pairings: any supported frontend with any supported backend.
REACT_EXPRESS_STACK = {
    **EXPRESS_STACK,
    "frontend_framework": "react",
    "codegen_target": "react__express__rest",
}
VUE_FASTAPI_STACK = {
    **FASTAPI_STACK,
    "frontend_framework": "vue",
    "codegen_target": "vue__fastapi__rest",
}

REACT_FLASK_STACK = {
    **FASTAPI_STACK,
    "backend_framework": "flask",
    "codegen_target": "react__flask__rest",
}
VUE_FLASK_STACK = {
    **REACT_FLASK_STACK,
    "frontend_framework": "vue",
    "codegen_target": "vue__flask__rest",
}

REACT_DJANGO_STACK = {
    **FASTAPI_STACK,
    "backend_framework": "django",
    "codegen_target": "react__django__rest",
}
VUE_DJANGO_STACK = {
    **REACT_DJANGO_STACK,
    "frontend_framework": "vue",
    "codegen_target": "vue__django__rest",
}

REACT_NESTJS_STACK = {
    **EXPRESS_STACK,
    "frontend_framework": "react",
    "backend_framework": "nestjs",
    "backend_language": "typescript",
    "codegen_target": "react__nestjs__rest",
}
VUE_NESTJS_STACK = {
    **REACT_NESTJS_STACK,
    "frontend_framework": "vue",
    "codegen_target": "vue__nestjs__rest",
}

REACT_SPRING_STACK = {
    **FASTAPI_STACK,
    "backend_framework": "spring_boot",
    "backend_language": "java",
    "codegen_target": "react__spring_boot__rest",
}
VUE_SPRING_STACK = {
    **REACT_SPRING_STACK,
    "frontend_framework": "vue",
    "codegen_target": "vue__spring_boot__rest",
}

UNSUPPORTED_STACK = {**FASTAPI_STACK, "frontend_framework": "angular"}

SUPPORTED_STACKS = [
    FASTAPI_STACK,
    EXPRESS_STACK,
    REACT_EXPRESS_STACK,
    VUE_FASTAPI_STACK,
    REACT_FLASK_STACK,
    VUE_FLASK_STACK,
    REACT_DJANGO_STACK,
    VUE_DJANGO_STACK,
    REACT_NESTJS_STACK,
    VUE_NESTJS_STACK,
    REACT_SPRING_STACK,
    VUE_SPRING_STACK,
]
STACK_IDS = [
    "react-fastapi",
    "vue-express",
    "react-express",
    "vue-fastapi",
    "react-flask",
    "vue-flask",
    "react-django",
    "vue-django",
    "react-nestjs",
    "vue-nestjs",
    "react-spring",
    "vue-spring",
]

# Where each backend writes a table's model.
MODEL_PATHS = {
    "fastapi": "backend/models/book.py",
    "flask": "backend/app/models/book.py",
    "django": "backend/api/models/book.py",
    "nestjs": "backend/src/book/book.entity.ts",
    "spring_boot": "backend/src/main/java/com/vengaicode/generated/librarymanager/model/Book.java",
    "express": "backend/models/book.js",
}

TABLES = [
    {
        "name": "Book",
        "purpose": "A book in the library",
        "key_fields": [
            "title",
            "author",
            "isbn",
            "price",
            "is_available",
            "published_at",
        ],
    },
    {
        "name": "Member",
        "purpose": "A library member",
        "key_fields": ["full_name", "email", "membership_count"],
    },
]


class FakeProject:
    """Duck-types just the attributes codegen_deterministic.py reads —
    no DB session needed, same spirit as this repo's other pure-function
    codegen tests."""

    def __init__(self, tables=TABLES, codegen_data=None, features=None, stories=None):
        self.name = "Library Manager"
        self.architecture_data = {
            "architecture": {"database_tables": tables, "api_endpoints": []}
        }
        self.requirements_data = {
            "frd": {
                "key_features": features
                if features is not None
                else ["users can scan a book cover"],
                "user_stories": stories
                if stories is not None
                else ["as a member I want to see my borrowed books"],
            }
        }
        self.codegen_data = codegen_data


def _by_path(codegen_data: dict) -> dict[str, str]:
    return {f["path"]: f["content"] for f in codegen_data["codegen"]["files"]}


# ─── Stack gating ───
@pytest.mark.parametrize("stack_info", SUPPORTED_STACKS, ids=STACK_IDS)
def test_is_supported_stack(stack_info):
    assert dc.is_supported_stack(stack_info)


def test_unsupported_stack():
    assert not dc.is_supported_stack(UNSUPPORTED_STACK)
    assert not dc.is_supported_stack({**FASTAPI_STACK, "api_style": "graphql"})


def test_supported_stacks_label_and_list():
    assert (
        dc.supported_stacks_label()
        == "React or Vue with Django, Express, FastAPI, Flask, NestJS or Spring Boot (REST)"
    )
    assert {
        "frontend": "vue",
        "backend": "fastapi",
        "api_style": "rest",
    } in dc.supported_stacks()
    assert len(dc.supported_stacks()) == 12


# ─── Requires at least one table (both pairings) ───
@pytest.mark.parametrize("stack_info", SUPPORTED_STACKS, ids=STACK_IDS)
def test_requires_at_least_one_table(stack_info):
    with pytest.raises(dc.DeterministicCodegenError):
        dc.build_deterministic_codegen_data(FakeProject(tables=[]), stack_info)


# ─── Shape parity across both pairings ───
@pytest.mark.parametrize("stack_info", SUPPORTED_STACKS, ids=STACK_IDS)
def test_matches_ai_path_codegen_data_shape(stack_info):
    """Same top-level keys api/v1/codegen.py's _saved_result() and the
    three packaging trigger_build() handlers read from the AI path —
    this is what makes deterministic output packaging-transparent,
    for BOTH pairings, not just the first one built."""
    data = dc.build_deterministic_codegen_data(FakeProject(), stack_info)
    for key in (
        "codegen",
        "files_generated",
        "native_capabilities",
        "validation_warnings",
        "stack_used",
        "user_approved",
        "generated_at",
    ):
        assert key in data
    assert data["generation_mode"] == "deterministic"
    assert data["user_approved"] is False
    assert data["validation_warnings"] == []
    assert set(data["codegen"].keys()) == {"summary", "files"}
    for f in data["codegen"]["files"]:
        assert set(f.keys()) == {"path", "language", "content", "description"}


@pytest.mark.parametrize("stack_info", SUPPORTED_STACKS, ids=STACK_IDS)
def test_native_capability_detection_from_requirements(stack_info):
    data = dc.build_deterministic_codegen_data(FakeProject(), stack_info)
    assert "camera" in data["native_capabilities"]


@pytest.mark.parametrize("stack_info", SUPPORTED_STACKS, ids=STACK_IDS)
def test_frontend_package_json_name_is_set(stack_info):
    data = dc.build_deterministic_codegen_data(FakeProject(), stack_info)
    pkg = json.loads(_by_path(data)["frontend/package.json"])
    assert pkg["name"] == "library-manager"


@pytest.mark.parametrize("stack_info", SUPPORTED_STACKS, ids=STACK_IDS)
def test_custom_slot_survives_regeneration_while_schema_change_applies(stack_info):
    """The core guarantee, proven for BOTH pairings — not just asserted
    once and assumed to generalize."""
    first = dc.build_deterministic_codegen_data(FakeProject(), stack_info)
    files = first["codegen"]["files"]

    is_python = stack_info["backend_framework"] in ("fastapi", "flask", "django")
    model_path = MODEL_PATHS[stack_info["backend_framework"]]
    marker = (
        "# This block is preserved across future regenerations.\n"
        if is_python
        else "// This block is preserved across future regenerations.\n"
    )
    hand_edit = (
        "    # a real hand-written addition\n"
        if is_python
        else "// a real hand-written addition\n"
    )

    edited_files = [dict(f) for f in files]
    for f in edited_files:
        if f["path"] == model_path:
            f["content"] = f["content"].replace(marker, marker + hand_edit)

    changed_tables = [
        dict(TABLES[0], key_fields=TABLES[0]["key_fields"] + ["genre"]),
        TABLES[1],
    ]
    project = FakeProject(
        tables=changed_tables,
        codegen_data={"codegen": {"summary": "", "files": edited_files}},
    )

    second = dc.build_deterministic_codegen_data(project, stack_info)
    regenerated = _by_path(second)[model_path]

    assert "a real hand-written addition" in regenerated, (
        "hand-edit inside VENGAI:CUSTOM must survive"
    )
    assert "genre" in regenerated, "schema change must still apply"


# ─── FastAPI + React specifics ───
@pytest.mark.parametrize(
    "field,expected_sa_type",
    [
        ("price", "Float"),
        ("is_available", "Boolean"),
        ("published_at", "DateTime(timezone=True)"),
        ("membership_count", "Integer"),
        ("email", "String(255)"),
        ("bio", "Text"),
        ("something_unrecognized", "String(255)"),
    ],
)
def test_sqlalchemy_column_type_inference(field, expected_sa_type):
    assert dc._infer_sa_type(field) == expected_sa_type


def test_fastapi_generated_python_files_are_valid_syntax():
    data = dc.build_deterministic_codegen_data(FakeProject(), FASTAPI_STACK)
    files = _by_path(data)
    py_paths = [p for p in files if p.endswith(".py")]
    assert py_paths
    for path in py_paths:
        ast.parse(files[path])  # raises SyntaxError if invalid


def test_fastapi_generated_js_files_pass_validation():
    data = dc.build_deterministic_codegen_data(FakeProject(), FASTAPI_STACK)
    files = _by_path(data)
    js_paths = [p for p in files if p.endswith((".js", ".jsx"))]
    assert js_paths
    for path in js_paths:
        assert validate_generated_content("javascript", files[path]) is None


def test_fastapi_model_file_has_correctly_typed_columns_and_a_custom_slot():
    data = dc.build_deterministic_codegen_data(FakeProject(), FASTAPI_STACK)
    model = _by_path(data)["backend/models/book.py"]
    assert "class Book(Base):" in model
    assert '__tablename__ = "books"' in model
    # Undeclared fields keep the by-name inference, now as explicit
    # sqlalchemy types (the same code the migration renders).
    assert "price = sa.Column(sa.Float(), nullable=True)" in model
    assert "is_available = sa.Column(sa.Boolean(), nullable=True)" in model
    assert (
        "published_at = sa.Column(sa.DateTime(timezone=True), nullable=True)" in model
    )
    assert "isbn = sa.Column(sa.String(length=255), nullable=True)" in model
    assert "VENGAI:CUSTOM:book_model:start" in model
    assert "VENGAI:CUSTOM:book_model:end" in model


def test_fastapi_routes_file_has_crud_for_every_table_and_a_custom_slot():
    data = dc.build_deterministic_codegen_data(FakeProject(), FASTAPI_STACK)
    routes = _by_path(data)["backend/routes/api.py"]
    for path_fragment in (
        '"/books"',
        '"/books/{item_id}"',
        '"/members"',
        '"/members/{item_id}"',
    ):
        assert path_fragment in routes
    assert "from models.book import Book" in routes
    assert "from models.member import Member" in routes
    assert "VENGAI:CUSTOM:extra_routes:start" in routes


# ─── Vue + Express specifics ───
@pytest.mark.parametrize(
    "field,expected_mongoose_type",
    [
        ("price", "Number"),
        ("is_available", "Boolean"),
        ("published_at", "Date"),
        ("membership_count", "Number"),
        ("email", "String"),
        ("bio", "String"),
        ("something_unrecognized", "String"),
    ],
)
def test_mongoose_type_inference(field, expected_mongoose_type):
    assert dc._infer_mongoose_type(field) == expected_mongoose_type


def test_express_generated_js_files_pass_validation_and_are_brace_balanced():
    data = dc.build_deterministic_codegen_data(FakeProject(), EXPRESS_STACK)
    files = _by_path(data)
    js_paths = [p for p in files if p.endswith(".js")]
    assert js_paths
    for path in js_paths:
        assert validate_generated_content("javascript", files[path]) is None
        assert files[path].count("{") == files[path].count("}"), path


def test_express_model_file_has_correctly_typed_fields_and_a_custom_slot():
    data = dc.build_deterministic_codegen_data(FakeProject(), EXPRESS_STACK)
    model = _by_path(data)["backend/models/book.js"]
    assert "const mongoose = require('mongoose');" in model
    assert "price: { type: Number }," in model
    assert "is_available: { type: Boolean }," in model
    assert "published_at: { type: Date }," in model
    assert 'collection: "books",' in model
    assert "autoIndex: false," in model
    assert 'module.exports = mongoose.model("Book", BookSchema);' in model
    assert "VENGAI:CUSTOM:book_model:start" in model
    assert "VENGAI:CUSTOM:book_model:end" in model


def test_express_routes_file_has_crud_for_every_table_and_a_custom_slot():
    data = dc.build_deterministic_codegen_data(FakeProject(), EXPRESS_STACK)
    routes = _by_path(data)["backend/routes/api.js"]
    for fragment in (
        "router.get('/books'",
        "router.get('/books/:id'",
        "router.get('/members'",
        "router.get('/members/:id'",
    ):
        assert fragment in routes
    # <Class>Model, so a table named e.g. "Date" can't hide the JS built-in.
    assert "const BookModel = require('../models/book');" in routes
    assert "VENGAI:CUSTOM:extra_routes:start" in routes
    assert "module.exports = router;" in routes


@pytest.mark.parametrize("stack_info", SUPPORTED_STACKS, ids=STACK_IDS)
def test_every_pairing_parses_and_uses_its_backends_id_key(stack_info):
    """Screens are the only frontend code that knows the backend: the
    record id's key ("id" for SQL, "_id" for MongoDB), and whether a
    foreign key holds a document id."""
    data = dc.build_deterministic_codegen_data(FakeProject(), stack_info)
    for f in data["codegen"]["files"]:
        empty_package_marker = f["path"].endswith("__init__.py") and not f["content"]
        # The README's code fences are the point; an empty __init__.py is normal.
        if not f["path"].endswith(".md") and not empty_package_marker:
            assert (
                validate_generated_content(f["language"], f["content"], f["path"])
                is None
            ), f["path"]
    files = _by_path(data)
    ext = "jsx" if stack_info["frontend_framework"] == "react" else "vue"
    screen = files[f"frontend/src/screens/BookScreen.{ext}"]
    id_key = "_id" if stack_info["backend_framework"] == "express" else "id"
    assert f'const ID_KEY = "{id_key}";' in screen
    assert "item[ID_KEY]" in screen
    assert "item.id" not in screen and "item._id" not in screen


@pytest.mark.parametrize("stack_info", SUPPORTED_STACKS, ids=STACK_IDS)
def test_vite_dev_server_proxies_api_to_the_backend(stack_info):
    data = dc.build_deterministic_codegen_data(FakeProject(), stack_info)
    vite = _by_path(data)["frontend/vite.config.js"]
    port = {"fastapi": 8000, "django": 8000, "nestjs": 3000, "spring_boot": 8080}.get(
        stack_info["backend_framework"], 5000
    )
    assert "'/api': {" in vite
    assert f'process.env.VITE_API_PROXY || "http://localhost:{port}"' in vite


def test_foreign_keys_follow_the_backend_not_the_frontend():
    tables = [
        {"name": "authors", "key_fields": ["name"]},
        {
            "name": "books",
            "key_fields": ["title", "author_id"],
            "foreign_keys": [{"field": "author_id", "references_table": "authors"}],
        },
    ]
    react_mongo = _by_path(
        dc.build_deterministic_codegen_data(
            FakeProject(tables=tables), REACT_EXPRESS_STACK
        )
    )["frontend/src/screens/BooksScreen.jsx"]
    vue_sql = _by_path(
        dc.build_deterministic_codegen_data(
            FakeProject(tables=tables), VUE_FASTAPI_STACK
        )
    )["frontend/src/screens/BooksScreen.vue"]
    assert 'type: "reference"' in react_mongo and 'valueKey: "_id"' in react_mongo
    assert 'type: "integer"' in vue_sql and 'valueKey: "id"' in vue_sql


def test_vue_screen_uses_mongoose_id_convention():
    """Mongoose documents key on _id, not id — a real difference from
    the SQLAlchemy side that a naive copy-paste from the React template
    would get wrong."""
    data = dc.build_deterministic_codegen_data(FakeProject(), EXPRESS_STACK)
    screen = _by_path(data)["frontend/src/screens/BookScreen.vue"]
    assert "<script setup>" in screen
    assert 'v-model="form[field.key]"' in screen
    assert '{ key: "price", label: "price", type: "float"' in screen
    assert 'const ID_KEY = "_id";' in screen
    assert "VENGAI:CUSTOM:book_screen:start" in screen


def test_express_backend_package_json_has_express_and_mongoose():
    data = dc.build_deterministic_codegen_data(FakeProject(), EXPRESS_STACK)
    pkg = json.loads(_by_path(data)["backend/package.json"])
    assert "express" in pkg["dependencies"]
    assert "mongoose" in pkg["dependencies"]


# ─── Custom-slot extraction/reinjection, backend-agnostic ───
def test_extract_and_reinject_custom_slots_directly():
    original = (
        "before\n# VENGAI:CUSTOM:x:start\nold body\n# VENGAI:CUSTOM:x:end\nafter\n"
    )
    slots = dc.extract_custom_slots(original)
    assert slots == {"x": "old body\n"}

    fresh_template = "before2\n# VENGAI:CUSTOM:x:start\ndefault body\n# VENGAI:CUSTOM:x:end\nafter2\n"
    merged = dc.reinject_custom_slots(fresh_template, slots)
    assert "old body" in merged
    assert "default body" not in merged
    assert "before2" in merged and "after2" in merged


def test_reinject_leaves_new_slot_names_untouched():
    """A slot name that didn't exist in the old file (a brand-new table)
    keeps the template's own default — nothing to merge in yet."""
    fresh_template = "# VENGAI:CUSTOM:new_table_model:start\ndefault\n# VENGAI:CUSTOM:new_table_model:end\n"
    merged = dc.reinject_custom_slots(fresh_template, old_slots={})
    assert merged == fresh_template


# ─── What the clients show next to the No-AI option ───
def test_stacks_endpoint_lists_every_pairing_and_needs_sign_in():
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from app.api.v1.auth import get_current_active_user
    from app.config import settings
    from app.main import app

    url = f"{settings.API_V1_PREFIX}/codegen/deterministic/stacks"
    client = TestClient(app)
    assert client.get(url).status_code in (401, 403)
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(id="u1")
    try:
        body = client.get(url).json()
    finally:
        app.dependency_overrides.clear()
    assert body["label"] == dc.supported_stacks_label()
    assert len(body["stacks"]) == len(dc.SUPPORTED_STACKS) == 12


# ─── Flask specifics ───
def _without_create_date(text: str) -> str:
    return "\n".join(
        line for line in text.splitlines() if not line.startswith("Create Date")
    )


def test_flask_backend_shares_fastapis_model_columns_and_migrations():
    """Same columns and the same Alembic revision as FastAPI — only the
    base class and module paths differ — so a project can switch between
    the two and keep its database and migration history."""
    fastapi = _by_path(
        dc.build_deterministic_codegen_data(FakeProject(), FASTAPI_STACK)
    )
    flask = _by_path(
        dc.build_deterministic_codegen_data(FakeProject(), REACT_FLASK_STACK)
    )
    fa_model, fl_model = (
        fastapi["backend/models/book.py"],
        flask["backend/app/models/book.py"],
    )
    assert "from app.extensions import db" in fl_model
    assert "class Book(db.Model):" in fl_model
    assert fa_model.replace("from app.core.database import Base", "").replace(
        "class Book(Base):", ""
    ) == fl_model.replace("from app.extensions import db", "").replace(
        "class Book(db.Model):", ""
    )
    fa_rev = [p for p in fastapi if p.startswith("backend/migrations/versions/")]
    fl_rev = [p for p in flask if p.startswith("backend/migrations/versions/")]
    assert fa_rev == fl_rev == ["backend/migrations/versions/0001_initial.py"]
    assert _without_create_date(fastapi[fa_rev[0]]) == _without_create_date(
        flask[fl_rev[0]]
    )
    env = flask["backend/migrations/env.py"]
    assert "from app.extensions import DATABASE_URL, db" in env
    assert "import app.models.book" in env
    assert "create_async_engine" not in env


def test_switching_fastapi_to_flask_keeps_the_migration_history():
    first = dc.build_deterministic_codegen_data(FakeProject(), FASTAPI_STACK)
    changed = [
        dict(TABLES[0], key_fields=TABLES[0]["key_fields"] + ["genre"]),
        TABLES[1],
    ]
    second = dc.build_deterministic_codegen_data(
        FakeProject(tables=changed, codegen_data=first), REACT_FLASK_STACK
    )
    revisions = [r["filename"] for r in second["migrations"]["revisions"]]
    assert revisions == [
        "backend/migrations/versions/0001_initial.py",
        "backend/migrations/versions/0002_add_books_genre.py",
    ]
    assert second["migrations"]["backend"] == "flask"


def test_flask_routes_and_app_factory():
    files = _by_path(
        dc.build_deterministic_codegen_data(FakeProject(), VUE_FLASK_STACK)
    )
    routes = files["backend/app/routes/api.py"]
    for fragment in (
        '@bp.get("/books")',
        '@bp.post("/books")',
        '@bp.put("/books/<int(signed=True):item_id>")',
        '@bp.delete("/members/<int(signed=True):item_id>")',
        "from app.models.book import Book",
        "class BookCreate(BaseModel):",
        "VENGAI:CUSTOM:extra_routes:start",
    ):
        assert fragment in routes, fragment
    init = files["backend/app/__init__.py"]
    assert "run_migrations()" in init and "create_all()" not in init
    assert 'app.register_blueprint(api_bp, url_prefix="/api")' in init
    assert "enable_sqlite_foreign_keys" in init
    assert files["backend/app/migrate.py"].count("os.path.dirname(") == 2
    requirements = files["backend/requirements.txt"]
    for pin in ("flask==", "flask-sqlalchemy==", "pydantic==", "alembic=="):
        assert pin in requirements, pin
    assert "python run.py" in files["README_SETUP.md"]


@pytest.mark.parametrize("field", ["query", "query_class", "model_dump", "sa"])
def test_flask_refuses_field_names_its_code_already_uses(field):
    tables = [{"name": "Book", "key_fields": ["title", field]}]
    with pytest.raises(dc.DeterministicCodegenError, match=field):
        dc.build_deterministic_codegen_data(
            FakeProject(tables=tables), REACT_FLASK_STACK
        )


# ─── Django specifics ───
def test_django_backend_files():
    files = _by_path(
        dc.build_deterministic_codegen_data(FakeProject(), REACT_DJANGO_STACK)
    )
    model = files["backend/api/models/book.py"]
    assert "class Book(models.Model):" in model and 'db_table = "books"' in model
    assert "VENGAI:CUSTOM:book_model:start" in model
    assert "router = SimpleRouter(trailing_slash=False)" in files["backend/api/urls.py"]
    assert (
        'router.register("books", views.BookViewSet, basename="books")'
        in files["backend/api/urls.py"]
    )
    assert "class BookViewSet(CrudViewSet):" in files["backend/api/views.py"]
    assert (
        "class BookSerializer(serializers.ModelSerializer):"
        in files["backend/api/serializers.py"]
    )
    assert "backend/api/migrations/0001_initial.py" in files
    assert "from api import lookups" in files["backend/api/models/__init__.py"]
    settings = files["backend/config/settings.py"]
    assert '"EXCEPTION_HANDLER": "api.errors.exception_handler"' in settings
    assert (
        "dj_database_url.parse" in settings
        and '"COERCE_DECIMAL_TO_STRING": False' in settings
    )
    requirements = files["backend/requirements.txt"]
    for pin in ("django==", "djangorestframework==", "dj-database-url==", "uvicorn=="):
        assert pin in requirements, pin
    assert 'path("api/", include("api.urls"))' in files["backend/config/urls.py"]
    assert "python manage.py migrate" in files["README_SETUP.md"]


def test_django_foreign_keys_are_named_the_django_way_but_keep_their_column():
    tables = [
        {"name": "authors", "key_fields": ["name"]},
        {
            "name": "books",
            "key_fields": ["title", "author_id"],
            "foreign_keys": [{"field": "author_id", "references_table": "authors"}],
        },
    ]
    files = _by_path(
        dc.build_deterministic_codegen_data(
            FakeProject(tables=tables), VUE_DJANGO_STACK
        )
    )
    assert (
        'author = models.ForeignKey("api.Authors"'
        in files["backend/api/models/books.py"]
    )
    assert 'db_column="author_id"' in files["backend/api/models/books.py"]
    assert (
        'author_id = serializers.PrimaryKeyRelatedField(source="author"'
        in files["backend/api/serializers.py"]
    )


def test_django_refuses_what_it_cant_name():
    clash = [
        {"name": "authors", "key_fields": ["name"]},
        {
            "name": "books",
            "key_fields": ["author", "author_id"],
            "foreign_keys": [{"field": "author_id", "references_table": "authors"}],
        },
    ]
    with pytest.raises(dc.DeterministicCodegenError, match="author"):
        dc.build_deterministic_codegen_data(
            FakeProject(tables=clash), REACT_DJANGO_STACK
        )
    reserved = [{"name": "Crud View Set", "key_fields": ["title"]}]
    with pytest.raises(dc.DeterministicCodegenError, match="CrudViewSet"):
        dc.build_deterministic_codegen_data(
            FakeProject(tables=reserved), REACT_DJANGO_STACK
        )
    for field in ("models", "objects"):
        tables = [{"name": "Book", "key_fields": ["title", field]}]
        with pytest.raises(dc.DeterministicCodegenError, match=field):
            dc.build_deterministic_codegen_data(
                FakeProject(tables=tables), REACT_DJANGO_STACK
            )


def test_ai_django_apps_get_uvicorn_for_the_desktop_sidecar():
    from app.ai.codegen.backend import django as django_adapter
    from app.ai.codegen.types import WiringCtx

    ctx = WiringCtx("App", [], [], [], [], [])
    assert "uvicorn==" in django_adapter.manifest_files(ctx)[0].content


def test_screens_read_django_rest_framework_errors():
    crud = _by_path(
        dc.build_deterministic_codegen_data(FakeProject(), REACT_DJANGO_STACK)
    )["frontend/src/lib/crud.js"]
    assert "Django REST Framework's 400" in crud and "non_field_errors" in crud


# ─── NestJS specifics ───
def test_nestjs_feature_modules_and_wiring():
    files = _by_path(
        dc.build_deterministic_codegen_data(FakeProject(), REACT_NESTJS_STACK)
    )
    for part in ("entity", "dto", "service", "controller", "module"):
        assert f"backend/src/book/book.{part}.ts" in files, part
    entity = files["backend/src/book/book.entity.ts"]
    assert '@Entity({ name: "books" })' in entity and "export class Book {" in entity
    assert "VENGAI:CUSTOM:book_model:start" in entity
    assert '@Controller("books")' in files["backend/src/book/book.controller.ts"]
    assert "@IsInt()" in files["backend/src/member/member.dto.ts"]
    app_module = files["backend/src/app.module.ts"]
    assert (
        "TypeOrmModule.forRoot(databaseOptions)" in app_module
        and "BookModule," in app_module
    )
    main = files["backend/src/main.ts"]
    assert (
        "app.setGlobalPrefix('api')" in main
        and "new ValidationPipe({ whitelist: true" in main
    )
    database = files["backend/src/database.ts"]
    assert "migrationsRun: true" in database and "synchronize: false" in database
    assert "backend/src/migrations/0001-initial.ts" in files
    pkg = json.loads(files["backend/package.json"])
    assert "class-validator" in pkg["dependencies"] and "schema:check" in pkg["scripts"]


def test_nestjs_user_text_cant_trip_the_generated_file_check():
    """A table named or described with "TODO" still produces files that
    pass the check (escaped in strings, reworded in comments)."""
    tables = [{"name": "TODO items", "purpose": "TODO (later", "key_fields": ["title"]}]
    data = dc.build_deterministic_codegen_data(
        FakeProject(tables=tables), VUE_NESTJS_STACK
    )
    assert data["validation_warnings"] == []


def test_nestjs_refuses_class_names_its_code_uses():
    tables = [{"name": "Index", "key_fields": ["title"]}]
    with pytest.raises(dc.DeterministicCodegenError, match="Index"):
        dc.build_deterministic_codegen_data(
            FakeProject(tables=tables), REACT_NESTJS_STACK
        )


# ─── Spring Boot specifics ───
SPRING_PKG = "backend/src/main/java/com/vengaicode/generated/librarymanager"


def test_spring_layout_and_config():
    files = _by_path(
        dc.build_deterministic_codegen_data(FakeProject(), REACT_SPRING_STACK)
    )
    for sub, name in (
        ("model", "Book"),
        ("dto", "BookRequest"),
        ("dto", "BookResponse"),
        ("service", "BookService"),
        ("controller", "BookController"),
        ("repository", "BookRepository"),
        ("support", "ApiErrors"),
        ("controller", "RootController"),
    ):
        assert f"{SPRING_PKG}/{sub}/{name}.java" in files, name
    entity = files[f"{SPRING_PKG}/model/Book.java"]
    assert (
        '@Table(name = "books")' in entity
        and "VENGAI:CUSTOM:book_model:start" in entity
    )
    assert (
        '@RequestMapping("/api/books")'
        in files[f"{SPRING_PKG}/controller/BookController.java"]
    )
    assert (
        "public Optional<@Size(max = 255) String> title;"
        in files[f"{SPRING_PKG}/dto/BookRequest.java"]
    )
    assert (
        '@JsonProperty("is_available") Boolean isAvailable'
        in files[f"{SPRING_PKG}/dto/BookResponse.java"]
    )
    props = files["backend/src/main/resources/application.properties"]
    assert "ddl-auto=validate" in props and "globally_quoted_identifiers=true" in props
    assert "WRITE_DELAY=0" in props  # a crash must not lose committed rows
    pom = files["backend/pom.xml"]
    assert "flyway-core" in pom and "spring-boot-starter-validation" in pom
    assert "backend/src/main/resources/db/migration/V1__initial.sql" in files
    assert "mvn spring-boot:run" in files["README_SETUP.md"]


def test_spring_ai_path_no_longer_points_at_a_missing_maven_wrapper():
    from app.ai.codegen.backend import spring_boot

    assert spring_boot.setup_commands("App") == ["cd backend", "mvn spring-boot:run"]
