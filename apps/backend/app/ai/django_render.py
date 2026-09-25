# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Django source rendering shared by models and migrations
#  ai/django_render.py — The deterministic Django backend writes each
#  table twice: once as a model class (api/models/<table>.py) and once
#  as migration operations (api/migrations/NNNN_*.py). Django compares
#  the two (`makemigrations --check`), so every field, constraint and
#  index is rendered HERE, from the same db_schema snapshot, for both.
#
#  Naming:
#    - Model class: _pascal(table label) — what every other generator
#      calls it, and stable for as long as the table's SQL name is.
#    - Field: the column name, except a foreign key column ending in
#      "_id" (customer_id), which becomes the Django field "customer" —
#      Django's own convention, and its attname IS customer_id, so the
#      column, the API key and `obj.customer_id` all keep that name.
#      Foreign keys always pin db_column, so turning an existing column
#      into a foreign key (or back) is a rename in Django's state only.
#    - Index: Django refuses index names over 30 characters, so longer
#      db_schema names are shortened with a hash (unique constraints and
#      checks keep the exact db_schema names every backend shares).
#
#  Helper modules are imported under "_" aliases (_datetime, _timezone…):
#  fields are class-body assignments, so a column named e.g. "copy" or
#  "timezone" would otherwise replace the module for every later field's
#  default — and no column name can start with "_".
#
#  CHECK rules become Q objects. Django rewrites a NEGATED lookup on a
#  nullable column as NOT (x = v AND x IS NOT NULL), which differs from
#  SQL's three-valued NOT when negations nest — so negation is pushed
#  down to the leaves first (NOT (a < 1) -> a >= 1, De Morgan through
#  AND/OR). With NOT only on leaves, the constraint accepts and rejects
#  exactly the rows the rule's SQL does on the other backends. LIKE uses
#  the app's own `like` lookup (api/lookups.py), which writes the same
#  SQL check_expr.render_sql() does.
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations

import hashlib
import json
import keyword
import re
from datetime import date, datetime
from typing import Any

from app.ai import db_schema
from app.ai.codegen_shared import _pascal

APP_LABEL = "api"
MAX_INDEX_NAME = 30  # Django's models.E034

_ON_DELETE = {"cascade": "CASCADE", "set_null": "SET_NULL", "restrict": "RESTRICT"}
_FIELD_CLASS = {
    "string": "CharField",
    "text": "TextField",
    "integer": "IntegerField",
    "float": "FloatField",
    "decimal": "DecimalField",
    "boolean": "BooleanField",
    "date": "DateField",
    "datetime": "DateTimeField",
    "json": "JSONField",
}


class Imports:
    """The module imports a rendered snippet needs, collected while
    rendering so a file imports exactly what it uses."""

    def __init__(self) -> None:
        self.names: set[str] = set()

    def need(self, name: str) -> None:
        self.names.add(name)

    def lines(self, *, migrations: bool) -> list[str]:
        stdlib = [
            f"import {n} as _{n}"
            for n in ("copy", "datetime", "decimal", "functools")
            if n in self.names
        ]
        django = [
            "from django.db import migrations, models"
            if migrations
            else "from django.db import models"
        ]
        if "Length" in self.names:
            django.append("from django.db.models.functions import Length")
        lookups = sorted(n for n in self.names if n in _LOOKUP_CLASSES.values())
        if lookups:
            django.append(f"from django.db.models.lookups import {', '.join(lookups)}")
        if "timezone" in self.names:
            django.append("from django.utils import timezone as _timezone")
        return stdlib + ([""] if stdlib else []) + django


# ─── names ───
def model_name(table: dict) -> str:
    return _pascal(table["label"])


def field_name(column: str, col: dict) -> str:
    if col.get("fk") and column.endswith("_id") and len(column) > 3:
        return column[:-3]
    return column


def index_name(name: str) -> str:
    if len(name) <= MAX_INDEX_NAME:
        return name
    digest = hashlib.sha1(name.encode()).hexdigest()[:8]
    return f"{name[: MAX_INDEX_NAME - 9].rstrip('_')}_{digest}"


def field_name_problem(column: str, col: dict, columns: dict) -> str | None:
    """Why a column can't become a Django field under the naming above."""
    name = field_name(column, col)
    if name.endswith("_") or "__" in name:
        return f'"{name}" can\'t be a Django field name (no trailing "_" and no "__")'
    if name != column:
        if name in columns:
            return (
                f'the foreign key "{column}" becomes the Django field "{name}", '
                f'which "{name}" already is — rename one of them'
            )
        if keyword.iskeyword(name) or name in ("pk", "objects", "id"):
            return f'the foreign key "{column}" would become the Django field "{name}", a reserved name'
    return None


# ─── values ───
def _datetime_code(value: datetime) -> str:
    parts = [value.year, value.month, value.day, value.hour, value.minute]
    if value.second or value.microsecond:
        parts.append(value.second)
    if value.microsecond:
        parts.append(value.microsecond)
    return f"_datetime.datetime({', '.join(str(p) for p in parts)}, tzinfo=_datetime.timezone.utc)"


