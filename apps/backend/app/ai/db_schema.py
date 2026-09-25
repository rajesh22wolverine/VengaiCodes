# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Typed Database Schema (single source of truth)
#  ai/db_schema.py — Turns an Architecture's database_tables (names +
#  key_fields, optionally enriched with field_specs / foreign_keys /
#  checks / indexes / seed_rows) into ONE resolved, validated, typed
#  schema that every consumer reads from:
#
#    - architecture.py      structural validation on edit (refuses with
#                           every problem listed), AI-output sanitizing,
#                           and the Mermaid ERD
#    - codegen_deterministic.py   SQLAlchemy / Mongoose models, typed
#                           routes and typed screens
#    - migrations_gen.py    Alembic / migrate-mongo migrations, built by
#                           diffing two snapshot() outputs
#    - the AI codegen adapters    describe_table_for_prompt()
#
#  Everything that must agree between a model file and its migration —
#  column type, nullability, server default, constraint names — is
#  decided HERE, once, so the two can't drift. Same philosophy as the
#  rest of the deterministic pipeline: a declared fact wins; anything
#  undeclared falls back to the same by-name heuristic the no-AI codegen
#  has always used; anything ambiguous or broken is refused with a
#  message a user can act on, never silently guessed at.
#
#  Backward compatibility: a table with only {name, purpose, key_fields}
#  (every project saved before this existed) resolves to exactly the
#  column types the deterministic generator already produced for it.
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations

import copy
import hashlib
import json
import keyword
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.ai import check_expr, knowledge
from app.ai.codegen_shared import _pascal, _slug

FIELD_TYPES: tuple[str, ...] = (
    "string",
    "text",
    "integer",
    "float",
    "decimal",
    "boolean",
    "date",
    "datetime",
    "json",
)
ON_DELETE_RULES: tuple[str, ...] = ("cascade", "set_null", "restrict")

# Columns every generated table gets without the user listing them.
# They can be referenced by checks and indexes, but not re-declared.
IMPLICIT_COLUMN_TYPES: dict[str, str] = {
    "id": "integer",
    "created_at": "datetime",
    "updated_at": "datetime",
}

STRING_LENGTH = 255
URL_LENGTH = 500
DECIMAL_PRECISION = 12
DECIMAL_SCALE = 2
MAX_IDENTIFIER_LENGTH = 63  # Postgres truncates longer names silently
MAX_TABLE_SLUG_LENGTH = 50  # leaves room for plural + constraint prefixes
MAX_FIELD_SLUG_LENGTH = 60
MAX_SEED_ROWS = 200
MAX_INDEX_COLUMNS = 8

PYTHON_BACKENDS = frozenset({"fastapi", "flask", "django"})
MONGOOSE_BACKENDS = frozenset({"express"})

_IDENT_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# Python keywords can't be attribute or module names (a "from" field
# would make `from = sa.Column(...)` a SyntaxError), and SQLAlchemy's
# declarative base reserves these two attribute names outright.
_PYTHON_RESERVED = frozenset(k.lower() for k in keyword.kwlist) | {
    "metadata",
    "registry",
}

# Field names the deterministic FastAPI generator can't give a column:
# "sa" is its name for the sqlalchemy module inside every model class body
# (a column called sa would replace it halfway through the class), and
# these are real methods/attributes of Pydantic's BaseModel, which the
# generated request models subclass — Pydantic refuses a field that
# replaces one outright (NameError at import).
_FASTAPI_FIELD_RESERVED = frozenset(
    {
        "sa",
        "model_config",
        "model_computed_fields",
        "model_construct",
        "model_copy",
        "model_dump",
        "model_dump_json",
        "model_extra",
        "model_fields",
        "model_fields_set",
        "model_json_schema",
        "model_parametrized_name",
        "model_post_init",
        "model_rebuild",
        "model_validate",
        "model_validate_json",
        "model_validate_strings",
    }
)

# Mongoose refuses (or silently breaks on) these as schema paths — see
# Schema.reserved in Mongoose's own source.
_MONGOOSE_RESERVED = frozenset(
    {
        "collection",
        "db",
        "emit",
        "errors",
        "get",
        "init",
        "ismodified",
        "isnew",
        "listeners",
        "modelname",
        "on",
        "once",
        "options",
        "populated",
        "remove",
        "removelistener",
        "save",
        "schema",
        "set",
        "toobject",
        "validate",
    }
)

_ON_DELETE_ALIASES = {
    "cascade": "cascade",
    "set_null": "set_null",
    "set null": "set_null",
    "setnull": "set_null",
    "null": "set_null",
    "restrict": "restrict",
    "no_action": "restrict",
    "no action": "restrict",
    "protect": "restrict",
}


# ───────────────────────────────────────────────
#  By-name type inference (moved here from codegen_deterministic.py,
#  unchanged, so undeclared fields keep resolving exactly as before)
# ───────────────────────────────────────────────
_CATEGORY_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"email"), "email"),
    (re.compile(r"url|link|href|website"), "url"),
    (
        re.compile(
            r"price|amount|total|cost|rating|score|percent|rate|weight|latitude|longitude"
        ),
        "float",
    ),
    (
        re.compile(r"count|quantity|qty|number|num|age|year|stock|inventory|duration"),
        "int",
    ),
    (re.compile(r"^is_|^has_"), "bool"),
    (re.compile(r"_at$|_date$|^date|^time|timestamp"), "datetime"),
    (re.compile(r"description|bio|notes|content|body|summary|address"), "text"),
]

_TYPE_BY_CATEGORY = {
    "email": "string",
    "url": "string",
    "float": "float",
    "int": "integer",
    "bool": "boolean",
    "datetime": "datetime",
    "text": "text",
    "string": "string",
}


def classify_field(field_name: str) -> str:
    """The legacy by-name category (email/url/float/int/bool/datetime/
    text/string). Kept distinct from infer_field_type() because email
    vs url still differ in string length."""
    lowered = field_name.lower()
    for pattern, category in _CATEGORY_RULES:
        if pattern.search(lowered):
            return category
    return "string"


def infer_field_type(field_name: str) -> str:
    return _TYPE_BY_CATEGORY[classify_field(field_name)]


def table_sql_name(name: str) -> str:
    """The physical table / MongoDB collection name — the same plural
    slug the deterministic generator has always used for routes."""
    slug = _slug(name)
    return slug if slug.endswith("s") else f"{slug}s"


def constraint_name(prefix: str, table_sql: str, *parts: str) -> str:
    """Deterministic, Postgres-safe (<= 63 chars) constraint/index name.
    Explicit names everywhere are what let a later migration drop or
    alter a constraint by name, including on SQLite batch mode."""
    base = re.sub(r"[^a-z0-9_]", "_", "_".join((prefix, table_sql, *parts)).lower())
    if len(base) <= MAX_IDENTIFIER_LENGTH:
        return base
    digest = hashlib.sha1(base.encode()).hexdigest()[:8]
    return f"{base[: MAX_IDENTIFIER_LENGTH - 9]}_{digest}"


# ───────────────────────────────────────────────
#  Value coercion (defaults + seed rows)
# ───────────────────────────────────────────────
class _CoercionError(ValueError):
    pass


_TRUE_WORDS = {"true", "yes", "1", "on"}
_FALSE_WORDS = {"false", "no", "0", "off"}


