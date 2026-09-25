# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Architecture API Routes (Sprint 5)
#  api/v1/architecture.py — Generate tech stack, schema, API list
#  from approved requirements + UI/UX design, and let the user edit
#  the database schema directly.
#
#  The database schema a project's code (and its migrations) is built
#  from lives in architecture_data.architecture.database_tables. Every
#  structural rule about those tables — valid types, keys, check
#  expressions, indexes, seed rows, backend-reserved names — is decided
#  by app/ai/db_schema.py, never re-implemented here, so what this API
#  accepts is exactly what codegen can build:
#    - AI output is sanitized (invalid optional entries dropped, with a
#      note saying why) before it's ever stored
#    - a user edit that's structurally wrong is refused with EVERY
#      problem listed at once, not one per save attempt
#    - POST /{id}/validate runs the same checks without saving, so the
#      editor can show problems while the user types
#    - the ERD is derived from the resolved schema: real types, PK/FK/UK
#      markers and one correctly-cardinal relationship per foreign key
# ═══════════════════════════════════════════════════════════════

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import check_expr, db_schema
from app.ai.codegen_shared import _slug, get_ordered_pages
from app.ai.orchestrator import AIError, generate_text
from app.ai.stack_matrix import get_project_stack
from app.api.v1.auth import get_current_active_user
from app.api.v1.reverse_engineer import build_reverse_engineering_directive
from app.core.database import get_db
from app.models.project import Project, SDLCPhase
from app.models.user import User

logger = logging.getLogger("vengaicode.architecture")
router = APIRouter()


# ─── Schemas ───
class GenerateArchitectureRequest(BaseModel):
    project_id: str


class TechStack(BaseModel):
    frontend: str
    backend: str
    database: str
    hosting: str


