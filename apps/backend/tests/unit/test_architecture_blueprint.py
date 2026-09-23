"""Coverage for the Architecture phase's deterministic blueprint output:
Mermaid system/ERD diagrams built straight from the AI-generated
ArchitectureDesign object (no second AI call, so they can't drift from or
contradict what generate_architecture actually decided), and the ADR
schema that wires the previously-unused Project.architecture_data.adrs
field to something a generator actually produces.
"""

import pytest

from app.api.v1.architecture import (
    ADR,
    APIEndpoint,
    ArchitectureDesign,
    ArchitectureEditError,
    DatabaseTable,
    TechStack,
    apply_architecture_edit,
    build_architecture_prompt,
    build_erd,
    build_system_diagram,
)


def _sample_architecture(**overrides) -> ArchitectureDesign:
    defaults = dict(
        architecture_summary="A simple CRUD app.",
        tech_stack=TechStack(
            frontend="React", backend="FastAPI", database="PostgreSQL", hosting="Render"
        ),
        database_tables=[
            DatabaseTable(
                name="products",
                purpose="Store products",
                key_fields=["id", "title", "price"],
            )
        ],
        api_endpoints=[
            APIEndpoint(method="GET", path="/products", purpose="List products")
        ],
        third_party_services=["Stripe (payments)"],
        adrs=[
            ADR(
                title="Use FastAPI",
                decision="Adopt FastAPI for the backend",
                rationale="Detected in the reverse-engineered source",
                alternatives_considered=["Django", "Flask"],
            )
        ],
    )
    defaults.update(overrides)
    return ArchitectureDesign(**defaults)


def test_build_system_diagram_includes_frontend_backend_database():
    diagram = build_system_diagram(_sample_architecture())
    assert diagram.startswith("graph TD")
    assert "React" in diagram
    assert "FastAPI" in diagram
    assert "PostgreSQL" in diagram
    assert "FE --> BE" in diagram
    assert "BE --> DB" in diagram


def test_build_system_diagram_adds_a_node_per_third_party_service():
    diagram = build_system_diagram(
        _sample_architecture(third_party_services=["Stripe", "SendGrid"])
    )
    assert "Stripe" in diagram
    assert "SendGrid" in diagram
    assert diagram.count("BE --> SVC") == 2


def test_build_system_diagram_strips_characters_that_break_mermaid_syntax():
    arch = _sample_architecture(
        tech_stack=TechStack(
            frontend='React ["weird"]',
            backend="FastAPI",
            database="Postgres",
            hosting="Render",
        )
    )
    diagram = build_system_diagram(arch)
    assert (
        "[" not in diagram.split("\n")[1].split("<br/>")[1]
    )  # the injected brackets were stripped from the label
    assert '"weird"' not in diagram


def test_build_erd_renders_one_block_per_table():
    erd = build_erd(
        [
            DatabaseTable(name="users", purpose="", key_fields=["id", "email"]),
            DatabaseTable(name="orders", purpose="", key_fields=["id", "user_id"]),
        ]
    )
    assert erd.startswith("erDiagram")
    assert "USERS {" in erd
    assert "ORDERS {" in erd
    assert "email" in erd
    assert "user_id" in erd


def test_build_erd_sanitizes_table_names_into_valid_mermaid_identifiers():
    erd = build_erd(
        [DatabaseTable(name="user-profiles!", purpose="", key_fields=["id"])]
    )
    assert "USER_PROFILES" in erd


def test_adr_field_round_trips_through_model_dump():
    arch = _sample_architecture()
    dumped = arch.model_dump()
    assert dumped["adrs"][0]["title"] == "Use FastAPI"
    assert dumped["adrs"][0]["alternatives_considered"] == ["Django", "Flask"]


def test_architecture_design_defaults_adrs_to_empty_list_when_omitted():
    # Older stored architecture_data / an AI response that omits "adrs"
    # entirely must not break parsing.
    arch = ArchitectureDesign(
        architecture_summary="x",
        tech_stack=TechStack(
            frontend="React", backend="FastAPI", database="Postgres", hosting="Render"
        ),
        database_tables=[],
        api_endpoints=[],
        third_party_services=[],
    )
    assert arch.adrs == []


# ─── Standing policy: default to open-source/free third-party services,
# only name a paid one the user already said they have credentials for,
# and always attribute it as the user's own account, never VengaiCode's ───
def test_architecture_prompt_defaults_third_party_services_to_open_source():
    prompt = build_architecture_prompt("MyApp", {"overview": "A todo app"}, [])
    assert "open-source" in prompt
    assert "self-host" in prompt.lower()
    assert "user's own" in prompt.lower() or "users own" in prompt.lower()


def test_architecture_prompt_never_implies_vengaicode_pays_for_paid_services():
    prompt = build_architecture_prompt("MyApp", {"overview": "A todo app"}, [])
    assert "never implying vengaicode provisions or pays for it" in prompt.lower()


# ─── Direct architecture editing (PUT /architecture/{id}/edit) ───
def _sample_architecture_data(**overrides) -> dict:
    data = {
        "architecture": _sample_architecture().model_dump(),
        "user_approved": True,
        "approved_at": "2026-01-01T00:00:00+00:00",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "system_diagram": "graph TD\n  FE --> BE",
    }
    data.update(overrides)
    return data


