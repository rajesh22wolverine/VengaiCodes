# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Spring Boot / Flyway rendering shared by entities and
#  migrations
#  ai/spring_render.py — The deterministic Spring Boot backend describes
#  each table twice: as a JPA entity and as Flyway SQL. Hibernate checks
#  the two against each other at every start (ddl-auto=validate), so
#  column names, SQL types and Java types all come from here.
#
#  Database: H2 in a file (zero setup, like the adapter's AI path). The
#  SQL is standard enough to read on Postgres too, but only H2 is run.
#  Every identifier is quoted — lower-case, as written — on both sides
#  (Hibernate's globally_quoted_identifiers): H2 upper-cases unquoted
#  names and reserves many common ones ("key", "value", "year"…).
#
#  Date-times are Instants in TIMESTAMP WITH TIME ZONE columns, so JSON
#  says "…Z" and a CHECK literal is explicitly UTC. Text and JSON are
#  unlengthed VARCHAR, not CLOB: H2 can't compare a CLOB, which a
#  UNIQUE, a LIKE rule or a seed-row match all need.
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from datetime import date, datetime

from app.ai import check_expr, db_schema, knowledge
from app.ai.codegen_shared import _pascal

SQL_TYPE = {
    "string": lambda col: f"VARCHAR({col['length']})",
    "text": lambda col: "VARCHAR",
    "integer": lambda col: "INTEGER",
    "float": lambda col: "DOUBLE PRECISION",
    "decimal": lambda col: (
        f"NUMERIC({db_schema.DECIMAL_PRECISION}, {db_schema.DECIMAL_SCALE})"
    ),
    "boolean": lambda col: "BOOLEAN",
    "date": lambda col: "DATE",
    "datetime": lambda col: "TIMESTAMP(6) WITH TIME ZONE",
    "json": lambda col: "VARCHAR",
}
JAVA_TYPE = {
    "string": "String",
    "text": "String",
    "integer": "Integer",
    "float": "Double",
    "decimal": "BigDecimal",
    "boolean": "Boolean",
    "date": "LocalDate",
    "datetime": "Instant",
    "json": "Object",
}
ON_DELETE = {"cascade": "CASCADE", "set_null": "SET NULL", "restrict": "RESTRICT"}


def q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def class_name(table: dict) -> str:
    return _pascal(table["label"])


def java_name(column: str) -> str:
    return knowledge.identifier_for(column, "camel")


def relation_name(column: str, table: dict) -> str:
    """The @ManyToOne field beside a foreign key column: customer_id ->
    customer, unless another column already takes that Java name."""
    base = column[:-3] if column.endswith("_id") and len(column) > 3 else column
    taken = {java_name(c) for c in table["columns"]} | {"id", "createdAt", "updatedAt"}
    name = java_name(base)
    return f"{name}Ref" if base == column or name in taken else name


def base_column(col: dict, tables: dict) -> dict:
    """A foreign key column has the type of the column it points at."""
    if not col.get("fk"):
        return col
    if col["fk"]["column"] == "id":
        return {**col, "type": "_id"}
    return {
        **tables[col["fk"]["table"]]["columns"][col["fk"]["column"]],
        "nullable": col["nullable"],
    }


def sql_type(col: dict) -> str:
    return "BIGINT" if col["type"] == "_id" else SQL_TYPE[col["type"]](col)


def java_type(col: dict) -> str:
    return "Long" if col["type"] == "_id" else JAVA_TYPE[col["type"]]


def _datetime(value) -> datetime:
    return (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(str(value).replace("Z", ""))
    )


def sql_literal(value, field_type: str) -> str:
    if value is None:
        return "NULL"
    if field_type == "boolean":
        return "TRUE" if value else "FALSE"
    if field_type in ("integer", "float", "_id"):
        return repr(value)
    if field_type == "decimal":
        return str(value)
    if field_type == "date":
        d = value if isinstance(value, date) else date.fromisoformat(str(value))
        return f"DATE '{d.isoformat()}'"
    if field_type == "datetime":
        stamp = _datetime(value).strftime("%Y-%m-%d %H:%M:%S.%f")
        return f"TIMESTAMP WITH TIME ZONE '{stamp}+00:00'"
    if field_type == "json":
        value = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    return "'" + str(value).replace("'", "''") + "'"


def sql_default(col: dict) -> str | None:
    default = col.get("default")
    if not default:
        return None
    if default["kind"] == "now":
        return "CURRENT_TIMESTAMP"
    if default["kind"] == "today":
        return "CURRENT_DATE"
    return sql_literal(default["value"], col["type"])


def column_sql(column: str, col: dict, tables: dict) -> str:
    base = base_column(col, tables)
    parts = [q(column), sql_type(base)]
    default = sql_default(col)
    if default is not None:
        parts.append(f"DEFAULT {default}")
    if not col["nullable"]:
        parts.append("NOT NULL")
    return " ".join(parts)


def check_sql(table: dict, name: str) -> str:
    types = {c: table["columns"][c]["type"] for c in table["columns"]}
    return check_expr.render_storage_sql(
        table["checks"][name]["ast"], types, utc_offset=True, quote_all=True
    )


def fk_sql(column: str, col: dict) -> str:
    fk = col["fk"]
    return (
        f"CONSTRAINT {q(fk['name'])} FOREIGN KEY ({q(column)}) REFERENCES {q(fk['table'])} "
        f"({q(fk['column'])}) ON DELETE {ON_DELETE[fk['on_delete']]}"
    )


def uniques(table: dict) -> list[tuple[str, list[str]]]:
    out = [
        (col["unique"], [c])
        for c in table["column_order"]
        if (col := table["columns"][c])["unique"]
    ]
    out += [(n, list(i["columns"])) for n, i in table["indexes"].items() if i["unique"]]
    return out


def indexes(table: dict) -> list[tuple[str, list[str]]]:
    return [
        (n, list(i["columns"])) for n, i in table["indexes"].items() if not i["unique"]
    ]


# ─── Java literals ───
def java_string(text: str) -> str:
    """A Java string literal. "TODO" is written with a \\u escape (the same
    string once compiled) so user text can't look like a leftover marker."""
    return json.dumps(str(text)).replace("TODO", "TOD\\u004f")


def java_default(col: dict) -> str | None:
    """The field initializer that gives a new entity its default."""
    default = col.get("default")
    if not default:
        return None
    if default["kind"] == "now":
        return "Instant.now()"
    if default["kind"] == "today":
        return "LocalDate.now(ZoneOffset.UTC)"
    value, t = default["value"], col["type"]
    if t in ("string", "text"):
        return java_string(value)
    if t == "integer":
        return str(value)
    if t == "float":
        return repr(float(value))
    if t == "decimal":
        return f'new BigDecimal("{value}")'
    if t == "boolean":
        return "true" if value else "false"
    if t == "date":
        return f'LocalDate.parse("{value}")'
    if t == "datetime":
        return f'Instant.parse("{_datetime(value).isoformat()}Z")'
    return f"JsonText.read({java_string(json.dumps(value, separators=(',', ':'), ensure_ascii=False))})"


def comment(text: str) -> str:
    return " ".join(str(text).split()).replace("TODO", "to-do").replace("*/", "* /")