class _Lenient(BaseModel):
    """Base for the table-level models an AI fills in. An AI that leaves
    a key out, or writes `"nullable": null`, means "the default" — not
    "reject the whole architecture" — so an explicit null on a field
    whose default isn't null is treated exactly like the key being
    absent. Whatever is still structurally wrong after that is
    db_schema's job to report (dropped with a note on generation,
    refused with a listed reason on edit), never a parse error."""

    @model_validator(mode="before")
    @classmethod
    def _null_means_default(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        return {
            key: value
            for key, value in data.items()
            if value is not None
            or key not in cls.model_fields
            or cls.model_fields[key].default is None
        }


class FieldSpec(_Lenient):
    """Optional, per-field detail layered on top of key_fields. A field
    with no FieldSpec is exactly what it always was: its type inferred
    from its name (db_schema.infer_field_type), optional, no default,
    not unique. `type` None also means "keep inferring" — so a spec can
    make a field required or unique without pinning down its type."""

    name: str = ""
    type: str | None = None  # one of db_schema.FIELD_TYPES, or None = infer
    nullable: bool = True
    default: Any = None  # canonicalized per type by db_schema on save
    unique: bool = False


class ForeignKey(_Lenient):
    field: str = ""
    references_table: str = ""  # another table's exact name
    references_field: str = "id"
    on_delete: str = "cascade"  # cascade | set_null | restrict


class CheckConstraint(_Lenient):
    name: str = ""
    expression: str = ""  # check_expr grammar — parsed, never pasted raw


class IndexSpec(_Lenient):
    fields: list[str] = []
    unique: bool = False

    @field_validator("fields", mode="before")
    @classmethod
    def _single_field_as_list(cls, value: Any) -> Any:
        # `"fields": "status"` has one unambiguous meaning.
        return [value] if isinstance(value, str) else value


class DatabaseTable(_Lenient):
    name: str = ""
    purpose: str = ""
    key_fields: list[str] = []
    # Everything below is additive and optional — a table with none of
    # this still works exactly as it always has (inferred types, no
    # keys/constraints/indexes/seed data). AI responses that omit these
    # fields entirely parse unchanged; ArchitectureDesign(**old_stored_data)
    # never breaks on a project saved before this existed.
    field_specs: list[FieldSpec] = []
    foreign_keys: list[ForeignKey] = []
    checks: list[CheckConstraint] = []
    indexes: list[IndexSpec] = []
    # Any, not dict: a malformed row is reported (or dropped from AI
    # output) by db_schema with a readable reason instead of failing
    # request parsing with an opaque 422.
    seed_rows: list[Any] = []


class APIEndpoint(BaseModel):
    method: str
    path: str
    purpose: str


class ADR(BaseModel):
    """One Architecture Decision Record — 'what was decided, and why',
    the closest thing to a real build-blueprint document this phase
    produces. Wires the previously-unused Project.architecture_data.adrs
    field the model schema already documented but nothing generated."""

    title: str
    decision: str
    rationale: str
    alternatives_considered: list[str] = []


class ArchitectureDesign(BaseModel):
    architecture_summary: str
    tech_stack: TechStack
    database_tables: list[DatabaseTable]
    api_endpoints: list[APIEndpoint]
    third_party_services: list[str]
    adrs: list[ADR] = []


class GenerateArchitectureResponse(BaseModel):
    success: bool = True
    architecture: ArchitectureDesign
    # What sanitizing the AI's tables dropped (and why), and what is
    # still wrong with them — the same fields GET /{id} returns, so a
    # client can show them without a second round trip.
    schema_notes: list[str] = []
    schema_issues: list[dict] = []


class ApproveArchitectureRequest(BaseModel):
    project_id: str
    approved: bool = True


class EditArchitectureRequest(BaseModel):
    database_tables: list[DatabaseTable]
    api_endpoints: list[APIEndpoint]


class ValidateArchitectureRequest(BaseModel):
    database_tables: list[DatabaseTable] = []
    # Accepted so the editor can post the exact body it would save, but
    # not inspected: this endpoint checks the database schema only.
    api_endpoints: list[Any] = []


# ─── Prompt builder ───
def build_stack_directive(selected_stack: dict | None) -> str:
    """
    Renders the user's explicit UI/backend/API pick (from the Stack step,
    /api/v1/stack) as a directive for the architecture prompt, so the pick
    actually reaches what the AI proposes instead of being ignored.
    """
    if not selected_stack:
        return ""

    directive = (
        f"\nThe user has EXPLICITLY chosen this tech stack — use EXACTLY this, "
        f"do not substitute a different framework or language:\n"
        f"- Frontend: {selected_stack.get('frontend_framework')} "
        f"({selected_stack.get('frontend_language')})\n"
        f"- Backend: {selected_stack.get('backend_framework')} "
        f"({selected_stack.get('backend_language')})\n"
        f"- API style: {selected_stack.get('api_style')}\n"
    )
    if not selected_stack.get("buildable_now", True):
        directive += (
            "Note: this stack is valid but not yet buildable by VengaiCode's code "
            "generator — the user has already been told code generation will "
            "substitute the closest buildable stack, so still describe the "
            "architecture in terms of their chosen stack here.\n"
        )
    return directive


def build_architecture_prompt(
    project_name: str,
    requirements: dict,
    pages: list[dict],
    selected_stack: dict | None = None,
    reverse_data: dict | None = None,
) -> str:
    features = ", ".join(requirements.get("key_features", []))
    platforms = ", ".join(requirements.get("platforms", []))
    screen_names = ", ".join(p.get("name", "") for p in pages)
    tech_hint = requirements.get("tech_recommendations", "")
    stack_directive = build_stack_directive(selected_stack)
    reverse_directive = build_reverse_engineering_directive(reverse_data)
    if reverse_directive:
        reverse_directive += (
            "Prefer recommending the SAME or a directly compatible technology to what was detected above, "
            "rather than inventing an unrelated stack — and base database_tables/api_endpoints on the real "
            'data entities/endpoints found above when they exist. Write the "adrs" entries as real decisions '
            'grounded in that detected evidence (e.g. "decision: keep the same backend framework", '
            '"rationale: it was directly detected in the source/site being reverse-engineered") rather than '
            "generic boilerplate reasoning.\n"
        )
    field_types = "|".join(f'"{t}"' for t in db_schema.FIELD_TYPES)

    return f"""You are Baby Tiger 🐯, VengaiCode's AI architecture assistant. Based on this app's approved requirements and UI/UX design, propose a simple, open-source technical architecture.

App: {project_name}
Overview: {requirements.get("overview", "")}
Key features: {features}
Platforms: {platforms}
Screens: {screen_names}
Complexity hint: {tech_hint}
{stack_directive}
{reverse_directive}
If the app is a game, favor Godot Engine for the tech stack — it's fully open-source, capable of high-end 2D/3D games, and VengaiCode can build it into a real installable APK automatically. Only suggest Open 3D Engine (O3DE) instead if the user explicitly asked for an AAA-grade engine by name — O3DE has no automated build pipeline here, so it stays a downloadable project template the user builds themselves. If the app is not a game, favor simple open-source web or mobile technologies.

Generate a JSON object with EXACTLY these fields (no markdown, no extra text, just valid JSON):
{{
  "architecture_summary": "2-3 sentences describing the overall technical approach",
  "tech_stack": {{
    "frontend": "framework/library choice + 1 sentence why it fits",
    "backend": "framework/language choice + 1 sentence why it fits",
    "database": "database choice + 1 sentence why it fits",
    "hosting": "suggested free/open-source hosting approach"
  }},
  "database_tables": [
    {{
      "name": "table_name",
      "purpose": "1 sentence",
      "key_fields": ["field1", "field2", "other_table_name_id"],
      "field_specs": [
        {{"name": "field1", "type": "string", "nullable": false, "default": null, "unique": true}},
        {{"name": "field2", "type": "decimal", "nullable": true, "default": 0, "unique": false}}
      ],
      "foreign_keys": [
        {{"field": "other_table_name_id", "references_table": "other_table_name", "references_field": "id", "on_delete": "cascade"}}
      ],
      "checks": [
        {{"name": "field2_not_negative", "expression": "field2 >= 0"}}
      ],
      "indexes": [
        {{"fields": ["field2"], "unique": false}}
      ],
      "seed_rows": []
    }}
  ],
  "api_endpoints": [
    {{"method": "GET", "path": "/resource", "purpose": "1 sentence"}}
  ],
  "third_party_services": ["service1 (why needed)", "service2 (why needed)"],
  "adrs": [
    {{"title": "short decision title", "decision": "what was decided", "rationale": "why", "alternatives_considered": ["alternative 1", "alternative 2"]}}
  ]
}}

Generate 3-6 database tables and 6-10 core API endpoints covering the key features.
Favor simple, well-known, open-source technology suitable for the app's complexity.
Use realistic REST conventions for API endpoint paths and methods.

For each table: "key_fields" stays the plain list of field names it always was. Every table
automatically gets an auto-increment "id" primary key plus "created_at"/"updated_at" timestamps —
you may list those in key_fields, but never give them a field_specs, foreign_keys or seed_rows
entry. Table and field names must start with a letter and must not be a programming keyword or
framework-reserved name (e.g. "class", "from", "import", "global", "metadata", "schema",
"collection", "errors", "options", "save", "validate") — write "class_name" or "from_date"
instead.

"field_specs" is OPTIONAL per-field detail — add an entry for a field when you know its real type,
when it is required, when it has a default, or when no two rows may share its value. "type" is
one of {field_types}; omit "type" (or set it to null) to keep the type VengaiCode infers from the
field's name. "nullable": false means the field is required. "default" is a plain value of the
field's type (a number, "text", true/false, "2024-01-31" for a date), "now" for a datetime or
"today" for a date — or null for no default. "unique": true only for a value no two rows may
share (e.g. an email or a slug).

Add a "foreign_keys" entry whenever one table's row genuinely belongs to another (e.g. an order
belongs to a customer). "field" is the local column (conventionally "{{other_table}}_id") and must
also be listed in key_fields. "references_table" must be the EXACT "name" of another table in this
same response (or of the same table, for a parent/child hierarchy). "references_field" is "id",
or a field of that table marked unique. "on_delete" is "cascade" (delete the child rows too) |
"set_null" (keep them, clear the link) | "restrict" (refuse the delete) — and "set_null" is only
allowed on a field that is nullable, never on one with "nullable": false. Foreign keys must not
form a loop between tables.

Add a "checks" entry only for a real, meaningful business rule a column value must satisfy (e.g.
a price or quantity that can't be negative) — omit it entirely rather than inventing a constraint
with no real justification. Every "expression" is parsed by a small grammar, not run as raw SQL,
and MUST follow it: {check_expr.GRAMMAR_HELP} There is no arithmetic and there are no other
functions, and an expression may only mention fields of its own table. Valid examples:
  price >= 0
  status IN ('draft', 'published', 'archived')
  rating BETWEEN 1 AND 5
  ends_on IS NULL OR ends_on >= starts_on

Add an "indexes" entry only for a field (or combination of fields) that will genuinely be
searched/filtered/sorted on often (not every field needs one); "unique": true makes that
combination unique. "seed_rows" is only for real lookup/reference data the app can't work
without (e.g. a fixed list of categories or order statuses) — one object per row keyed by field
name, never setting "id", "created_at", "updated_at" or a foreign-key field, always including
the table's required fields and satisfying its checks. Most tables need none: leave it an empty
list. All of field_specs/foreign_keys/checks/indexes/seed_rows may be empty lists when a table
has no real need for them — do not pad them out for the sake of filling every field.

"third_party_services" MUST default to free, open-source, or self-hostable options the user
doesn't need to pay for or already own an account with (e.g. self-hosted Postfix/an SMTP relay
instead of SendGrid, self-hosted MinIO instead of S3, Firebase Cloud Messaging's free tier
instead of a paid push provider). Only name a specific paid/subscription service if the user
already said, in the overview/features/conversation above, that they have their own account or
credentials for it — and even then, phrase it as using THEIR OWN key/account (e.g. "Stripe,
using the user's own API key"), never implying VengaiCode provisions or pays for it. If a
feature genuinely needs a paid capability with no realistic open-source substitute, name it
plainly but flag that it requires the user's own subscription.
Generate 3-5 ADRs (Architecture Decision Records) covering the most consequential choices
(tech stack, database, one or two key structural decisions) — each a real trade-off with a
stated rationale and the alternatives that were passed over, not a restatement of the summary.

Respond with ONLY the JSON object, nothing else."""


def parse_ai_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    cleaned = cleaned.strip()
    return json.loads(cleaned)


def sanitize_ai_tables(
    raw_tables: Any, backend: str | None
) -> tuple[list[dict], list[str]]:
    """The AI's database_tables, made safe to store. Returns (tables,
    notes).

    Each table is first parsed through DatabaseTable (lenient: omitted
    keys and nulls become defaults; a genuinely wrong shape — say
    key_fields as a string — raises ValueError, which the caller turns
    into "try again"). Then db_schema.sanitize_tables() drops every
    invalid optional entry (a check that doesn't parse, a foreign key to
    a table that doesn't exist, a seed row that breaks a constraint…)
    with a note saying what and why, instead of refusing a whole design
    over one bad detail.

    If that leaves the tables fully valid they're stored in canonical
    form (normalize_tables), exactly as a user edit would store them.
    If not, what's left is a table/field NAME problem only the user can
    resolve (a reserved word, a duplicate name) — those are stored as-is
    so the Architecture screen shows them as issues to fix, rather than
    being silently renamed or thrown away."""
    if raw_tables is None:
        raw_tables = []
    if not isinstance(raw_tables, list):
        raise ValueError("database_tables must be a list of tables.")
    shaped = [DatabaseTable.model_validate(t).model_dump() for t in raw_tables]
    cleaned, notes = db_schema.sanitize_tables(shaped, backend)
    if db_schema.validate_tables(cleaned, backend):
        return cleaned, notes
    return db_schema.normalize_tables(cleaned, backend), notes


def build_ai_architecture(
    parsed: Any, backend: str | None
) -> tuple[ArchitectureDesign, list[str]]:
    """ArchitectureDesign from the AI's parsed JSON, with its tables
    sanitized before the design is built (so what's stored, returned
    and diagrammed is the cleaned version). Raises ValueError/TypeError
    for a response that isn't a usable architecture at all."""
    if not isinstance(parsed, dict):
        raise TypeError("The architecture response wasn't a JSON object.")
    tables, notes = sanitize_ai_tables(parsed.get("database_tables"), backend)
    return ArchitectureDesign(**{**parsed, "database_tables": tables}), notes


def _mermaid_safe_text(text: str) -> str:
    """Strips characters that break Mermaid node-label syntax. Applied to
    AI-generated tech_stack/service strings before embedding them in a
    diagram, since we don't control their exact punctuation."""
    return re.sub(r'["\[\]{}<>|]', "", text).strip()[:80]


# ─── ERD text escaping ───
# Every rule below exists because Mermaid 11's real erDiagram parser
# (checked against mermaid 11.17's lexer, not guessed) rejects the
# diagram — or silently eats part of it — otherwise:
#   - An unquoted entity id that happens to be a Mermaid keyword breaks
#     the parse: "style", "class", "classDef", "end", "one", "many",
#     "to", "erDiagram", and "accTitle"/"accDescr" when followed by ":".
#     A table named "class" is stored as "class" (it already ends in s),
#     so this isn't hypothetical. Ids are therefore always QUOTED — a
#     quoted name is matched before any keyword rule — and the table's
#     human name is shown via an alias: "order_items"["Order Items"].
#   - A quoted name can't contain '"', '%', '\' or a line break.
#   - A line (outside an entity's { }) containing "direction" + spaces +
#     TB/BT/RL/LR anywhere is swallowed whole as a direction statement.
#   - "%%{" anywhere starts a Mermaid directive that runs to the next
#     "}%%" — or to the end of the diagram.
#   - Before parsing, Mermaid rewrites ="…" to ='…' inside anything that
#     looks like an HTML tag (<word … >), and that "tag" may span lines:
#     a "<b" in one label and a ">" in a later comment could flip the
#     quotes of everything in between.
#   - An attribute named exactly PK, FK or UK is read as a key marker
#     (so "string pk" is a syntax error) unless it is `backquoted`.
#   - "#name;" / "#123;" anywhere is a Mermaid entity code: a table
#     called "R#amp;D" would be drawn as "R&D". Not a parse error, but
#     not the name either. (Mermaid also drops the last ";" of a line
#     matching style…:…#…; or classDef…:…#…; — cosmetic, left alone.)
_ZERO_WIDTH_SPACE = "​"
_DIRECTION_STATEMENT = re.compile(r"(direction)(\s+)(?=(?:tb|bt|rl|lr))", re.I)
# Mermaid's entity-code pattern is JavaScript's #\w+; — ASCII \w only.
_ENTITY_CODE = re.compile(r"#(?=[A-Za-z0-9_]+;)")
_ERD_KEY_WORDS = frozenset({"pk", "fk", "uk"})
_PLAIN_ATTRIBUTE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _mermaid_plain(text: str) -> str:
    """Single-line text with the rewrites every quoted ERD string needs:
    control characters and line breaks become spaces, angle brackets
    become ‹ › (no "HTML tag" for Mermaid's pre-parse rewrite to find —
    and a renderer would have swallowed <word> as markup anyway), a run
    of % collapses to one, so "%%{" can never start a directive, and a
    zero-width space after the # of "#name;" keeps it literal text."""
    # U+FEFF counts as whitespace to Mermaid's (JavaScript) regexes but
    # not to Python's, so it's normalized here with the control chars.
    text = "".join(" " if ord(ch) < 32 or ch in "\x7f﻿" else ch for ch in text)
    text = text.replace("<", "‹").replace(">", "›")
    text = re.sub(r"%+", "%", text)
    text = _ENTITY_CODE.sub("#" + _ZERO_WIDTH_SPACE, text)
    return re.sub(r"\s+", " ", text).strip()


def _mermaid_comment(text: str) -> str:
    """An ERD attribute comment ends at the next double quote, so none
    may survive into one (see _mermaid_plain for the rest)."""
    return _mermaid_plain(text.replace('"', ""))


def _mermaid_label(text: str) -> str:
    """A table's human name as a quoted entity alias. Double quotes turn
    into single ones and % into a full-width ％ (a quoted name may hold
    neither), a backslash is dropped, and the whitespace in
    "direction TB"-like text gets a zero-width space in front of it —
    invisible when drawn, but enough that Mermaid no longer reads the
    whole line as a direction statement."""
    text = _mermaid_plain(text.replace('"', "'").replace("\\", ""))
    text = text.replace("%", "％")
    return _DIRECTION_STATEMENT.sub(rf"\1{_ZERO_WIDTH_SPACE}\2", text)


def _erd_attribute_name(column: str) -> str:
    if column.lower() in _ERD_KEY_WORDS or not _PLAIN_ATTRIBUTE_NAME.match(column):
        return f"`{column.replace('`', '')}`"
    return column


def _erd_entity_ids(schema: db_schema.ResolvedSchema) -> dict[str, str]:
    """sql_name -> quoted Mermaid entity id. The physical table name is
    what the "→ customers.id" comments point at, so it's the id too;
    db_schema already guarantees it's unique and [a-z0-9_], but the
    diagram doesn't lean on that — anything else is replaced and a
    clash gets a numeric suffix, so an id can never be shared."""
    ids: dict[str, str] = {}
    used: set[str] = set()
    for table in schema.tables:
        base = re.sub(r"[^A-Za-z0-9_]", "_", table.sql_name) or "table"
        candidate, n = base, 2
        while candidate in used:
            candidate, n = f"{base}_{n}", n + 1
        used.add(candidate)
        ids[table.sql_name] = f'"{candidate}"'
    return ids


def build_system_diagram(architecture: "ArchitectureDesign") -> str:
    """Deterministic Mermaid component diagram built straight from the
    already-structured tech_stack + third_party_services the AI call above
    just produced — no separate AI call, so it can't drift from or
    hallucinate beyond what generate_architecture actually decided."""
    ts = architecture.tech_stack
    lines = [
        "graph TD",
        f'  FE["Frontend<br/>{_mermaid_safe_text(ts.frontend)}"]',
        f'  BE["Backend<br/>{_mermaid_safe_text(ts.backend)}"]',
        f'  DB[("Database<br/>{_mermaid_safe_text(ts.database)}")]',
        "  FE --> BE",
        "  BE --> DB",
    ]
    for i, svc in enumerate(architecture.third_party_services):
        node = f"SVC{i}"
        lines.append(f'  {node}["{_mermaid_safe_text(svc)}"]')
        lines.append(f"  BE --> {node}")
    return "\n".join(lines)


_ERD_DEFAULT_MAX_CHARS = 40


def _erd_default_text(column: db_schema.ResolvedColumn) -> str | None:
    default = column.default
    if default is None:
        return None
    if default["kind"] != "literal":
        return f"default {default['kind']}"  # "now" / "today"
    value = default["value"]
    if isinstance(value, bool):
        shown = "true" if value else "false"
    elif column.type in ("string", "text"):
        shown = f"'{value}'"
    elif isinstance(value, str):
        shown = value  # decimal / date / datetime canonical text
    else:
        shown = json.dumps(value, separators=(",", ":"))
    if len(shown) > _ERD_DEFAULT_MAX_CHARS:
        shown = shown[: _ERD_DEFAULT_MAX_CHARS - 1] + "…"
    return f"default {shown}"


def _erd_column_line(column: db_schema.ResolvedColumn, unique: bool) -> str:
    keys = []
    if column.fk:
        keys.append("FK")
    if unique:
        keys.append("UK")
    notes = []
    if not column.nullable:
        notes.append("required")
    default_text = _erd_default_text(column)
    if default_text:
        notes.append(default_text)
    if column.length and column.length != db_schema.STRING_LENGTH:
        notes.append(f"max {column.length}")
    if column.fk:
        rule = column.fk.on_delete.replace("_", " ")
        notes.append(
            f"→ {column.fk.ref_table_sql}.{column.fk.ref_column} (on delete {rule})"
        )
    parts = [column.type, _erd_attribute_name(column.column)]
    if keys:
        parts.append(", ".join(keys))
    comment = _mermaid_comment(", ".join(notes))
    if comment:
        parts.append(f'"{comment}"')
    return "    " + " ".join(parts)


def _as_table_dict(table: Any) -> dict | None:
    if hasattr(table, "model_dump"):
        return table.model_dump()
    return table if isinstance(table, dict) else None


def build_erd(database_tables: list[Any]) -> str:
    """Deterministic Mermaid ERD from the architecture's own database_tables
    — same rationale as build_system_diagram: derived from structured data
    we already trust, not a second AI call that could contradict it.

    Built from db_schema's resolved schema, so every type shown is the
    type a real build produces — declared where the user/AI declared it,
    otherwise the same by-name inference codegen uses. Each table shows
    its implicit "integer id PK", then every field (no cap: a diagram
    that silently hides columns misrepresents the schema) with FK/UK
    markers and a short comment where it adds something (required,
    default, target of a foreign key). One relationship line per foreign
    key, labelled with the FK column:
        required FK  PARENT ||--o{ CHILD     optional FK  PARENT |o--o{ CHILD
        unique FK    PARENT ||--o| CHILD     (one-to-one; |o--o| if optional)

    Any table name produces a diagram Mermaid can parse: entities are
    keyed by their quoted physical table name and labelled with the
    human one, escaped per the notes above _mermaid_plain().

    Accepts Pydantic DatabaseTables or plain dicts, and never raises on
    legacy or partly-invalid data (resolve_schema(strict=False) skips
    only what can't be resolved at all — the issues themselves are
    reported separately as schema_issues)."""
    tables = [t for t in (_as_table_dict(t) for t in database_tables or []) if t]
    schema = db_schema.resolve_schema(tables, strict=False)
    # First table of a given name wins, as it does in db_schema — a later
    # duplicate (reported as an issue) mustn't reorder the first's fields.
    raw_by_name: dict[str, dict] = {}
    for raw in tables:
        raw_by_name.setdefault(str(raw.get("name") or "").strip(), raw)
    ids = _erd_entity_ids(schema)

    lines = ["erDiagram"]
    relationships = []
    for table in schema.tables:
        unique_single = {
            i.columns[0] for i in table.indexes if i.unique and len(i.columns) == 1
        }
        # Entity id = quoted physical table name; the human name is shown
        # as an alias whenever it reads differently ("customer" stored as
        # "customers", "Order Items" as "order_items").
        entity_id, label = ids[table.sql_name], _mermaid_label(table.name)
        alias = f'["{label}"]' if label and f'"{label}"' != entity_id else ""
        lines.append(f"  {entity_id}{alias} {{")
        lines.append("    integer id PK")

        # key_fields order, so the diagram reads like the editor; the
        # implicit timestamps only when the user listed them, and any
        # column only key_fields didn't mention (a foreign-key field
        # sanitizing added) at the end.
        emitted: set[str] = {"id"}
        raw_fields = raw_by_name.get(table.name, {}).get("key_fields") or []
        order = [_slug(str(f)) for f in raw_fields if str(f or "").strip()]
        order += [c.column for c in table.columns]
        for slug in order:
            if slug in emitted:
                continue
            column = table.column(slug)
            if column is not None:
                lines.append(
                    _erd_column_line(
                        column, column.unique or column.column in unique_single
                    )
                )
            elif slug in db_schema.IMPLICIT_COLUMN_TYPES:
                lines.append(
                    f'    {db_schema.IMPLICIT_COLUMN_TYPES[slug]} {slug} "set automatically"'
                )
            else:
                continue
            emitted.add(slug)
        lines.append("  }")

        for column in table.columns:
            if column.fk is None or column.fk.ref_table_sql not in ids:
                continue
            parent_side = "|o" if column.nullable else "||"
            one_to_one = column.unique or column.column in unique_single
            child_side = "o|" if one_to_one else "o{"
            relationships.append(
                f"  {ids[column.fk.ref_table_sql]} {parent_side}--{child_side} "
                f'{ids[table.sql_name]} : "{column.column}"'
            )

    return "\n".join(lines + relationships)


def resolved_tables_payload(schema: db_schema.ResolvedSchema) -> list[dict]:
    """The resolved (typed) tables as the desktop/mobile editors consume
    them — what each field WILL be once built, including types inferred
    from names, so the editor can show "string (inferred)" rather than
    leaving the user to guess. Table order follows the editor's order,
    not creation order."""
    return [
        {
            "name": table.name,
            "sql_name": table.sql_name,
            "columns": [
                {
                    "name": column.name,
                    "column": column.column,
                    "type": column.type,
                    "declared": column.declared,
                    "nullable": column.nullable,
                    "unique": column.unique,
                    "default": db_schema.default_storage_value(column.default),
                    "fk": None
                    if column.fk is None
                    else {
                        "table": column.fk.ref_table,
                        "table_sql": column.fk.ref_table_sql,
                        "column": column.fk.ref_column,
                        "on_delete": column.fk.on_delete,
                    },
                }
                for column in table.columns
            ],
            "checks": [{"name": chk.name, "sql": chk.sql} for chk in table.checks],
            "indexes": [
                {"name": idx.name, "columns": list(idx.columns), "unique": idx.unique}
                for idx in table.indexes
            ],
            "seed_row_count": len(table.seed_rows),
        }
        for table in schema.tables
    ]


def schema_view(database_tables: list[Any], backend: str | None) -> dict:
    """The live, derived view of a set of tables that Architecture
    responses carry: {"schema_issues", "resolved_tables", "erd"}.

    Never raises — it runs on read paths over legacy and AI-authored
    data, where one unexpected shape must not take the whole
    Architecture screen down. If analysis does fail, that is reported
    as an issue rather than an empty (i.e. "valid") list."""
    tables = [t for t in (_as_table_dict(t) for t in database_tables or []) if t]
    try:
        issues = db_schema.validate_tables(tables, backend)
        resolved = db_schema.resolve_schema(tables, backend, strict=False)
        return {
            "schema_issues": [issue.to_dict() for issue in issues],
            "resolved_tables": resolved_tables_payload(resolved),
            "erd": build_erd(tables),
        }
    except Exception:
        logger.exception("Couldn't analyze database tables")
        return {
            "schema_issues": [
                {
                    "table": None,
                    "kind": "table",
                    "index": None,
                    "message": "These tables couldn't be checked — re-save them from "
                    "the editor to see what needs fixing.",
                }
            ],
            "resolved_tables": [],
            "erd": None,
        }


def _project_backend(project: Project) -> str | None:
    """The backend codegen will actually build for this project (a
    stack_matrix key like "fastapi"/"express"), which decides which
    names are reserved. None skips the reserved-name checks — never a
    reason to fail a request."""
    try:
        return get_project_stack(project)["backend_framework"]
    except Exception:
        logger.warning("Couldn't resolve project %s's backend", project.id)
        return None


def _saved_tables(architecture_data: dict | None) -> list[dict]:
    architecture = (architecture_data or {}).get("architecture")
    if not isinstance(architecture, dict):
        return []
    tables = architecture.get("database_tables")
    if not isinstance(tables, list):
        return []
    return [t for t in tables if isinstance(t, dict)]


class ArchitectureEditError(RuntimeError):
    """A failure with a message meant for the user, not a stack trace."""


_VALID_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


def _validate_tables(tables: list[Any], backend: str | None = None) -> None:
    """Structural validation, delegated entirely to db_schema — the same
    rules codegen and migrations are built on, so a schema accepted here
    can always be generated. Same refuse-on-ambiguity philosophy as the
    deterministic Page Engine: nothing is silently guessed at or dropped.
    Every problem is listed at once, so fixing a schema never turns into
    a save / read one error / save again loop."""
    issues = db_schema.validate_tables(tables, backend)
    if issues:
        raise ArchitectureEditError(
            "Fix these before saving:\n"
            + db_schema.format_issues(issues, limit=len(issues))
        )


def _validate_endpoints(endpoints: list[APIEndpoint]) -> None:
    for endpoint in endpoints:
        method = (endpoint.method or "").strip().upper()
        if method not in _VALID_HTTP_METHODS:
            raise ArchitectureEditError(
                f'"{endpoint.method}" is not a valid HTTP method — use one of '
                f"{', '.join(sorted(_VALID_HTTP_METHODS))}."
            )
        endpoint.method = method

        path = (endpoint.path or "").strip()
        if not path.startswith("/"):
            raise ArchitectureEditError(
                f'Endpoint path "{endpoint.path}" must start with "/".'
            )
        endpoint.path = path


def apply_architecture_edit(
    architecture_data: dict | None,
    uml_diagrams: dict | None,
    database_tables: list[DatabaseTable],
    api_endpoints: list[APIEndpoint],
    *,
    backend: str | None = None,
) -> tuple[dict, dict]:
    """Rebuilds the saved ArchitectureDesign with user-edited tables and
    endpoints, leaving every AI-authored field (summary, tech_stack,
    third_party_services, adrs) untouched, then regenerates the
    deterministic diagrams from the EDITED data via the exact same
    build_system_diagram()/build_erd() generate_architecture() itself
    uses — so an edited diagram is never stale or hand-drawn, just a
    live view of whatever is currently saved.

    The tables are validated against `backend` (the project's codegen
    backend — it decides which names are reserved) and stored in
    db_schema's canonical form: trimmed names, lower-cased types and
    rules, canonical defaults/seed values, foreign keys pointing at the
    referenced table's exact name, no-op field_specs removed. Canonical
    storage is what lets a later migration diff compare like with like.

    Both the AI codegen path (codegen_runner.build_context()) and the
    deterministic codegen path (codegen_deterministic.py) read straight
    from architecture_data.architecture.{database_tables,api_endpoints}
    — an edit made here is honored by the next codegen run with zero
    codegen-side changes, the same way approving the AI's first draft
    always has been.

    Un-approves the architecture (codegen is gated on
    architecture_data["user_approved"]): an edit is a real change the
    user should re-review before it drives a build.
    """
    if not (architecture_data or {}).get("architecture"):
        raise ArchitectureEditError(
            "No architecture exists yet to edit — generate one first."
        )

    _validate_tables(database_tables, backend)
    _validate_endpoints(api_endpoints)
    normalized = db_schema.normalize_tables(database_tables, backend)

    current = ArchitectureDesign(**architecture_data["architecture"])
    updated = current.model_copy(
        update={
            "database_tables": [DatabaseTable(**t) for t in normalized],
            "api_endpoints": api_endpoints,
        }
    )

    new_architecture_data = dict(architecture_data)
    new_architecture_data["architecture"] = updated.model_dump()
    new_architecture_data["system_diagram"] = build_system_diagram(updated)
    new_architecture_data["user_approved"] = False
    new_architecture_data.pop("approved_at", None)
    new_architecture_data["edited_at"] = datetime.now(timezone.utc).isoformat()

    new_uml_diagrams = {
        **(uml_diagrams or {}),
        "erd": build_erd(updated.database_tables),
    }

    return new_architecture_data, new_uml_diagrams


_PLANNING_FAILED = (
    "Baby Tiger had trouble planning your architecture. Please try again! 🐯"
)


async def _get_owned_project(db: AsyncSession, project_id: str, user: User) -> Project:
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.user_id == user.id,
        )
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found."
        )
    return project