def coerce_value(value: Any, field_type: str) -> Any:
    """Converts a user/AI-supplied value to the canonical stored form
    for a column type, or raises _CoercionError with a readable reason.
    Canonical forms (all JSON-serializable): integer -> int, float ->
    float, decimal -> str (exact, e.g. "9.99"), boolean -> bool,
    string/text -> str, date -> "YYYY-MM-DD", datetime -> ISO 8601
    string, json -> any JSON value."""
    if field_type in ("string", "text"):
        if isinstance(value, (dict, list)):
            raise _CoercionError("expected text")
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)
    if field_type == "integer":
        if isinstance(value, bool):
            raise _CoercionError("expected a whole number")
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        try:
            return int(str(value).strip())
        except ValueError:
            raise _CoercionError("expected a whole number") from None
    if field_type == "float":
        if isinstance(value, bool):
            raise _CoercionError("expected a number")
        try:
            return float(str(value).strip())
        except ValueError:
            raise _CoercionError("expected a number") from None
    if field_type == "decimal":
        if isinstance(value, bool):
            raise _CoercionError("expected a number")
        try:
            number = Decimal(str(value).strip())
        except InvalidOperation:
            raise _CoercionError("expected a number") from None
        if not number.is_finite():
            raise _CoercionError("expected a finite number")
        quantized = number.quantize(Decimal(1).scaleb(-DECIMAL_SCALE))
        if quantized != number:
            raise _CoercionError(f"only {DECIMAL_SCALE} decimal places are stored")
        if abs(quantized) >= Decimal(10) ** (DECIMAL_PRECISION - DECIMAL_SCALE):
            raise _CoercionError("number is too large")
        return str(quantized)
    if field_type == "boolean":
        if isinstance(value, bool):
            return value
        word = str(value).strip().lower()
        if word in _TRUE_WORDS:
            return True
        if word in _FALSE_WORDS:
            return False
        raise _CoercionError("expected true or false")
    if field_type == "date":
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        try:
            return date.fromisoformat(str(value).strip()).isoformat()
        except ValueError:
            raise _CoercionError("expected a date like 2024-01-31") from None
    if field_type == "datetime":
        if isinstance(value, datetime):
            return value.isoformat()
        text = str(value).strip()
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat()
        except ValueError:
            raise _CoercionError(
                "expected a date/time like 2024-01-31T09:30:00"
            ) from None
    if field_type == "json":
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                raise _CoercionError("expected valid JSON") from None
        try:
            json.dumps(value)
        except (TypeError, ValueError):
            raise _CoercionError("expected valid JSON") from None
        return value
    raise _CoercionError(f"unknown type {field_type}")


def normalize_default(value: Any, field_type: str) -> dict | None:
    """None, or {"kind": "now"} / {"kind": "today"} / {"kind": "literal",
    "value": canonical}. Raises _CoercionError for an invalid default."""
    if value is None or (
        isinstance(value, str)
        and not value.strip()
        and field_type not in ("string", "text")
    ):
        return None
    if isinstance(value, str):
        word = value.strip().lower()
        if field_type == "datetime" and word in ("now", "now()", "current_timestamp"):
            return {"kind": "now"}
        if field_type == "date" and word in ("today", "current_date"):
            return {"kind": "today"}
    return {"kind": "literal", "value": coerce_value(value, field_type)}


def default_storage_value(default: dict | None) -> Any:
    """How a normalized default is stored back on a FieldSpec."""
    if default is None:
        return None
    if default["kind"] in ("now", "today"):
        return default["kind"]
    return default["value"]


# ───────────────────────────────────────────────
#  Issues
# ───────────────────────────────────────────────
@dataclass(frozen=True)
class SchemaIssue:
    table_index: int | None
    table: str | None
    kind: str  # table | field | field_spec | foreign_key | check | index | seed_row
    index: int | None
    message: str

    def to_dict(self) -> dict:
        return {
            "table": self.table,
            "kind": self.kind,
            "index": self.index,
            "message": self.message,
        }


class SchemaValidationError(ValueError):
    def __init__(self, issues: list[SchemaIssue]):
        self.issues = issues
        super().__init__(format_issues(issues))


def format_issues(issues: list[SchemaIssue], limit: int = 12) -> str:
    lines = [f"• {i.message}" for i in issues[:limit]]
    if len(issues) > limit:
        lines.append(f"• …and {len(issues) - limit} more.")
    return "\n".join(lines)


# ───────────────────────────────────────────────
#  Resolved schema
# ───────────────────────────────────────────────
@dataclass(frozen=True)
class ResolvedForeignKey:
    ref_table: str  # referenced table's display name
    ref_table_sql: str  # its physical table / collection name
    ref_class: str  # its PascalCase model name
    ref_column: str  # referenced column slug ("id" by default)
    on_delete: str  # cascade | set_null | restrict
    constraint_name: str


@dataclass(frozen=True)
class ResolvedColumn:
    name: str  # as listed in key_fields
    column: str  # slug — the physical column / attribute name
    type: str  # one of FIELD_TYPES
    declared: bool  # True if the type came from a field_spec
    nullable: bool
    default: dict | None  # see normalize_default()
    unique: bool
    length: int | None  # only for "string"
    fk: ResolvedForeignKey | None
    unique_constraint_name: str | None

    def snapshot(self) -> dict:
        return {
            "type": self.type,
            "length": self.length,
            "nullable": self.nullable,
            "default": self.default,
            "unique": self.unique_constraint_name,
            "fk": None
            if self.fk is None
            else {
                "table": self.fk.ref_table_sql,
                "column": self.fk.ref_column,
                "on_delete": self.fk.on_delete,
                "name": self.fk.constraint_name,
            },
        }


@dataclass(frozen=True)
class ResolvedCheck:
    name: str
    constraint_name: str
    expression: str  # the text as written
    ast: dict  # bound to column slugs — see check_expr.py
    sql: str
    fields: tuple[str, ...]


@dataclass(frozen=True)
class ResolvedIndex:
    name: str
    columns: tuple[str, ...]
    unique: bool


@dataclass(frozen=True)
class ResolvedTable:
    name: str
    slug: str
    sql_name: str
    class_name: str
    purpose: str
    columns: tuple[ResolvedColumn, ...]
    checks: tuple[ResolvedCheck, ...]
    indexes: tuple[ResolvedIndex, ...]
    seed_rows: tuple[dict, ...]  # keyed by column slug, canonical values

    def column(self, slug: str) -> ResolvedColumn | None:
        return next((c for c in self.columns if c.column == slug), None)

    def column_types(self) -> dict[str, str]:
        return {**IMPLICIT_COLUMN_TYPES, **{c.column: c.type for c in self.columns}}


@dataclass(frozen=True)
class ResolvedSchema:
    tables: tuple[ResolvedTable, ...]
    creation_order: tuple[str, ...] = field(default=())  # sql names, parents first

    def table(self, name_or_sql: str) -> ResolvedTable | None:
        return next(
            (t for t in self.tables if name_or_sql in (t.name, t.sql_name, t.slug)),
            None,
        )

    def ordered_tables(self) -> list[ResolvedTable]:
        by_sql = {t.sql_name: t for t in self.tables}
        return [by_sql[s] for s in self.creation_order if s in by_sql]

    def referencing(self, table_sql: str) -> list[tuple[ResolvedTable, ResolvedColumn]]:
        """Every (child table, FK column) pointing at table_sql — what an
        app-level ON DELETE implementation (MongoDB) has to visit."""
        out = []
        for t in self.tables:
            for c in t.columns:
                if c.fk and c.fk.ref_table_sql == table_sql:
                    out.append((t, c))
        return out


# ───────────────────────────────────────────────
#  Analysis — validation and resolution in one pass
# ───────────────────────────────────────────────
def _as_dict(table: Any) -> dict:
    if hasattr(table, "model_dump"):
        return table.model_dump()
    return dict(table or {})


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


