"""
The knowledge registry (app/ai/knowledge/) and the places that use it:
schema validation, AI code prompts, SDLC phase prompts, the API.
"""

import asyncio
import keyword

import pytest
from fastapi.testclient import TestClient

from app.ai import codegen_shared, db_schema, knowledge
from app.ai.stack_matrix import BACKEND_FRAMEWORKS, FRONTEND_FRAMEWORKS
from app.api.v1.requirements import build_frd_prompt
from app.main import app


# ─── Coverage and correctness of the data ───
def test_every_stack_framework_and_language_is_known():
    frameworks = [k for k in (*FRONTEND_FRAMEWORKS, *BACKEND_FRAMEWORKS) if k != "none"]
    assert [k for k in frameworks if knowledge.framework(k) is None] == []
    languages = {
        lang
        for d in (FRONTEND_FRAMEWORKS, BACKEND_FRAMEWORKS)
        for meta in d.values()
        for lang in meta["languages"]
        if lang != "none"
    }
    assert sorted(lang for lang in languages if knowledge.language(lang) is None) == []


def test_keyword_lists_match_the_language_specifications():
    assert knowledge.language("python").keywords == frozenset(keyword.kwlist)
    assert len(knowledge.language("go").keywords) == 25
    assert len(knowledge.language("csharp").keywords) == 77
    assert {"class", "goto", "const", "_"} <= knowledge.language("java").keywords
    assert {"type", "match", "fn", "async", "yield"} <= knowledge.language(
        "rust"
    ).keywords
    assert {"class", "await", "enum", "let", "yield"} <= knowledge.language(
        "javascript"
    ).keywords
    assert {"end", "def", "unless", "__FILE__"} <= knowledge.language("ruby").keywords


@pytest.mark.parametrize(
    "path,lang",
    [
        ("frontend/src/App.tsx", "typescript"),
        ("backend/models/order.py", "python"),
        ("src/main.rs", "rust"),
        ("README", None),
    ],
)
def test_language_for_path(path, lang):
    spec = knowledge.language_for_path(path)
    assert (spec.key if spec else None) == lang


def test_identifier_for():
    assert knowledge.identifier_for("order_item_id", "camel") == "orderItemId"
    assert knowledge.identifier_for("order_item_id", "pascal") == "OrderItemId"
    assert knowledge.identifier_for("order_item_id", "snake") == "order_item_id"


# ─── Names each stack can't use ───
@pytest.mark.parametrize(
    "backend,slug,problem",
    [
        ("rails", "type", "single-table inheritance"),
        ("flask", "query", "Model.query"),
        ("django", "objects", "default manager"),
        ("spring_boot", "class", "Java keyword `class`"),
        ("spring_boot", "default", "Java keyword `default`"),
        ("actix", "match", "Rust keyword `match`"),
        ("laravel", "fillable", "Eloquent"),
        ("gin", "type", None),  # becomes the exported field Type — legal Go
        ("aspnet_core", "class", None),  # becomes the property Class — legal C#
        ("express", "class", None),  # a property name — legal JavaScript
        ("spring_boot", "order_id", None),
        (None, "type", None),
    ],
)
def test_field_problem(backend, slug, problem):
    reason = knowledge.field_problem(slug, backend)
    assert (reason is None) == (problem is None), reason
    if problem:
        assert problem in reason


def test_csharp_property_cant_share_its_class_name():
    assert "can't share its class's name" in knowledge.field_problem(
        "order", "aspnet_core", "Order"
    )
    assert knowledge.field_problem("order", "gin", "Order") is None


@pytest.mark.parametrize(
    "backend,slug,problem",
    [
        ("spring_boot", "string", "Java/Spring Boot type (String)"),
        ("aspnet_core", "task", "(Task)"),
        ("actix", "box", "(Box)"),
        ("laravel", "list", "PHP keyword"),  # PHP keywords are case-insensitive
        ("fastapi", "none", "Python keyword"),  # class None(...) is a SyntaxError
        ("fastapi", "string", None),
        ("gin", "string", None),
    ],
)
def test_table_problem(backend, slug, problem):
    reason = knowledge.table_problem(slug, backend)
    assert (reason is None) == (problem is None), reason
    if problem:
        assert problem in reason


def test_every_backend_names_the_tables_it_keeps_for_itself():
    """Every backend's migration tool keeps its history in a table (or
    collection) of the app's own database."""
    backends = [k for k in BACKEND_FRAMEWORKS if k != "none"]
    assert [k for k in backends if not knowledge.framework(k).reserved_tables] == []