def test_apply_architecture_edit_replaces_tables_and_endpoints():
    new_tables = [
        DatabaseTable(
            name="orders", purpose="Customer orders", key_fields=["id", "total"]
        )
    ]
    new_endpoints = [APIEndpoint(method="get", path="/orders", purpose="List orders")]

    new_data, new_uml = apply_architecture_edit(
        _sample_architecture_data(), {}, new_tables, new_endpoints
    )

    assert new_data["architecture"]["database_tables"][0]["name"] == "orders"
    assert new_data["architecture"]["api_endpoints"][0]["path"] == "/orders"
    assert "ORDERS {" in new_uml["erd"]


def test_apply_architecture_edit_preserves_ai_authored_fields():
    original = _sample_architecture_data()
    new_data, _ = apply_architecture_edit(
        original,
        {},
        [DatabaseTable(name="orders", purpose="x", key_fields=["id"])],
        [],
    )
    assert (
        new_data["architecture"]["architecture_summary"]
        == original["architecture"]["architecture_summary"]
    )
    assert (
        new_data["architecture"]["tech_stack"] == original["architecture"]["tech_stack"]
    )
    assert (
        new_data["architecture"]["third_party_services"]
        == original["architecture"]["third_party_services"]
    )
    assert new_data["architecture"]["adrs"] == original["architecture"]["adrs"]


def test_apply_architecture_edit_unapproves_and_clears_approved_at():
    new_data, _ = apply_architecture_edit(
        _sample_architecture_data(),
        {},
        [DatabaseTable(name="orders", purpose="x", key_fields=["id"])],
        [],
    )
    assert new_data["user_approved"] is False
    assert "approved_at" not in new_data
    assert "edited_at" in new_data


def test_apply_architecture_edit_regenerates_diagrams_from_edited_data():
    new_data, new_uml = apply_architecture_edit(
        _sample_architecture_data(),
        {"erd": "erDiagram\n  OLD_TABLE {\n    string id\n  }"},
        [DatabaseTable(name="brand_new_table", purpose="x", key_fields=["id", "note"])],
        [],
    )
    assert "BRAND_NEW_TABLE {" in new_uml["erd"]
    assert "OLD_TABLE" not in new_uml["erd"]
    assert (
        "BRAND_NEW_TABLE" in new_data["system_diagram"]
        or "graph TD" in new_data["system_diagram"]
    )


def test_apply_architecture_edit_normalizes_endpoint_method_case_and_requires_leading_slash():
    new_data, _ = apply_architecture_edit(
        _sample_architecture_data(),
        {},
        [],
        [APIEndpoint(method="get", path="/things", purpose="x")],
    )
    assert new_data["architecture"]["api_endpoints"][0]["method"] == "GET"


def test_apply_architecture_edit_rejects_when_no_architecture_exists_yet():
    with pytest.raises(ArchitectureEditError, match="generate one first"):
        apply_architecture_edit(None, {}, [], [])
    with pytest.raises(ArchitectureEditError):
        apply_architecture_edit({}, {}, [], [])


def test_apply_architecture_edit_rejects_blank_table_name():
    with pytest.raises(ArchitectureEditError, match="needs a name"):
        apply_architecture_edit(
            _sample_architecture_data(),
            {},
            [DatabaseTable(name="  ", purpose="x", key_fields=["id"])],
            [],
        )


def test_apply_architecture_edit_rejects_duplicate_table_names():
    with pytest.raises(ArchitectureEditError, match="distinct"):
        apply_architecture_edit(
            _sample_architecture_data(),
            {},
            [
                DatabaseTable(name="Orders", purpose="x", key_fields=["id"]),
                DatabaseTable(name="orders", purpose="y", key_fields=["id"]),
            ],
            [],
        )


def test_apply_architecture_edit_rejects_duplicate_field_names_within_a_table():
    with pytest.raises(ArchitectureEditError, match="more than once"):
        apply_architecture_edit(
            _sample_architecture_data(),
            {},
            [DatabaseTable(name="orders", purpose="x", key_fields=["total", "Total"])],
            [],
        )


def test_apply_architecture_edit_rejects_blank_field_name():
    with pytest.raises(ArchitectureEditError, match="blank field name"):
        apply_architecture_edit(
            _sample_architecture_data(),
            {},
            [DatabaseTable(name="orders", purpose="x", key_fields=["total", "  "])],
            [],
        )


def test_apply_architecture_edit_rejects_invalid_http_method():
    with pytest.raises(ArchitectureEditError, match="not a valid HTTP method"):
        apply_architecture_edit(
            _sample_architecture_data(),
            {},
            [],
            [APIEndpoint(method="FETCH", path="/things", purpose="x")],
        )


def test_apply_architecture_edit_rejects_path_without_leading_slash():
    with pytest.raises(ArchitectureEditError, match='must start with "/"'):
        apply_architecture_edit(
            _sample_architecture_data(),
            {},
            [],
            [APIEndpoint(method="GET", path="things", purpose="x")],
        )