@dataclass
class _TableInfo:
    index: int
    name: str
    slug: str
    sql_name: str
    raw: dict
    fields: dict[str, str]  # slug -> display name (key_fields order, implicit excluded)
    specs: dict[str, dict]  # slug -> {"type","nullable","default_raw","unique"}


def _reserved_reason(slug: str, backend: str | None, field: bool = False) -> str | None:
    if backend in PYTHON_BACKENDS and slug in _PYTHON_RESERVED:
        return "a reserved word in Python/SQLAlchemy"
    if field and backend == "fastapi" and slug in _FASTAPI_FIELD_RESERVED:
        return "a name the generated SQLAlchemy/Pydantic code already uses"
    if backend in MONGOOSE_BACKENDS and slug in _MONGOOSE_RESERVED:
        return "a reserved name in Mongoose"
    return None


def _analyze(
    tables_in: list[Any], backend: str | None
) -> tuple[list[SchemaIssue], ResolvedSchema]:
    issues: list[SchemaIssue] = []
    tables = [_as_dict(t) for t in (tables_in or [])]

    def add(info_or_index, kind: str, index: int | None, message: str) -> None:
        if isinstance(info_or_index, _TableInfo):
            issues.append(
                SchemaIssue(
                    info_or_index.index, info_or_index.name, kind, index, message
                )
            )
        else:
            ti, tname = info_or_index
            issues.append(SchemaIssue(ti, tname, kind, index, message))

    # ── Phase A: table names ──
    infos: list[_TableInfo] = []
    by_slug: dict[str, _TableInfo] = {}
    by_sql: dict[str, _TableInfo] = {}
    by_class: dict[str, _TableInfo] = {}
    for ti, raw in enumerate(tables):
        name = str(raw.get("name") or "").strip()
        if not name:
            add((ti, None), "table", None, "Every table needs a name.")
            continue
        slug = _slug(name)
        if not _IDENT_RE.match(slug):
            add(
                (ti, name),
                "table",
                None,
                f'Table name "{name}" has to start with a letter.',
            )
            continue
        if len(slug) > MAX_TABLE_SLUG_LENGTH:
            add(
                (ti, name),
                "table",
                None,
                f'Table name "{name}" is too long (max {MAX_TABLE_SLUG_LENGTH} characters).',
            )
            continue
        # knowledge.table_problem: a model class the chosen stack's language
        # or framework can't have (a keyword, or a standard type it'd shadow).
        reason = _reserved_reason(slug, backend) or knowledge.table_problem(
            slug, backend
        )
        if reason:
            add(
                (ti, name),
                "table",
                None,
                f'Table name "{name}" can\'t be used — "{slug}" is {reason}.',
            )
            continue
        if slug in by_slug:
            add(
                (ti, name),
                "table",
                None,
                f'Two tables both resolve to "{slug}" — table names must be distinct.',
            )
            continue
        sql_name = table_sql_name(name)
        if sql_name in by_sql:
            add(
                (ti, name),
                "table",
                None,
                f'"{name}" and "{by_sql[sql_name].name}" would both be stored in the table "{sql_name}" — rename one.',
            )
            continue
        class_name = _pascal(name)
        if class_name in by_class:
            # "a1b" and "a 1b" are distinct tables with distinct slugs, but
            # every generator names the model class the same — two classes
            # (and, on MongoDB, two models) called A1b.
            add(
                (ti, name),
                "table",
                None,
                f'"{name}" and "{by_class[class_name].name}" would both become the model "{class_name}" — rename one.',
            )
            continue
        info = _TableInfo(ti, name, slug, sql_name, raw, {}, {})
        infos.append(info)
        by_slug[slug] = info
        by_sql[sql_name] = info
        by_class[class_name] = info

    def find_table(ref: Any) -> _TableInfo | None:
        text = str(ref or "").strip()
        if not text:
            return None
        exact = [i for i in infos if i.name == text]
        if exact:
            return exact[0]
        ref_slug = _slug(text)
        return (
            by_slug.get(ref_slug)
            or by_sql.get(ref_slug)
            or by_sql.get(table_sql_name(text))
        )

    # ── Phase B: fields and field_specs ──
    for info in infos:
        for fi, f in enumerate(info.raw.get("key_fields") or []):
            fname = str(f or "").strip()
            if not fname:
                add(info, "field", fi, f'Table "{info.name}" has a blank field name.')
                continue
            fslug = _slug(fname)
            if fslug in IMPLICIT_COLUMN_TYPES:
                # Listing id/created_at/updated_at is harmless (they exist
                # anyway) but listing one twice is still a duplicate.
                if f"__implicit__{fslug}" in info.fields:
                    add(
                        info,
                        "field",
                        fi,
                        f'Table "{info.name}" has the field "{fname}" more than once.',
                    )
                info.fields.setdefault(f"__implicit__{fslug}", fname)
                continue
            if not _IDENT_RE.match(fslug):
                add(
                    info,
                    "field",
                    fi,
                    f'Field "{fname}" in "{info.name}" has to start with a letter.',
                )
                continue
            if len(fslug) > MAX_FIELD_SLUG_LENGTH:
                add(
                    info,
                    "field",
                    fi,
                    f'Field "{fname}" in "{info.name}" is too long (max {MAX_FIELD_SLUG_LENGTH} characters).',
                )
                continue
            # knowledge.field_problem: the field as the chosen stack's code names
            # it — a keyword there, a name the framework uses, or (C#) its class's name.
            reason = _reserved_reason(
                fslug, backend, field=True
            ) or knowledge.field_problem(fslug, backend, info.name)
            if reason:
                add(
                    info,
                    "field",
                    fi,
                    f'Field "{fname}" in "{info.name}" can\'t be used — "{fslug}" is {reason}. '
                    f'Rename it (e.g. "{fslug}_value").',
                )
                continue
            if fslug in info.fields:
                add(
                    info,
                    "field",
                    fi,
                    f'Table "{info.name}" has the field "{fname}" more than once.',
                )
                continue
            info.fields[fslug] = fname
        # implicit-name placeholders were only for duplicate detection
        info.fields = {
            k: v for k, v in info.fields.items() if not k.startswith("__implicit__")
        }

        for si, spec in enumerate(info.raw.get("field_specs") or []):
            sname = str(_get(spec, "name") or "").strip()
            sslug = _slug(sname) if sname else ""
            if sslug in IMPLICIT_COLUMN_TYPES:
                add(
                    info,
                    "field_spec",
                    si,
                    f'"{sslug}" in "{info.name}" is created automatically — its type can\'t be changed.',
                )
                continue
            if not sname or sslug not in info.fields:
                add(
                    info,
                    "field_spec",
                    si,
                    f'Table "{info.name}" has a type declared for "{sname}", which isn\'t one of its fields.',
                )
                continue
            if sslug in info.specs:
                add(
                    info,
                    "field_spec",
                    si,
                    f'"{info.name}.{sname}" has its details declared twice.',
                )
                continue
            raw_type = _get(spec, "type")
            ftype = (
                str(raw_type).strip().lower() if raw_type not in (None, "") else None
            )
            if ftype == "auto":
                ftype = None
            if ftype is not None and ftype not in FIELD_TYPES:
                add(
                    info,
                    "field_spec",
                    si,
                    f'"{raw_type}" is not a valid field type for "{info.name}.{sname}" — use one of {", ".join(FIELD_TYPES)}.',
                )
                continue
            info.specs[sslug] = {
                "index": si,
                "type": ftype,
                "nullable": _get(spec, "nullable") is not False,
                "default_raw": _get(spec, "default"),
                "unique": bool(_get(spec, "unique", False)),
            }

    def unique_single_columns(info: _TableInfo) -> set[str]:
        cols = {s for s, spec in info.specs.items() if spec["unique"]}
        for idx in info.raw.get("indexes") or []:
            fields = [
                _slug(str(f))
                for f in (_get(idx, "fields") or [])
                if str(f or "").strip()
            ]
            if _get(idx, "unique", False) and len(fields) == 1:
                cols.add(fields[0])
        return cols

    def base_type(info: _TableInfo, col: str) -> str:
        spec = info.specs.get(col)
        if spec and spec["type"]:
            return spec["type"]
        return infer_field_type(info.fields[col])

    # ── Phase C: foreign keys ──
    fks: dict[
        tuple[str, str], tuple[int, _TableInfo, str, str]
    ] = {}  # (table sql, col) -> (fk index, ref info, ref col, on_delete)
    for info in infos:
        for fi, fk in enumerate(info.raw.get("foreign_keys") or []):
            fname = str(_get(fk, "field") or "").strip()
            col = _slug(fname) if fname else ""
            if col in IMPLICIT_COLUMN_TYPES:
                add(
                    info,
                    "foreign_key",
                    fi,
                    f'"{col}" in "{info.name}" is created automatically — it can\'t be a foreign key.',
                )
                continue
            if not fname or col not in info.fields:
                add(
                    info,
                    "foreign_key",
                    fi,
                    f'Table "{info.name}" has a foreign key on "{fname}", which isn\'t one of its fields.',
                )
                continue
            if (info.sql_name, col) in fks:
                add(
                    info,
                    "foreign_key",
                    fi,
                    f'"{info.name}.{fname}" has more than one foreign key.',
                )
                continue
            ref_raw = _get(fk, "references_table")
            ref = find_table(ref_raw)
            if ref is None:
                add(
                    info,
                    "foreign_key",
                    fi,
                    f'Table "{info.name}"\'s foreign key on "{fname}" references "{ref_raw}", which doesn\'t exist.',
                )
                continue
            ref_col = _slug(str(_get(fk, "references_field") or "id"))
            if ref_col != "id":
                if ref_col not in ref.fields:
                    add(
                        info,
                        "foreign_key",
                        fi,
                        f'"{info.name}.{fname}" references "{ref.name}.{ref_col}", which isn\'t a field of "{ref.name}".',
                    )
                    continue
                if ref_col not in unique_single_columns(ref):
                    add(
                        info,
                        "foreign_key",
                        fi,
                        f'"{info.name}.{fname}" references "{ref.name}.{ref_col}", but a foreign key can only point at '
                        f'"id" or a field marked unique.',
                    )
                    continue
                if any(
                    _slug(str(_get(other, "field") or "")) == ref_col
                    for other in (ref.raw.get("foreign_keys") or [])
                ):
                    add(
                        info,
                        "foreign_key",
                        fi,
                        f'"{info.name}.{fname}" references "{ref.name}.{ref_col}", which is itself a foreign key — '
                        f"point at the original table instead.",
                    )
                    continue
            on_delete_raw = str(_get(fk, "on_delete") or "cascade").strip().lower()
            on_delete = _ON_DELETE_ALIASES.get(on_delete_raw)
            if on_delete is None:
                add(
                    info,
                    "foreign_key",
                    fi,
                    f'"{_get(fk, "on_delete")}" is not a valid on-delete rule for "{info.name}.{fname}" — use one of '
                    f"{', '.join(ON_DELETE_RULES)}.",
                )
                continue
            spec = info.specs.get(col)
            if on_delete == "set_null" and spec is not None and not spec["nullable"]:
                add(
                    info,
                    "foreign_key",
                    fi,
                    f'ON DELETE SET NULL needs "{info.name}.{fname}" to be optional (nullable) — it\'s marked required.',
                )
                continue
            target_type = "integer" if ref_col == "id" else base_type(ref, ref_col)
            if target_type == "json":
                add(
                    info,
                    "foreign_key",
                    fi,
                    f'"{info.name}.{fname}" can\'t reference a JSON field.',
                )
                continue
            if spec is not None and spec["type"] and spec["type"] != target_type:
                add(
                    info,
                    "foreign_key",
                    fi,
                    f'"{info.name}.{fname}" is declared as {spec["type"]} but references '
                    f'"{ref.name}.{ref_col}", which is {target_type} — they have to match.',
                )
                continue
            fks[(info.sql_name, col)] = (fi, ref, ref_col, on_delete)

    # Multi-table FK cycles make "create the parents first" impossible.
    edges: dict[str, set[str]] = {i.sql_name: set() for i in infos}
    for (tsql, _col), (_fi, ref, _rc, _od) in fks.items():
        if ref.sql_name != tsql:
            edges[tsql].add(ref.sql_name)

    def find_cycle() -> list[str] | None:
        state: dict[str, int] = {}
        stack: list[str] = []

        def visit(n: str) -> list[str] | None:
            state[n] = 1
            stack.append(n)
            for m in sorted(edges[n]):
                if state.get(m) == 1:
                    return stack[stack.index(m) :] + [m]
                if m not in state:
                    found = visit(m)
                    if found:
                        return found
            stack.pop()
            state[n] = 2
            return None

        for n in [i.sql_name for i in infos]:
            if n not in state:
                found = visit(n)
                if found:
                    return found
        return None

    while True:
        cycle = find_cycle()
        if not cycle:
            break
        # Report (and drop from the working set) the FK that closes the loop.
        tsql, ref_sql = cycle[-2], cycle[-1]
        info = by_sql[tsql]
        key = next(
            k for k, v in fks.items() if k[0] == tsql and v[1].sql_name == ref_sql
        )
        fi = fks[key][0]
        names = " → ".join(by_sql[s].name for s in cycle)
        add(
            info,
            "foreign_key",
            fi,
            f"Foreign keys form a loop ({names}), so no table can be created first. "
            f'Remove one of them — e.g. keep "{info.fields[key[1]]}" as a plain field.',
        )
        del fks[key]
        edges[tsql].discard(ref_sql)

    # ── Phase D: resolve columns, defaults, checks, indexes, seeds ──
    resolved_tables: dict[str, ResolvedTable] = {}
    for info in infos:
        columns: list[ResolvedColumn] = []
        for col, display in info.fields.items():
            spec = info.specs.get(col)
            fk_entry = fks.get((info.sql_name, col))
            if spec and spec["type"]:
                ftype, declared = spec["type"], True
            elif fk_entry:
                ref, ref_col = fk_entry[1], fk_entry[2]
                ftype, declared = (
                    ("integer" if ref_col == "id" else base_type(ref, ref_col)),
                    False,
                )
            else:
                ftype, declared = infer_field_type(display), False
            nullable = spec["nullable"] if spec else True
            unique = spec["unique"] if spec else False
            default = None
            if spec and spec["default_raw"] is not None:
                try:
                    default = normalize_default(spec["default_raw"], ftype)
                except _CoercionError as e:
                    add(
                        info,
                        "field_spec",
                        spec["index"],
                        f'Default for "{info.name}.{display}" is invalid: {e}.',
                    )
                    default = None
            if unique and ftype == "json":
                add(
                    info,
                    "field_spec",
                    spec["index"],
                    f'"{info.name}.{display}" is JSON, which can\'t be marked unique.',
                )
                unique = False
            length = None
            if ftype == "string":
                length = (
                    URL_LENGTH
                    if classify_field(display) == "url" and not declared
                    else STRING_LENGTH
                )
            resolved_fk = None
            if fk_entry:
                _fi, ref, ref_col, on_delete = fk_entry
                resolved_fk = ResolvedForeignKey(
                    ref_table=ref.name,
                    ref_table_sql=ref.sql_name,
                    ref_class=_pascal(ref.name),
                    ref_column=ref_col,
                    on_delete=on_delete,
                    constraint_name=constraint_name("fk", info.sql_name, col),
                )
            columns.append(
                ResolvedColumn(
                    name=display,
                    column=col,
                    type=ftype,
                    declared=declared,
                    nullable=nullable,
                    default=default,
                    unique=unique,
                    length=length,
                    fk=resolved_fk,
                    unique_constraint_name=constraint_name("uq", info.sql_name, col)
                    if unique
                    else None,
                )
            )

        col_types = {**IMPLICIT_COLUMN_TYPES, **{c.column: c.type for c in columns}}
        by_col = {c.column: c for c in columns}

        # checks
        checks: list[ResolvedCheck] = []
        seen_checks: set[str] = set()
        for ci, chk in enumerate(info.raw.get("checks") or []):
            cname = str(_get(chk, "name") or "").strip()
            expression = str(_get(chk, "expression") or "").strip()
            if not cname or not expression:
                add(
                    info,
                    "check",
                    ci,
                    f'Table "{info.name}" has a check constraint with a blank name or expression.',
                )
                continue
            cslug = _slug(cname)
            if cslug in seen_checks:
                add(
                    info,
                    "check",
                    ci,
                    f'Table "{info.name}" has two check constraints named "{cname}".',
                )
                continue

            def resolve_name(n: str, _types=col_types, _table=info.name) -> str:
                s = _slug(n)
                if s not in _types:
                    raise check_expr.CheckExpressionError(
                        f'"{n}" isn\'t a field of "{_table}".'
                    )
                return s

            try:
                ast = check_expr.bind_fields(check_expr.parse(expression), resolve_name)
                check_expr.type_check(ast, col_types)
            except check_expr.CheckExpressionError as e:
                add(info, "check", ci, f'Check "{cname}" on "{info.name}": {e}')
                continue
            # One stored shape for date/time constants ('2024-01-31T09:30:00'),
            # so the Mongoose evaluator and seed validation parse exactly one
            # form — and SQL written in the form SQLAlchemy stores date-times
            # on SQLite, which compares them as text: against the ISO "T"
            # form, noon on 2024-01-01 would fail ">= '2024-01-01T00:00:00'".
            ast = check_expr.canonicalize_literals(ast, col_types)
            seen_checks.add(cslug)
            checks.append(
                ResolvedCheck(
                    name=cname,
                    constraint_name=constraint_name("ck", info.sql_name, cslug),
                    expression=expression,
                    ast=ast,
                    sql=check_expr.render_storage_sql(ast, col_types),
                    fields=tuple(check_expr.referenced_fields(ast)),
                )
            )

        # indexes
        indexes: list[ResolvedIndex] = []
        seen_index_keys: set[tuple[tuple[str, ...], bool]] = set()
        for ii, idx in enumerate(info.raw.get("indexes") or []):
            raw_fields = [
                str(f).strip()
                for f in (_get(idx, "fields") or [])
                if str(f or "").strip()
            ]
            unique = bool(_get(idx, "unique", False))
            if not raw_fields:
                add(
                    info,
                    "index",
                    ii,
                    f'Table "{info.name}" has an index with no fields.',
                )
                continue
            cols = [_slug(f) for f in raw_fields]
            unknown = [raw_fields[k] for k, c in enumerate(cols) if c not in col_types]
            if unknown:
                add(
                    info,
                    "index",
                    ii,
                    f'Table "{info.name}" has an index on "{unknown[0]}", which isn\'t one of its fields.',
                )
                continue
            if len(set(cols)) != len(cols):
                add(
                    info,
                    "index",
                    ii,
                    f'An index on "{info.name}" lists the same field twice.',
                )
                continue
            if len(cols) > MAX_INDEX_COLUMNS:
                add(
                    info,
                    "index",
                    ii,
                    f'An index on "{info.name}" has more than {MAX_INDEX_COLUMNS} fields.',
                )
                continue
            json_cols = [c for c in cols if col_types[c] == "json"]
            if json_cols:
                add(
                    info,
                    "index",
                    ii,
                    f'"{info.name}.{json_cols[0]}" is JSON and can\'t be indexed.',
                )
                continue
            key = (tuple(cols), unique)
            if key in seen_index_keys:
                add(
                    info,
                    "index",
                    ii,
                    f'Table "{info.name}" has the same index on ({", ".join(cols)}) twice.',
                )
                continue
            if (
                unique
                and len(cols) == 1
                and cols[0] in by_col
                and by_col[cols[0]].unique
            ):
                add(
                    info,
                    "index",
                    ii,
                    f'The unique index on "{info.name}.{cols[0]}" repeats the field\'s own "unique" flag — remove one.',
                )
                continue
            seen_index_keys.add(key)
            indexes.append(
                ResolvedIndex(
                    name=constraint_name(
                        "uq" if unique else "ix", info.sql_name, *cols
                    ),
                    columns=tuple(cols),
                    unique=unique,
                )
            )

        # seed rows
        seed_rows: list[dict] = []
        raw_seeds = info.raw.get("seed_rows") or []
        if len(raw_seeds) > MAX_SEED_ROWS:
            add(
                info,
                "seed_row",
                None,
                f'"{info.name}" has more than {MAX_SEED_ROWS} seed rows.',
            )
            raw_seeds = []
        seen_unique: dict[str, set[str]] = {
            c.column: set() for c in columns if c.unique
        }
        for idx_def in indexes:
            if idx_def.unique:
                seen_unique["|".join(idx_def.columns)] = set()
        for ri, row in enumerate(raw_seeds):
            if not isinstance(row, dict):
                add(
                    info,
                    "seed_row",
                    ri,
                    f'Seed row {ri + 1} of "{info.name}" isn\'t a set of field values.',
                )
                continue
            normalized: dict[str, Any] = {}
            row_ok = True
            for key, value in row.items():
                k = _slug(str(key))
                col = by_col.get(k)
                if k in IMPLICIT_COLUMN_TYPES:
                    add(
                        info,
                        "seed_row",
                        ri,
                        f'Seed row {ri + 1} of "{info.name}" sets "{k}", which is filled in automatically.',
                    )
                    row_ok = False
                    break
                if col is None:
                    add(
                        info,
                        "seed_row",
                        ri,
                        f'Seed row {ri + 1} of "{info.name}" sets "{key}", which isn\'t one of its fields.',
                    )
                    row_ok = False
                    break
                if col.fk and col.fk.ref_column == "id":
                    add(
                        info,
                        "seed_row",
                        ri,
                        f'Seed row {ri + 1} of "{info.name}" sets "{col.name}", but ids are assigned by the database — '
                        f"leave it blank in seed data.",
                    )
                    row_ok = False
                    break
                if value is None or (
                    isinstance(value, str)
                    and value == ""
                    and col.type not in ("string", "text")
                ):
                    continue
                try:
                    normalized[k] = coerce_value(value, col.type)
                except _CoercionError as e:
                    add(
                        info,
                        "seed_row",
                        ri,
                        f'Seed row {ri + 1} of "{info.name}": "{col.name}" {e}.',
                    )
                    row_ok = False
                    break
                if (
                    col.type == "string"
                    and col.length
                    and len(normalized[k]) > col.length
                ):
                    add(
                        info,
                        "seed_row",
                        ri,
                        f'Seed row {ri + 1} of "{info.name}": "{col.name}" is longer than {col.length} characters.',
                    )
                    row_ok = False
                    break
            if not row_ok:
                continue
            missing = [
                c.name
                for c in columns
                if not c.nullable and c.default is None and c.column not in normalized
            ]
            if missing:
                add(
                    info,
                    "seed_row",
                    ri,
                    f'Seed row {ri + 1} of "{info.name}" is missing required field "{missing[0]}".',
                )
                continue
            violated = [
                chk.name
                for chk in checks
                if check_expr.evaluate(chk.ast, normalized, col_types) is False
            ]
            if violated:
                add(
                    info,
                    "seed_row",
                    ri,
                    f'Seed row {ri + 1} of "{info.name}" breaks the check "{violated[0]}".',
                )
                continue
            dup = None
            for ukey, seen_vals in seen_unique.items():
                ucols = ukey.split("|")
                if any(normalized.get(c) is None for c in ucols):
                    continue  # NULLs never collide in a unique constraint
                token = json.dumps([normalized[c] for c in ucols], sort_keys=True)
                if token in seen_vals:
                    dup = ", ".join(ucols)
                    break
                seen_vals.add(token)
            if dup:
                add(
                    info,
                    "seed_row",
                    ri,
                    f'Seed row {ri + 1} of "{info.name}" repeats a value in unique ({dup}).',
                )
                continue
            seed_rows.append(normalized)

        resolved_tables[info.sql_name] = ResolvedTable(
            name=info.name,
            slug=info.slug,
            sql_name=info.sql_name,
            class_name=_pascal(info.name),
            purpose=str(info.raw.get("purpose") or ""),
            columns=tuple(columns),
            checks=tuple(checks),
            indexes=tuple(indexes),
            seed_rows=tuple(seed_rows),
        )

    # ── Phase E: creation order (parents before children; stable) ──
    order: list[str] = []
    placed: set[str] = set()
    remaining = [i.sql_name for i in infos]
    while remaining:
        progressed = False
        for s in list(remaining):
            if edges[s] <= placed:
                order.append(s)
                placed.add(s)
                remaining.remove(s)
                progressed = True
        if not progressed:  # unreachable once cycles are removed; defensive
            order.extend(remaining)
            break

    schema = ResolvedSchema(
        tables=tuple(resolved_tables[i.sql_name] for i in infos),
        creation_order=tuple(order),
    )
    return issues, schema


