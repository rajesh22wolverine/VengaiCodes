"""Coverage for the AI-less, schema-driven code generator
(app/ai/codegen_deterministic.py). Three things matter here, mirroring
why the deterministic Page Engine has the same kind of test file:
real syntax validity (not just "didn't crash"), correct column-type
inference from field names, and — the one property that makes this
safe to run against an already-hand-edited project — that a
VENGAI:CUSTOM slot survives a regeneration untouched while the
template around it still picks up a real schema change.
"""

import ast
import json

import pytest

from app.ai import codegen_deterministic as dc
from app.ai.codegen_shared import validate_generated_content

STACK_INFO = {
    "frontend_framework": "react",
    "frontend_language": "javascript",
    "backend_framework": "fastapi",
    "backend_language": "python",
    "api_style": "rest",
    "codegen_target": "react__fastapi__rest",
    "source": "selected_stack",
    "fallback_reason": None,
}

UNSUPPORTED_STACK_INFO = {**STACK_INFO, "frontend_framework": "vue"}

TABLES = [
    {
        "name": "Book",
        "purpose": "A book in the library",
        "key_fields": ["title", "author", "isbn", "price", "is_available", "published_at"],
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

    def __init__(self, tables=TABLES, codegen_data=None):
        self.name = "Library Manager"
        self.architecture_data = {"architecture": {"database_tables": tables, "api_endpoints": []}}
        self.requirements_data = {
            "frd": {
                "key_features": ["users can scan a book cover"],
                "user_stories": ["as a member I want to see my borrowed books"],
            }
        }
        self.codegen_data = codegen_data


def _by_path(codegen_data: dict) -> dict[str, str]:
    return {f["path"]: f["content"] for f in codegen_data["codegen"]["files"]}


# ─── Stack gating ───
def test_is_supported_stack():
    assert dc.is_supported_stack(STACK_INFO)
    assert not dc.is_supported_stack(UNSUPPORTED_STACK_INFO)


# ─── Requires at least one table ───
def test_requires_at_least_one_table():
    with pytest.raises(dc.DeterministicCodegenError):
        dc.build_deterministic_codegen_data(FakeProject(tables=[]), STACK_INFO)


# ─── Real syntax validity, not just "didn't crash" ───
def test_generated_python_files_are_valid_syntax():
    data = dc.build_deterministic_codegen_data(FakeProject(), STACK_INFO)
    files = _by_path(data)
    py_paths = [p for p in files if p.endswith(".py")]
    assert py_paths, "expected python files"
    for path in py_paths:
        ast.parse(files[path])  # raises SyntaxError if invalid


def test_generated_js_files_pass_validation():
    data = dc.build_deterministic_codegen_data(FakeProject(), STACK_INFO)
    files = _by_path(data)
    js_paths = [p for p in files if p.endswith((".js", ".jsx"))]
    assert js_paths, "expected JS/JSX files"
    for path in js_paths:
        assert validate_generated_content("javascript", files[path]) is None


def test_zero_validation_warnings_and_generation_mode_flag():
    data = dc.build_deterministic_codegen_data(FakeProject(), STACK_INFO)
    assert data["validation_warnings"] == []
    assert data["generation_mode"] == "deterministic"
    assert data["user_approved"] is False


def test_matches_ai_path_codegen_data_shape():
    """Same top-level keys api/v1/codegen.py's _saved_result() and the
    three packaging trigger_build() handlers read from the AI path —
    this is what makes deterministic output packaging-transparent."""
    data = dc.build_deterministic_codegen_data(FakeProject(), STACK_INFO)
    for key in ("codegen", "files_generated", "native_capabilities", "validation_warnings", "stack_used", "user_approved", "generated_at"):
        assert key in data
    assert set(data["codegen"].keys()) == {"summary", "files"}
    for f in data["codegen"]["files"]:
        assert set(f.keys()) == {"path", "language", "content", "description"}


# ─── Column-type inference (the "golden" cases) ───
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
def test_column_type_inference(field, expected_sa_type):
    assert dc._infer_sa_type(field) == expected_sa_type


def test_model_file_has_correctly_typed_columns_and_a_custom_slot():
    data = dc.build_deterministic_codegen_data(FakeProject(), STACK_INFO)
    model = _by_path(data)["backend/models/book.py"]
    assert "class Book(Base):" in model
    assert "price = Column(Float, nullable=True)" in model
    assert "is_available = Column(Boolean, nullable=True)" in model
    assert "published_at = Column(DateTime(timezone=True), nullable=True)" in model
    assert "VENGAI:CUSTOM:book_model:start" in model
    assert "VENGAI:CUSTOM:book_model:end" in model


def test_routes_file_has_crud_for_every_table_and_a_custom_slot():
    data = dc.build_deterministic_codegen_data(FakeProject(), STACK_INFO)
    routes = _by_path(data)["backend/routes/api.py"]
    for path_fragment in ('"/books"', '"/books/{item_id}"', '"/members"', '"/members/{item_id}"'):
        assert path_fragment in routes
    assert "from models.book import Book" in routes
    assert "from models.member import Member" in routes
    assert "VENGAI:CUSTOM:extra_routes:start" in routes


def test_package_json_name_is_set():
    data = dc.build_deterministic_codegen_data(FakeProject(), STACK_INFO)
    pkg = json.loads(_by_path(data)["frontend/package.json"])
    assert pkg["name"] == "library-manager"


def test_native_capability_detection_from_requirements():
    data = dc.build_deterministic_codegen_data(FakeProject(), STACK_INFO)
    assert "camera" in data["native_capabilities"]


# ─── Custom-code preservation across a real regeneration ───
def test_custom_slot_survives_regeneration_while_schema_change_applies():
    first = dc.build_deterministic_codegen_data(FakeProject(), STACK_INFO)
    files = first["codegen"]["files"]

    hand_edit = "    def check_isbn(self):\n        return len(self.isbn or '') == 13\n"
    edited_files = [dict(f) for f in files]
    for f in edited_files:
        if f["path"] == "backend/models/book.py":
            f["content"] = f["content"].replace(
                "    # This block is preserved across future regenerations.\n",
                "    # This block is preserved across future regenerations.\n" + hand_edit,
            )

    # A real schema change: Book gains a new field between runs.
    changed_tables = [dict(TABLES[0], key_fields=TABLES[0]["key_fields"] + ["genre"]), TABLES[1]]
    project = FakeProject(
        tables=changed_tables,
        codegen_data={"codegen": {"summary": "", "files": edited_files}},
    )

    second = dc.build_deterministic_codegen_data(project, STACK_INFO)
    regenerated_model = _by_path(second)["backend/models/book.py"]

    assert "def check_isbn" in regenerated_model, "hand-edit inside VENGAI:CUSTOM must survive"
    assert "genre = Column(String(255), nullable=True)" in regenerated_model, "schema change must still apply"
    ast.parse(regenerated_model)  # still valid Python after the splice


def test_extract_and_reinject_custom_slots_directly():
    original = "before\n# VENGAI:CUSTOM:x:start\nold body\n# VENGAI:CUSTOM:x:end\nafter\n"
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