@router.post(
    "/generate",
    response_model=GenerateArchitectureResponse,
    summary="Generate architecture from approved requirements + UI/UX",
)
async def generate_architecture(
    payload: GenerateArchitectureRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Takes the approved requirements + UI/UX design and generates a
    technical architecture — tech stack, database schema, API endpoints.
    """
    project = await _get_owned_project(db, payload.project_id, user)

    if not project.uiux_data or not project.uiux_data.get("user_approved"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="UI/UX design must be approved before generating architecture.",
        )

    frd = (project.requirements_data or {}).get("frd", {})
    pages = get_ordered_pages(project.uiux_data)
    backend = _project_backend(project)

    try:
        prompt = build_architecture_prompt(
            project.name,
            frd,
            pages,
            project.selected_stack,
            project.reverse_engineering_data,
        )
        ai_result = await generate_text(prompt, user=user, db=db)
        parsed = parse_ai_json(ai_result["text"])
    except AIError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)
        )
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.error(f"Failed to parse AI architecture response: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=_PLANNING_FAILED
        )

    try:
        architecture, schema_notes = build_ai_architecture(parsed, backend)
    except (ValueError, TypeError) as e:
        # ValueError includes Pydantic's ValidationError: a response whose
        # SHAPE is unusable (a problem inside a table is not — that's
        # sanitized away with a note) is worth one more try, not a 500.
        logger.error(f"AI architecture response had an unusable shape: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=_PLANNING_FAILED
        )

    project.architecture_data = {
        "architecture": architecture.model_dump(),
        "user_approved": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        # Deterministic (no AI call) — derived from the architecture object
        # right above, so these can't drift from or contradict it.
        "system_diagram": build_system_diagram(architecture),
        "schema_notes": schema_notes,
    }
    project.uml_diagrams = {
        **(project.uml_diagrams or {}),
        "erd": build_erd(architecture.database_tables),
    }
    await db.commit()

    view = schema_view(architecture.database_tables, backend)
    return GenerateArchitectureResponse(
        architecture=architecture,
        schema_notes=schema_notes,
        schema_issues=view["schema_issues"],
    )


@router.get(
    "/{project_id}",
    summary="Get saved architecture design",
)
async def get_architecture(
    project_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve a previously generated architecture design, with a live
    analysis of its tables: structural issues (against the backend
    codegen will actually build), the resolved typed schema, and an ERD
    rebuilt from the saved tables — so a project saved before the ERD
    showed types/keys gets the current diagram without a re-save."""
    project = await _get_owned_project(db, project_id, user)

    if not project.architecture_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No architecture generated yet.",
        )

    view = schema_view(
        _saved_tables(project.architecture_data), _project_backend(project)
    )
    return {
        "success": True,
        "architecture": project.architecture_data.get("architecture"),
        "user_approved": project.architecture_data.get("user_approved", False),
        "generated_at": project.architecture_data.get("generated_at"),
        "system_diagram": project.architecture_data.get("system_diagram"),
        "erd": view["erd"] or (project.uml_diagrams or {}).get("erd"),
        "schema_issues": view["schema_issues"],
        "schema_notes": project.architecture_data.get("schema_notes") or [],
        "resolved_tables": view["resolved_tables"],
    }