# ───────────────────────────────────────────────
#  Public entry points
# ───────────────────────────────────────────────
def validate_tables(tables: list[Any], backend: str | None = None) -> list[SchemaIssue]:
    """Every structural problem, in table order. Empty list = valid.
    `backend` (a stack_matrix backend key, e.g. "fastapi"/"express")
    enables that language's reserved-name checks; None skips them."""
    return _analyze(tables, backend)[0]


def resolve_schema(
    tables: list[Any], backend: str | None = None, strict: bool = True
) -> ResolvedSchema:
    """strict=True raises SchemaValidationError listing every issue.
    strict=False first drops invalid optional entries (sanitize_tables)
    and then resolves whatever is left, skipping any table/field whose
    own name is unusable — for read paths (ERD, AI prompts) that must
    never fail on legacy or AI-authored data."""
    if strict:
        issues, schema = _analyze(tables, backend)
        if issues:
            raise SchemaValidationError(issues)
        return schema
    cleaned, _notes = sanitize_tables(tables, backend)
    return _analyze(cleaned, backend)[1]


_DROPPABLE_KINDS = {
    "field_spec": "a field detail",
    "foreign_key": "a foreign key",
    "check": "a check constraint",
    "index": "an index",
    "seed_row": "a seed row",
}


def sanitize_tables(
    tables: list[Any], backend: str | None = None
) -> tuple[list[dict], list[str]]:
    """For AI-authored architectures: removes each invalid optional entry
    (field_spec / foreign_key / check / index / seed_row) instead of
    rejecting the whole design, and returns a note per removal so the UI
    can say exactly what was dropped and why. A foreign key on a field
    the AI forgot to list in key_fields gets that field added (the
    intent is unambiguous). Problems with table or field NAMES are left
    in place — only the user can decide what to rename."""
    cleaned = [copy.deepcopy(_as_dict(t)) for t in (tables or [])]
    notes: list[str] = []

    for t in cleaned:
        existing = {
            _slug(str(f)) for f in (t.get("key_fields") or []) if str(f or "").strip()
        }
        for fk in t.get("foreign_keys") or []:
            fname = str(_get(fk, "field") or "").strip()
            if (
                fname
                and _slug(fname) not in existing
                and _slug(fname) not in IMPLICIT_COLUMN_TYPES
            ):
                t.setdefault("key_fields", []).append(fname)
                existing.add(_slug(fname))
                notes.append(
                    f'Added the field "{fname}" to "{t.get("name")}" because a foreign key uses it.'
                )

    for _ in range(8):
        issues = _analyze(cleaned, backend)[0]
        droppable = [
            i
            for i in issues
            if i.kind in _DROPPABLE_KINDS and i.table_index is not None
        ]
        if not droppable:
            break
        # An issue with index None (e.g. too many seed rows) clears the whole list.
        by_target: dict[tuple[int, str], set[int | None]] = {}
        for issue in droppable:
            by_target.setdefault((issue.table_index, issue.kind), set()).add(
                issue.index
            )
            notes.append(f"Dropped {_DROPPABLE_KINDS[issue.kind]}: {issue.message}")
        for (ti, kind), positions in by_target.items():
            key = {
                "field_spec": "field_specs",
                "foreign_key": "foreign_keys",
                "check": "checks",
                "index": "indexes",
                "seed_row": "seed_rows",
            }[kind]
            items = cleaned[ti].get(key) or []
            if None in positions:
                cleaned[ti][key] = []
            else:
                cleaned[ti][key] = [
                    item for pos, item in enumerate(items) if pos not in positions
                ]
    return cleaned, notes