@pytest.mark.parametrize(
    "backend,table,stored_as,problem",
    [
        ("laravel", "Migration", "migrations", "Laravel keeps its migration history"),
        ("nestjs", "migration", "migrations", "TypeORM keeps its migration history"),
        ("rails", "Schema Migration", "schema_migrations", "Active Record keeps"),
        ("django", "Django Migration", "django_migrations", "Django keeps"),
        # SQLite won't create a table named sqlite_…, whichever SQL backend.
        ("gin", "SQLite Sequence", "sqlite_sequences", "SQLite keeps for itself"),
        ("fastapi", "sqlite stat", "sqlite_stats", "SQLite keeps for itself"),
        # An ordinary table wherever the name isn't taken.
        ("rails", "Migration", "migrations", None),
        ("fastapi", "Migration", "migrations", None),
        ("gin", "Schema Migration", "schema_migrations", None),
        ("express", "SQLite Sequence", "sqlite_sequences", None),
    ],
)
def test_a_table_cant_be_stored_where_the_stack_keeps_its_own(
    backend, table, stored_as, problem
):
    issues = db_schema.validate_tables([{"name": table, "key_fields": ["x"]}], backend)
    if problem is None:
        assert issues == []
        return
    assert len(issues) == 1 and issues[0].kind == "table", issues
    assert f'it would be stored as "{stored_as}", ' in issues[0].message
    assert problem in issues[0].message


def test_the_architecture_editor_refuses_names_the_stack_cant_use():
    def messages(tables, backend):
        return [i.message for i in db_schema.validate_tables(tables, backend)]

    posts = [{"name": "posts", "key_fields": ["title", "type"]}]
    assert "single-table inheritance" in messages(posts, "rails")[0]
    assert messages(posts, "fastapi") == []  # a plain column there
    assert (
        "can't share its class's name"
        in messages([{"name": "Order", "key_fields": ["order"]}], "aspnet_core")[0]
    )
    assert (
        "(String)"
        in messages([{"name": "string", "key_fields": ["x"]}], "spring_boot")[0]
    )


# ─── Prompts ───
def test_language_and_framework_rules_for_prompt():
    rules = knowledge.language_rules_for_prompt("python", "fastapi")
    assert "Python rules" in rules and "FastAPI rules" in rules and "PEP 8" in rules
    assert "Reserved words that can't be identifiers:" in rules
    # A framework of another language (fastapi writing a JSON manifest) is left out.
    assert "FastAPI" not in knowledge.language_rules_for_prompt("json", "fastapi")
    assert knowledge.language_rules_for_prompt("text", None) == ""


def test_every_code_prompt_carries_the_rules(monkeypatch):
    prompts = []

    async def fake_generate_text(prompt, **kwargs):
        prompts.append(prompt)
        return {"text": "x = 1\n"}

    monkeypatch.setattr(codegen_shared, "generate_text", fake_generate_text)
    with codegen_shared.generating_for("django"):
        asyncio.run(codegen_shared.generate_text_validated("Write a model.", "python"))
    asyncio.run(
        codegen_shared.generate_text_validated("Write a component.", "typescript")
    )
    assert (
        prompts[0].startswith("Write a model.")
        and "Django rules" in prompts[0]
        and "Python rules" in prompts[0]
    )
    assert "TypeScript rules" in prompts[1] and "Django" not in prompts[1]


def test_architecture_prompt_names_what_to_avoid():
    from app.api.v1.architecture import build_stack_directive

    directive = build_stack_directive(
        {
            "frontend_framework": "react",
            "backend_framework": "rails",
            "backend_language": "ruby",
            "api_style": "rest",
        }
    )
    assert "For Ruby on Rails, avoid:" in directive and "type" in directive
    assert (
        "a table stored as ar_internal_metadata or schema_migrations "
        "(the framework keeps those tables for itself)" in directive
    )


def test_phase_rules_sit_before_the_final_instruction():
    prompt = build_frd_prompt("Demo", "an idea", [])
    assert "Requirements good practice:" in prompt
    assert prompt.rstrip().endswith("Respond with ONLY the JSON object, nothing else.")
    assert prompt.index("Requirements good practice:") < prompt.index(
        "Respond with ONLY"
    )


# ─── API ───
def test_knowledge_api():
    client = TestClient(app)
    body = client.get("/api/v1/knowledge").json()
    assert (
        len(body["languages"]) >= 20
        and len(body["frameworks"]) == 22
        and len(body["sdlc_phases"]) == 7
    )
    assert (
        client.get("/api/v1/knowledge/languages/py").json()["language"]["key"]
        == "python"
    )
    assert (
        "type"
        in client.get("/api/v1/knowledge/frameworks/rails").json()["framework"][
            "reserved_field_names"
        ]
    )
    assert client.get("/api/v1/knowledge/frameworks/cobol").status_code == 404