def value_code(value: Any, field_type: str, imports: Imports) -> str:
    """A canonical (snapshot) value as Python source for its field type."""
    if value is None:
        return "None"
    if field_type == "decimal":
        imports.need("decimal")
        return f"_decimal.Decimal({json.dumps(str(value))})"
    if field_type == "date":
        imports.need("datetime")
        d = value if isinstance(value, date) else date.fromisoformat(str(value))
        return f"_datetime.date({d.year}, {d.month}, {d.day})"
    if field_type == "datetime":
        imports.need("datetime")
        dt = (
            value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        )
        return _datetime_code(dt.replace(tzinfo=None))
    if field_type == "json":
        return repr(json.loads(json.dumps(value)))
    if field_type == "float" and isinstance(value, int) and not isinstance(value, bool):
        return repr(float(value))
    return repr(value)


def _default_code(col: dict, imports: Imports) -> str | None:
    default = col.get("default")
    if not default:
        return None
    if default["kind"] == "now":
        imports.need("timezone")
        return "_timezone.now"
    if default["kind"] == "today":
        imports.need("datetime")
        return "_datetime.date.today"
    value = default["value"]
    if col["type"] == "json" and isinstance(value, (dict, list)):
        # A mutable default must be a callable (Django's fields.E010);
        # partial(deepcopy, value) hands every row its own copy and
        # compares by value, so makemigrations sees no change.
        if value == {}:
            return "dict"
        if value == []:
            return "list"
        imports.need("functools")
        imports.need("copy")
        return (
            f"_functools.partial(_copy.deepcopy, {value_code(value, 'json', imports)})"
        )
    return value_code(value, col["type"], imports)


# ─── fields ───
def field_code(
    column: str,
    col: dict,
    tables: dict,
    imports: Imports,
    *,
    fk: dict | None | bool = True,
    pin_column: bool = False,
) -> str:
    """models.<Field>(...) for a snapshot column. `fk` overrides whether
    the column is rendered as a foreign key (True = as the snapshot
    says, None = as a plain column); `pin_column` adds db_column to a
    plain column (a step of turning it into a foreign key or back)."""
    fk_def = col.get("fk") if fk is True else fk
    kwargs: list[str] = []
    if fk_def:
        target = model_name(tables[fk_def["table"]])
        head = f'models.ForeignKey("{APP_LABEL}.{target}", on_delete=models.{_ON_DELETE[fk_def["on_delete"]]}'
        kwargs.append(f'db_column="{column}"')
        kwargs.append('related_name="+"')
        if fk_def["column"] != "id":
            kwargs.append(f'to_field="{fk_def["column"]}"')
    else:
        cls = _FIELD_CLASS[col["type"]]
        head = f"models.{cls}("
        if col["type"] == "string":
            kwargs.append(f"max_length={col['length']}")
        if col["type"] == "decimal":
            kwargs.append(f"max_digits={db_schema.DECIMAL_PRECISION}")
            kwargs.append(f"decimal_places={db_schema.DECIMAL_SCALE}")
        if pin_column:
            kwargs.append(f'db_column="{column}"')
    if col["nullable"]:
        kwargs += ["null=True", "blank=True"]
    default = _default_code(col, imports)
    if default is not None:
        kwargs.append(f"default={default}")
    if fk_def:
        return head + (", " + ", ".join(kwargs) if kwargs else "") + ")"
    return head + ", ".join(kwargs) + ")"


ID_FIELD = 'models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")'
CREATED_AT_FIELD = "models.DateTimeField(auto_now_add=True)"
UPDATED_AT_FIELD = "models.DateTimeField(auto_now=True)"


# ─── checks: AST -> Q ───
_COMPLEMENT = {"=": "<>", "<>": "=", "<": ">=", ">=": "<", ">": "<=", "<=": ">"}
_FLIP = {"=": "=", "<>": "<>", "<": ">", ">": "<", "<=": ">=", ">=": "<="}
_SUFFIX = {"=": "", "<": "__lt", "<=": "__lte", ">": "__gt", ">=": "__gte"}
_LOOKUP_CLASSES = {
    "=": "Exact",
    "<": "LessThan",
    "<=": "LessThanOrEqual",
    ">": "GreaterThan",
    ">=": "GreaterThanOrEqual",
    "in": "In",
    "isnull": "IsNull",
}