def normalize_tables(tables: list[Any], backend: str | None = None) -> list[dict]:
    """Canonical storage form of VALID tables (call validate_tables
    first): trimmed names, lower-cased types/rules, canonical defaults
    and seed values, foreign keys pointing at the referenced table's
    exact name, and no-op field_specs removed. Keys of seed rows and
    names in indexes/field_specs use the field's key_fields spelling so
    the editor can match them back up."""
    schema = _analyze(tables, backend)[1]
    out: list[dict] = []
    raw_by_name = {
        str(_as_dict(t).get("name") or "").strip(): _as_dict(t) for t in (tables or [])
    }
    for rt in schema.tables:
        raw = raw_by_name.get(rt.name, {})
        display = {c.column: c.name for c in rt.columns}
        key_fields = [
            str(f).strip()
            for f in (raw.get("key_fields") or [])
            if str(f or "").strip()
        ]
        field_specs = []
        for c in rt.columns:
            if not (c.declared or not c.nullable or c.default is not None or c.unique):
                continue
            field_specs.append(
                {
                    "name": c.name,
                    "type": c.type if c.declared else None,
                    "nullable": c.nullable,
                    "default": default_storage_value(c.default),
                    "unique": c.unique,
                }
            )
        out.append(
            {
                "name": rt.name,
                "purpose": str(raw.get("purpose") or "").strip(),
                "key_fields": key_fields,
                "field_specs": field_specs,
                "foreign_keys": [
                    {
                        "field": c.name,
                        "references_table": c.fk.ref_table,
                        "references_field": c.fk.ref_column,
                        "on_delete": c.fk.on_delete,
                    }
                    for c in rt.columns
                    if c.fk
                ],
                "checks": [
                    {"name": chk.name, "expression": chk.expression}
                    for chk in rt.checks
                ],
                "indexes": [
                    {
                        "fields": [display.get(col, col) for col in idx.columns],
                        "unique": idx.unique,
                    }
                    for idx in rt.indexes
                ],
                "seed_rows": [
                    {display.get(k, k): v for k, v in row.items()}
                    for row in rt.seed_rows
                ],
            }
        )
    return out


