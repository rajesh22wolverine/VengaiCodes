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

UNSUPPORTED_STACK = {**FASTAPI_STACK, "frontend_framework": "angular"}

SUPPORTED_STACKS = [FASTAPI_STACK, EXPRESS_STACK]

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
def test_is_supported_stack():
    assert dc.is_supported_stack(FASTAPI_STACK)
    assert dc.is_supported_stack(EXPRESS_STACK)
    assert not dc.is_supported_stack(UNSUPPORTED_STACK)


def test_supported_stacks_label_mentions_both_pairings():
    label = dc.supported_stacks_label()
    assert "React + FastAPI" in label
    assert "Vue + Express" in label


# ─── Requires at least one table (both pairings) ───
@pytest.mark.parametrize("stack_info", SUPPORTED_STACKS, ids=["fastapi", "express"])
def test_requires_at_least_one_table(stack_info):
    with pytest.raises(dc.DeterministicCodegenError):
        dc.build_deterministic_codegen_data(FakeProject(tables=[]), stack_info)


# ─── Shape parity across both pairings ───
@pytest.mark.parametrize("stack_info", SUPPORTED_STACKS, ids=["fastapi", "express"])
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


@pytest.mark.parametrize("stack_info", SUPPORTED_STACKS, ids=["fastapi", "express"])
def test_native_capability_detection_from_requirements(stack_info):
    data = dc.build_deterministic_codegen_data(FakeProject(), stack_info)
    assert "camera" in data["native_capabilities"]


@pytest.mark.parametrize("stack_info", SUPPORTED_STACKS, ids=["fastapi", "express"])
def test_frontend_package_json_name_is_set(stack_info):
    data = dc.build_deterministic_codegen_data(FakeProject(), stack_info)
    pkg = json.loads(_by_path(data)["frontend/package.json"])
    assert pkg["name"] == "library-manager"


@pytest.mark.parametrize("stack_info", SUPPORTED_STACKS, ids=["fastapi", "express"])
def test_custom_slot_survives_regeneration_while_schema_change_applies(stack_info):
    """The core guarantee, proven for BOTH pairings — not just asserted
    once and assumed to generalize."""
    first = dc.build_deterministic_codegen_data(FakeProject(), stack_info)
    files = first["codegen"]["files"]

    is_fastapi = stack_info["backend_framework"] == "fastapi"
    model_path = "backend/models/book.py" if is_fastapi else "backend/models/book.js"
    marker = (
        "# This block is preserved across future regenerations.\n"
        if is_fastapi
        else "// This block is preserved across future regenerations.\n"
    )
    hand_edit = (
        "    # a real hand-written addition\n"
        if is_fastapi
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


def test_vue_screen_uses_mongoose_id_convention():
    """Mongoose documents key on _id, not id — a real difference from
    the SQLAlchemy side that a naive copy-paste from the React template
    would get wrong."""
    data = dc.build_deterministic_codegen_data(FakeProject(), EXPRESS_STACK)
    screen = _by_path(data)["frontend/src/screens/BookScreen.vue"]
    assert "<script setup>" in screen
    assert 'v-model="form[field.key]"' in screen
    assert '{ key: "price", label: "price", type: "float"' in screen
    assert "item._id" in screen
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