class _Q:
    def __init__(self, columns: dict, imports: Imports) -> None:
        self.columns = columns
        self.imports = imports

    def _type(self, operand: dict) -> str | None:
        if "field" in operand:
            return self.columns[operand["field"]]["type"]
        return None

    def _literal(self, value: Any, field_type: str | None) -> str:
        if field_type in ("date", "datetime", "decimal") and isinstance(value, str):
            return value_code(value, field_type, self.imports)
        if field_type == "decimal" and not isinstance(value, bool):
            return value_code(str(value), "decimal", self.imports)
        return repr(value)

    def _expr(self, operand: dict) -> str:
        """An operand as a Django expression (right-hand side of a lookup)."""
        if "field" in operand:
            return f'models.F("{operand["field"]}")'
        if "length" in operand:
            self.imports.need("Length")
            inner = operand["length"]
            return (
                f'Length("{inner["field"]}")'
                if "field" in inner
                else f"Length({self._expr(inner)})"
            )
        return repr(operand["value"])

    def _leaf(self, op: str, left: dict, right: dict) -> str:
        if "value" in left and "value" not in right:
            left, right, op = right, left, _FLIP[op]
        negate = op == "<>"
        base = "=" if negate else op
        if "field" in left:
            rhs = (
                self._literal(right["value"], self._type(left))
                if "value" in right
                else self._expr(right)
            )
            q = f"models.Q({left['field']}{_SUFFIX[base]}={rhs})"
        else:
            cls = _LOOKUP_CLASSES[base]
            self.imports.need(cls)
            q = f"models.Q({cls}({self._expr(left)}, {self._expr(right)}))"
        return f"~{q}" if negate else q

    def render(self, node: dict, neg: bool = False, top: bool = False) -> str:
        if "and" in node or "or" in node:
            is_and = ("and" in node) != neg
            parts = [
                self.render(child, neg)
                for child in node["and" if "and" in node else "or"]
            ]
            joined = (" & " if is_and else " | ").join(parts)
            # A top-level group needs no outer parentheses.
            return joined if top else f"({joined})"
        if "not" in node:
            return self.render(node["not"], not neg, top)
        if "cmp" in node:
            op = _COMPLEMENT[node["cmp"]] if neg else node["cmp"]
            return self._leaf(op, node["left"], node["right"])
        negated = bool(node.get("negated")) != neg
        if "is_null" in node:
            target = node["is_null"]
            want = "False" if negated else "True"
            if "field" in target:
                return f"models.Q({target['field']}__isnull={want})"
            self.imports.need("IsNull")
            return f"models.Q(IsNull({self._expr(target)}, {want}))"
        if "in" in node:
            target = node["in"]
            values = (
                "["
                + ", ".join(
                    self._literal(v, self._type(target)) for v in node["values"]
                )
                + "]"
            )
            if "field" in target:
                q = f"models.Q({target['field']}__in={values})"
            else:
                self.imports.need("In")
                q = f"models.Q(In({self._expr(target)}, {values}))"
            return f"~{q}" if negated else q
        if "between" in node:
            target, low, high = node["between"], node["low"], node["high"]
            if negated:
                return f"({self._leaf('<', target, low)} | {self._leaf('>', target, high)})"
            if "field" in target and "value" in low and "value" in high:
                t = self._type(target)
                return (
                    f"models.Q({target['field']}__range=("
                    f"{self._literal(low['value'], t)}, {self._literal(high['value'], t)}))"
                )
            return (
                f"({self._leaf('>=', target, low)} & {self._leaf('<=', target, high)})"
            )
        if "like" in node:
            target = node["like"]
            if "field" not in target:
                raise ValueError(
                    "LIKE on a computed value isn't supported by the Django backend"
                )
            q = f"models.Q({target['field']}__like={node['pattern']!r})"
            return f"~{q}" if negated else q
        raise ValueError(f"Unknown check node: {node!r}")


def q_code(ast: dict, columns: dict, imports: Imports) -> str:
    return _Q(columns, imports).render(ast, top=True)


# ─── constraints / indexes ───
def unique_constraint_code(table: dict, columns: list[str], name: str) -> str:
    fields = ", ".join(f'"{field_name(c, table["columns"][c])}"' for c in columns)
    return f'models.UniqueConstraint(fields=[{fields}], name="{name}")'


def check_constraint_code(table: dict, name: str, imports: Imports) -> str:
    q = q_code(table["checks"][name]["ast"], table["columns"], imports)
    return f'models.CheckConstraint(check={q}, name="{name}")'


def index_code(table: dict, name: str) -> str:
    idx = table["indexes"][name]
    fields = ", ".join(
        f'"{field_name(c, table["columns"][c])}"' for c in idx["columns"]
    )
    return f'models.Index(fields=[{fields}], name="{index_name(name)}")'


def table_constraints(table: dict, imports: Imports) -> list[str]:
    """Every Meta.constraints entry, in a stable order."""
    out = [
        unique_constraint_code(table, [c], col["unique"])
        for c in table["column_order"]
        if (col := table["columns"][c])["unique"]
    ]
    out += [
        unique_constraint_code(table, idx["columns"], name)
        for name, idx in table["indexes"].items()
        if idx["unique"]
    ]
    out += [check_constraint_code(table, name, imports) for name in table["checks"]]
    return out


def table_indexes(table: dict) -> list[str]:
    return [
        index_code(table, name)
        for name, idx in table["indexes"].items()
        if not idx["unique"]
    ]


def py_identifier_ok(name: str) -> bool:
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name)) and not keyword.iskeyword(
        name
    )