# ───────────────────────────────────────────────
#  Snapshots and diffs (the input to migrations_gen.py)
# ───────────────────────────────────────────────
SNAPSHOT_VERSION = 1


def snapshot(schema: ResolvedSchema) -> dict:
    """DDL-relevant, JSON-serializable description of a resolved schema.
    Two snapshots are equal iff they'd produce the same database, so a
    regeneration with no real schema change produces no migration."""
    tables = {}
    for t in schema.tables:
        tables[t.sql_name] = {
            "label": t.name,
            "columns": {c.column: c.snapshot() for c in t.columns},
            "column_order": [c.column for c in t.columns],
            "checks": {
                chk.constraint_name: {
                    "ast": chk.ast,
                    "sql": chk.sql,
                    "expression": chk.expression,
                }
                for chk in t.checks
            },
            "indexes": {
                i.name: {"columns": list(i.columns), "unique": i.unique}
                for i in t.indexes
            },
            "seed_rows": [dict(r) for r in t.seed_rows],
        }
    return {
        "version": SNAPSHOT_VERSION,
        "tables": tables,
        "table_order": list(schema.creation_order),
    }


def empty_snapshot() -> dict:
    return {"version": SNAPSHOT_VERSION, "tables": {}, "table_order": []}


def _row_key(row: dict) -> str:
    return json.dumps(row, sort_keys=True)