@router.put(
    "/{project_id}/edit",
    summary="Directly edit the saved architecture's tables/endpoints (no AI call)",
)
async def edit_architecture(
    project_id: str,
    payload: EditArchitectureRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Lets a user add/rename/remove tables, fields and endpoints directly,
    and declare field types, keys, checks, indexes and seed rows, instead
    of only reviewing what the AI proposed. See apply_architecture_edit()'s
    docstring for why this needs no codegen or packaging changes to take
    effect on a later build.
    """
    project = await _get_owned_project(db, project_id, user)
    backend = _project_backend(project)

    try:
        new_architecture_data, new_uml_diagrams = apply_architecture_edit(
            project.architecture_data,
            project.uml_diagrams,
            payload.database_tables,
            payload.api_endpoints,
            backend=backend,
        )
    except ArchitectureEditError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e

    project.architecture_data = new_architecture_data
    project.uml_diagrams = new_uml_diagrams
    await db.commit()

    view = schema_view(_saved_tables(new_architecture_data), backend)
    return {
        "success": True,
        "architecture": new_architecture_data.get("architecture"),
        "user_approved": False,
        "generated_at": new_architecture_data.get("generated_at"),
        "system_diagram": new_architecture_data.get("system_diagram"),
        "erd": new_uml_diagrams.get("erd"),
        "schema_issues": view["schema_issues"],
        "schema_notes": new_architecture_data.get("schema_notes") or [],
        "resolved_tables": view["resolved_tables"],
        "message": "Changes saved — review and approve again before generating code.",
    }


@router.post(
    "/{project_id}/validate",
    summary="Check edited tables without saving them (no AI call)",
)
async def validate_architecture(
    project_id: str,
    payload: ValidateArchitectureRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Runs exactly the checks PUT /{project_id}/edit would, against the
    project's own backend, and returns every issue plus the ERD and
    resolved tables those edits would produce — so the editor can show
    problems as the user makes them. Saves nothing, never answers 400
    for a schema problem (that's the whole point of asking), and works
    before any architecture exists: the project only has to be the
    user's.
    """
    project = await _get_owned_project(db, project_id, user)
    view = schema_view(payload.database_tables, _project_backend(project))
    return {
        "success": True,
        "valid": not view["schema_issues"],
        "issues": view["schema_issues"],
        "erd": view["erd"],
        "resolved_tables": view["resolved_tables"],
    }


@router.post(
    "/approve",
    summary="Approve architecture and move to next phase",
)
async def approve_architecture(
    payload: ApproveArchitectureRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """User approves the generated architecture. Marks phase complete."""
    project = await _get_owned_project(db, payload.project_id, user)

    if not project.architecture_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No architecture to approve.",
        )

    # Reassign the whole dict — required for SQLAlchemy JSON column
    # change tracking (in-place mutation is not detected)
    architecture_data = dict(project.architecture_data)
    architecture_data["user_approved"] = payload.approved
    architecture_data["approved_at"] = datetime.now(timezone.utc).isoformat()
    project.architecture_data = architecture_data

    if payload.approved:
        phases = project.phases_completed or []
        if "architecture" not in phases:
            phases.append("architecture")
        project.phases_completed = phases
        project.progress_percent = project.get_progress_percent()
        project.current_phase = SDLCPhase.API_BUILDER

    await db.commit()

    return {
        "success": True,
        "message": "Architecture approved! Next: API Builder 🐯"
        if payload.approved
        else "Feedback noted.",
        "progress_percent": project.progress_percent,
    }