def _check_sig(chk: dict) -> str:
    return json.dumps(chk["ast"], sort_keys=True)


def diff_snapshots(old: dict | None, new: dict) -> list[dict]:
    """Ordered operations that turn database `old` into database `new`.
    Order is execution-safe: constraints that would block a change are
    dropped first, children are dropped before parents and created
    after them, and seed rows go in last. The reverse migration is
    simply diff_snapshots(new, old).

    Ops carry names only; a renderer looks the full definition up in
    `new` (for create/add/alter) or `old` (for drop)."""
    old = old or empty_snapshot()
    old_t, new_t = old["tables"], new["tables"]
    old_order = old.get("table_order") or list(old_t)
    new_order = new.get("table_order") or list(new_t)
    dropped = [s for s in reversed(old_order) if s in old_t and s not in new_t]
    created = [s for s in new_order if s in new_t and s not in old_t]
    common = [s for s in new_order if s in new_t and s in old_t]
    ops: list[dict] = []

    # 1. Drop indexes/checks/FKs/uniques that are removed or changed.
    for s in common:
        o, n = old_t[s], new_t[s]
        for name, idx in o["indexes"].items():
            if n["indexes"].get(name) != idx:
                ops.append({"op": "drop_index", "table": s, "name": name})
        for name, chk in o["checks"].items():
            if name not in n["checks"] or _check_sig(n["checks"][name]) != _check_sig(
                chk
            ):
                ops.append({"op": "drop_check", "table": s, "name": name})
        for col, oc in o["columns"].items():
            nc = n["columns"].get(col)
            if oc["fk"] and (nc is None or nc["fk"] != oc["fk"]):
                ops.append(
                    {
                        "op": "drop_fk",
                        "table": s,
                        "column": col,
                        "name": oc["fk"]["name"],
                    }
                )
            if oc["unique"] and (nc is None or nc["unique"] != oc["unique"]):
                ops.append(
                    {
                        "op": "drop_unique",
                        "table": s,
                        "column": col,
                        "name": oc["unique"],
                    }
                )

    # 2. Remove seed rows that are gone (while every column they matched on still exists).
    for s in common:
        new_keys = {_row_key(r) for r in new_t[s]["seed_rows"]}
        removed = [r for r in old_t[s]["seed_rows"] if _row_key(r) not in new_keys]
        if removed:
            ops.append({"op": "delete_seed", "table": s, "rows": removed})

    # 3. Drop whole tables, children first.
    for s in dropped:
        ops.append({"op": "drop_table", "table": s})

    # 4. Create new tables, parents first (with their own constraints,
    #    indexes and seed rows — a renderer emits those inline).
    for s in created:
        ops.append({"op": "create_table", "table": s})

    # 5. Column changes on surviving tables.
    for s in common:
        o, n = old_t[s], new_t[s]
        for col in n["column_order"]:
            if col not in o["columns"]:
                ops.append({"op": "add_column", "table": s, "column": col})
        for col in n["column_order"]:
            oc, nc = o["columns"].get(col), n["columns"][col]
            if oc is None:
                continue
            changes = {}
            for attr in ("type", "length", "nullable", "default"):
                if oc[attr] != nc[attr]:
                    changes[attr] = [oc[attr], nc[attr]]
            if changes:
                ops.append(
                    {
                        "op": "alter_column",
                        "table": s,
                        "column": col,
                        "changes": changes,
                    }
                )
        for col in o["column_order"]:
            if col not in n["columns"]:
                ops.append({"op": "drop_column", "table": s, "column": col})

    # 6. Add uniques/FKs/checks/indexes that are new or changed.
    for s in common:
        o, n = old_t[s], new_t[s]
        for col in n["column_order"]:
            nc, oc = n["columns"][col], o["columns"].get(col)
            if nc["unique"] and (oc is None or oc["unique"] != nc["unique"]):
                ops.append(
                    {
                        "op": "add_unique",
                        "table": s,
                        "column": col,
                        "name": nc["unique"],
                    }
                )
            if nc["fk"] and (oc is None or oc["fk"] != nc["fk"]):
                ops.append(
                    {
                        "op": "add_fk",
                        "table": s,
                        "column": col,
                        "name": nc["fk"]["name"],
                    }
                )
        for name, chk in n["checks"].items():
            if name not in o["checks"] or _check_sig(o["checks"][name]) != _check_sig(
                chk
            ):
                ops.append({"op": "add_check", "table": s, "name": name})
        for name, idx in n["indexes"].items():
            if o["indexes"].get(name) != idx:
                ops.append({"op": "add_index", "table": s, "name": name})

    # 7. New seed rows on surviving tables.
    for s in common:
        old_keys = {_row_key(r) for r in old_t[s]["seed_rows"]}
        added = [r for r in new_t[s]["seed_rows"] if _row_key(r) not in old_keys]
        if added:
            ops.append({"op": "insert_seed", "table": s, "rows": added})

    return ops


def _qual(op: dict) -> str:
    return f"{op['table']}.{op['column']}" if "column" in op else op["table"]


def describe_op(op: dict, old: dict | None, new: dict) -> str:
    """One human-readable line per op, for migration docstrings and the UI."""
    kind = op["op"]
    new_t = new["tables"]
    if kind == "create_table":
        return f"create table {op['table']}"
    if kind == "drop_table":
        return f"drop table {op['table']} (deletes all of its rows)"
    if kind == "add_column":
        col = new_t[op["table"]]["columns"][op["column"]]
        return f"add column {_qual(op)} ({col['type']}{'' if col['nullable'] else ', required'})"
    if kind == "drop_column":
        return f"drop column {_qual(op)} (deletes its data)"
    if kind == "alter_column":
        parts = []
        ch = op["changes"]
        if "type" in ch:
            parts.append(f"type {ch['type'][0]} → {ch['type'][1]}")
        elif "length" in ch:
            parts.append(f"length {ch['length'][0]} → {ch['length'][1]}")
        if "nullable" in ch:
            parts.append("now required" if not ch["nullable"][1] else "now optional")
        if "default" in ch:
            parts.append("default changed" if ch["default"][1] else "default removed")
        return f"change {_qual(op)}: {', '.join(parts)}"
    if kind == "add_unique":
        return f"make {_qual(op)} unique"
    if kind == "drop_unique":
        return f"stop requiring {_qual(op)} to be unique"
    if kind == "add_fk":
        fk = new_t[op["table"]]["columns"][op["column"]]["fk"]
        return f"add foreign key {_qual(op)} → {fk['table']}.{fk['column']} (on delete {fk['on_delete']})"
    if kind == "drop_fk":
        return f"drop foreign key on {_qual(op)}"
    if kind == "add_check":
        return f"add check {op['name']} ({new_t[op['table']]['checks'][op['name']]['sql']})"
    if kind == "drop_check":
        return f"drop check {op['name']}"
    if kind == "add_index":
        idx = new_t[op["table"]]["indexes"][op["name"]]
        return f"add {'unique ' if idx['unique'] else ''}index {op['name']} on {op['table']}({', '.join(idx['columns'])})"
    if kind == "drop_index":
        return f"drop index {op['name']}"
    if kind == "insert_seed":
        return f"insert {len(op['rows'])} seed row(s) into {op['table']}"
    if kind == "delete_seed":
        return f"delete {len(op['rows'])} seed row(s) from {op['table']}"
    return kind


def destructive_changes(ops: list[dict], old: dict | None, new: dict) -> list[str]:
    """Ops that can permanently lose existing data. The deterministic
    codegen endpoint refuses to write a migration containing any of
    these unless the user explicitly confirms."""
    out = []
    for op in ops:
        if op["op"] in ("drop_table", "drop_column"):
            out.append(describe_op(op, old, new))
        elif op["op"] == "alter_column" and (
            "type" in op["changes"] or "length" in op["changes"]
        ):
            out.append(describe_op(op, old, new) + " (existing values may not convert)")
    return out


def migration_blockers(ops: list[dict], old: dict | None, new: dict) -> list[str]:
    """Changes no migration can apply safely to a table that may already
    hold rows — refused outright with a fix the user can make."""
    out = []
    for op in ops:
        if op["op"] == "add_column":
            col = new["tables"][op["table"]]["columns"][op["column"]]
            if not col["nullable"] and col["default"] is None:
                out.append(
                    f'"{_qual(op)}" is a new required field on an existing table — rows already in the '
                    f"database would have no value for it. Give it a default, or make it optional."
                )
        elif op["op"] == "alter_column" and "nullable" in op["changes"]:
            becomes_required = op["changes"]["nullable"][1] is False
            col = new["tables"][op["table"]]["columns"][op["column"]]
            if becomes_required and col["default"] is None:
                out.append(
                    f'"{_qual(op)}" is becoming required, but existing rows may have it empty. Give it a '
                    f"default (used to fill those rows), or keep it optional."
                )
    return out


# ───────────────────────────────────────────────
#  SQLAlchemy rendering shared by the model file AND the migration,
#  so the two always agree character for character.
# ───────────────────────────────────────────────
def sa_type_code(col: dict) -> str:
    t = col["type"]
    if t == "string":
        return f"sa.String(length={col.get('length') or STRING_LENGTH})"
    return {
        "text": "sa.Text()",
        "integer": "sa.Integer()",
        "float": "sa.Float()",
        "decimal": f"sa.Numeric(precision={DECIMAL_PRECISION}, scale={DECIMAL_SCALE})",
        "boolean": "sa.Boolean()",
        "date": "sa.Date()",
        "datetime": "sa.DateTime(timezone=True)",
        "json": "sa.JSON()",
    }[t]


def sa_server_default_code(col: dict) -> str | None:
    default = col.get("default")
    if not default:
        return None
    if default["kind"] == "now":
        return "sa.func.now()"
    if default["kind"] == "today":
        return 'sa.text("CURRENT_DATE")'
    value = default["value"]
    t = col["type"]
    if t == "boolean":
        return "sa.true()" if value else "sa.false()"
    if t in ("integer", "float", "decimal"):
        return f"sa.text({json.dumps(str(value))})"
    if t == "json":
        return repr(json.dumps(value, sort_keys=True))
    return repr(str(value))


def python_type_code(col: dict) -> str:
    """Pydantic field annotation for a column (without Optional)."""
    return {
        "string": "str",
        "text": "str",
        "integer": "int",
        "float": "float",
        "decimal": "Decimal",
        "boolean": "bool",
        "date": "date",
        "datetime": "datetime",
        "json": "Any",
    }[col["type"]]


def python_literal(value: Any, field_type: str) -> str:
    """A canonical seed/default value as Python source."""
    if field_type == "decimal":
        return f"Decimal({json.dumps(str(value))})"
    if field_type == "date":
        return f"date.fromisoformat({json.dumps(value)})"
    if field_type == "datetime":
        return f"datetime.fromisoformat({json.dumps(value)})"
    return repr(value)


# ───────────────────────────────────────────────
#  AI codegen prompt description
# ───────────────────────────────────────────────
def describe_table_for_prompt(table: Any, all_tables: list[Any] | None = None) -> str:
    """Replaces the old bare "Fields: a, b, c" line in every AI backend
    adapter's model prompt with the resolved, typed schema — declared
    types are marked authoritative; inferred ones are flagged as a best
    guess. Never raises: falls back to the plain field list if this
    table can't be resolved at all."""
    raw = _as_dict(table)
    plain = f"Fields: {', '.join(str(f) for f in (raw.get('key_fields') or []))}"
    try:
        schema = resolve_schema(
            all_tables if all_tables is not None else [raw], strict=False
        )
    except Exception:  # noqa: BLE001 — a prompt must never fail to build
        return plain
    rt = schema.table(str(raw.get("name") or "").strip())
    if rt is None:
        return plain

    lines = ['Fields (primary key "id" is generated automatically):']
    for c in rt.columns:
        parts = [f"string (max {c.length})" if c.type == "string" else c.type]
        parts.append("required (NOT NULL)" if not c.nullable else "optional")
        if c.unique:
            parts.append("unique")
        if c.default is not None:
            dv = default_storage_value(c.default)
            parts.append(
                f"default {dv if c.default['kind'] != 'literal' else json.dumps(dv)}"
            )
        if c.fk:
            rule = c.fk.on_delete.replace("_", " ").upper()
            parts.append(
                f"foreign key → {c.fk.ref_table_sql}.{c.fk.ref_column} (ON DELETE {rule})"
            )
        if not c.declared and not c.fk:
            parts.append("type inferred from the name — keep unless clearly wrong")
        lines.append(f"- {c.column}: {', '.join(parts)}")
    if rt.checks:
        lines.append("Check constraints (enforce every one):")
        lines += [f"- {chk.constraint_name}: {chk.sql}" for chk in rt.checks]
    if rt.indexes:
        lines.append("Indexes:")
        lines += [
            f"- {i.name}: {'UNIQUE ' if i.unique else ''}({', '.join(i.columns)})"
            for i in rt.indexes
        ]
    return "\n".join(lines)
