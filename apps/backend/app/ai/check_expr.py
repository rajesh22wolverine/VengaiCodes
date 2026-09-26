# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Check-Constraint Expression Grammar
#  ai/check_expr.py — A deliberately small, fully-parsed language for
#  an Architecture table's "checks" (business rules a row must satisfy,
#  e.g. "price >= 0"), so a check is never raw text pasted into
#  generated code.
#
#  Why a real parser instead of passing the user's/AI's text through:
#    - The same rule has to become THREE things that must agree: a SQL
#      CHECK constraint (Alembic migration + SQLAlchemy model), a
#      Mongoose document validator (MongoDB has no CHECK constraints),
#      and a Python evaluation used to validate seed rows before they
#      are ever written into a migration. Only a parsed tree can be
#      rendered three ways without drifting.
#    - Rendering from a parsed tree makes injection structurally
#      impossible: identifiers are validated column names and literals
#      are re-quoted by us, so text like "0); DROP TABLE users; --" is a
#      parse error, not a payload.
#    - It lets validation catch the mistakes that actually happen (a
#      typo'd field name, comparing a number column to text) with a
#      clear message, instead of a migration failing at deploy time.
#
#  Supported (case-insensitive keywords):
#    comparisons     a = b, a <> b (also != and ==), <, <=, >, >=
#    null tests      a IS NULL, a IS NOT NULL
#    membership      a [NOT] IN ('x', 'y', 3)
#    ranges          a [NOT] BETWEEN low AND high
#    patterns        a [NOT] LIKE 'text%'   (% = any run, _ = one char)
#    length          LENGTH(field)  (alias LEN)
#    boolean field   is_active       (shorthand for is_active = TRUE)
#    combinators     AND / OR / NOT, also && / || / !, and ( ... )
#  Operands are a field name, a number, a 'single-quoted' string, TRUE
#  or FALSE. No arithmetic and no other functions, on purpose.
#
#  "Identical meaning everywhere" is enforced, not assumed — each rule
#  below exists because SQLite, Postgres, Python and JS really do
#  disagree otherwise (the SQLite half is pinned by a differential test
#  that runs render_sql() output as a real CHECK and compares it with
#  evaluate() row by row):
#    - LIKE is case-insensitive for A-Z. SQLite's LIKE already is and
#      can't portably be made otherwise, so Postgres gets the same
#      meaning via LOWER() on both sides whenever the pattern has a
#      letter in it. A backslash in a pattern is always a literal
#      backslash (Postgres would otherwise treat it as an escape).
#    - Text can only be tested for equality (=, <>, IN, LIKE, LENGTH),
#      never ordered (<, >, BETWEEN): text ordering follows the
#      database's collation, which differs between SQLite (code points)
#      and a typical Postgres (en_US — "B" < "a" in one, not the other).
#    - Date/time constants are 'YYYY-MM-DD' (dates) or
#      'YYYY-MM-DDTHH:MM[:SS[.ffffff]]' (date-times), without a time
#      zone. The AST stores them in that canonical ISO form, and
#      render_storage_sql() writes date-times the way SQLAlchemy stores
#      them on SQLite ('YYYY-MM-DD HH:MM:SS.ffffff'), because SQLite
#      compares dates as plain text.
#
#  Semantics follow SQL's three-valued logic: a comparison involving
#  NULL is UNKNOWN (None), and a CHECK constraint only rejects a row
#  when the expression is definitely FALSE — UNKNOWN passes. evaluate()
#  below and the generated JS evaluator both implement exactly that, so
#  "price >= 0" accepts a row whose price is NULL in all three places.
#
#  AST (plain JSON-serializable dicts — embedded verbatim into generated
#  JS, stored in schema snapshots):
#    {"and": [node, ...]} | {"or": [node, ...]} | {"not": node}
#    {"cmp": "=|<>|<|<=|>|>=", "left": operand, "right": operand}
#    {"is_null": operand, "negated": bool}
#    {"in": operand, "values": [literal, ...], "negated": bool}
#    {"between": operand, "low": operand, "high": operand, "negated": bool}
#    {"like": operand, "pattern": str, "negated": bool}
#  operand:
#    {"field": column_slug} | {"value": number|str|bool} | {"length": operand}
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

MAX_EXPRESSION_LENGTH = 500
# Parentheses / NOT nesting depth. Far beyond any real business rule,
# and low enough that the recursive parser and tree walkers can never
# hit Python's recursion limit (500 characters of "(((" otherwise can).
MAX_NESTING = 32

NUMERIC_TYPES = frozenset({"integer", "float", "decimal"})
TEXT_TYPES = frozenset({"string", "text"})
TEMPORAL_TYPES = frozenset({"date", "datetime"})

GRAMMAR_HELP = (
    "Checks support comparisons (=, <>, <, <=, >, >=), IS [NOT] NULL, [NOT] IN (...), "
    "[NOT] BETWEEN ... AND ..., [NOT] LIKE '...', LENGTH(field), and AND/OR/NOT with "
    "parentheses. Text values go in 'single quotes'."
)

# Words that must be double-quoted if a column happens to use them —
# the union of what SQLAlchemy itself quotes for Postgres and SQLite
# (so the CHECK text agrees with the DDL SQLAlchemy emits for the same
# column) plus the rest of both databases' keyword lists. Quoting a
# word that didn't strictly need it is harmless in both; everything
# else is emitted bare so the generated SQL stays readable.
_SQL_RESERVED = frozenset(
    """
    abort action add after all alter always analyse analyze and any array as asc
    asymmetric attach authorization autoincrement before begin between binary both
    by cascade case cast check collate collation column commit concurrently conflict
    constraint create cross current current_catalog current_date current_role
    current_schema current_time current_timestamp current_user database default
    deferrable deferred delete desc detach distinct do drop each else end escape
    except exclude exclusive exists explain fail false fetch filter first following
    for foreign freeze from full generated glob grant group groups having if ignore
    ilike immediate in index indexed initially inner insert instead intersect into is
    isnull join key last lateral leading left like limit localtime localtimestamp
    match materialized natural new no not nothing notnull null nulls of off offset
    old on only or order others outer over overlaps partition placing plan pragma
    preceding primary query raise range recursive references regexp reindex release
    rename replace restrict returning right rollback row rows savepoint select
    session_user set similar some symmetric system_user table tablesample temp
    temporary then ties to trailing transaction trigger true unbounded union unique
    update user using vacuum values variadic verbose view virtual when where window
    with without
    """.split()
)


class CheckExpressionError(ValueError):
    """Unparseable or ill-typed check expression — message is user-facing."""


# ───────────────────────────────────────────────
#  Tokenizer
# ───────────────────────────────────────────────
_TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<number>\d+(?:\.\d+)?)
  | (?P<string>'(?:[^']|'')*')
  | (?P<dquote>"[^"]*"?)
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>>=|<=|<>|!=|==|&&|\|\||[=<>(),!\-])
    """,
    re.VERBOSE,
)

_KEYWORDS = frozenset(
    {"and", "or", "not", "is", "null", "in", "between", "like", "true", "false"}
)
_FUNCTIONS = {"length": "length", "len": "length"}


class _Tok:
    __slots__ = ("kind", "text", "pos")

    def __init__(self, kind: str, text: str, pos: int):
        self.kind = kind  # number | string | ident | kw | op | end
        self.text = text
        self.pos = pos

    def is_kw(self, *words: str) -> bool:
        return self.kind == "kw" and self.text in words

    def is_op(self, *ops: str) -> bool:
        return self.kind == "op" and self.text in ops


def _tokenize(text: str) -> list[_Tok]:
    tokens: list[_Tok] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m:
            raise CheckExpressionError(
                f'Unexpected "{text[pos]}" at position {pos + 1}. {GRAMMAR_HELP}'
            )
        kind = m.lastgroup
        value = m.group()
        if kind == "dquote":
            raise CheckExpressionError(
                f"Use single quotes around text values (found {value} at position "
                f"{pos + 1}) — double quotes mean a column name in SQL."
            )
        if kind == "ident" and value.lower() in _KEYWORDS:
            tokens.append(_Tok("kw", value.lower(), pos))
        elif kind != "ws":
            tokens.append(_Tok(kind, value, pos))
        pos = m.end()
    tokens.append(_Tok("end", "", len(text)))
    return tokens


# ───────────────────────────────────────────────
#  Parser (recursive descent)
# ───────────────────────────────────────────────
class _Parser:
    def __init__(self, text: str):
        self.text = text
        self.tokens = _tokenize(text)
        self.i = 0
        self.depth = 0

    @property
    def tok(self) -> _Tok:
        return self.tokens[self.i]

    def advance(self) -> _Tok:
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def fail(self, what: str) -> CheckExpressionError:
        tok = self.tok
        found = "the end of the expression" if tok.kind == "end" else f'"{tok.text}"'
        return CheckExpressionError(
            f"Expected {what} but found {found} at position {tok.pos + 1}. {GRAMMAR_HELP}"
        )

    def nest(self) -> None:
        self.depth += 1
        if self.depth > MAX_NESTING:
            raise CheckExpressionError(
                f"Check expressions can nest parentheses/NOT at most {MAX_NESTING} deep."
            )

    def parse(self) -> dict:
        node = self.parse_or()
        if self.tok.kind != "end":
            raise self.fail("AND, OR or the end of the expression")
        return node

    def parse_or(self) -> dict:
        args = [self.parse_and()]
        while self.tok.is_kw("or") or self.tok.is_op("||"):
            self.advance()
            args.append(self.parse_and())
        return args[0] if len(args) == 1 else {"or": args}

    def parse_and(self) -> dict:
        args = [self.parse_not()]
        while self.tok.is_kw("and") or self.tok.is_op("&&"):
            self.advance()
            args.append(self.parse_not())
        return args[0] if len(args) == 1 else {"and": args}

    def parse_not(self) -> dict:
        if self.tok.is_kw("not") or self.tok.is_op("!"):
            self.advance()
            self.nest()
            node = {"not": self.parse_not()}
            self.depth -= 1
            return node
        return self.parse_predicate()

    def parse_predicate(self) -> dict:
        if self.tok.is_op("("):
            self.advance()
            self.nest()
            node = self.parse_or()
            if not self.tok.is_op(")"):
                raise self.fail('a closing ")"')
            self.advance()
            self.depth -= 1
            return node

        left = self.parse_operand()
        tok = self.tok

        if tok.is_op("=", "==", "<>", "!=", "<", "<=", ">", ">="):
            self.advance()
            op = {"==": "=", "!=": "<>"}.get(tok.text, tok.text)
            return {"cmp": op, "left": left, "right": self.parse_operand()}

        if tok.is_kw("is"):
            self.advance()
            negated = False
            if self.tok.is_kw("not"):
                self.advance()
                negated = True
            if not self.tok.is_kw("null"):
                raise self.fail("NULL after IS")
            self.advance()
            return {"is_null": left, "negated": negated}

        negated = False
        if tok.is_kw("not"):
            self.advance()
            negated = True
            if not self.tok.is_kw("in", "between", "like"):
                raise self.fail("IN, BETWEEN or LIKE after NOT")

        if self.tok.is_kw("in"):
            self.advance()
            if not self.tok.is_op("("):
                raise self.fail('"(" after IN')
            self.advance()
            values = [self.parse_literal()]
            while self.tok.is_op(","):
                self.advance()
                values.append(self.parse_literal())
            if not self.tok.is_op(")"):
                raise self.fail('"," or ")" in the IN list')
            self.advance()
            return {"in": left, "values": values, "negated": negated}

        if self.tok.is_kw("between"):
            self.advance()
            low = self.parse_operand()
            if not self.tok.is_kw("and"):
                raise self.fail("AND inside BETWEEN ... AND ...")
            self.advance()
            high = self.parse_operand()
            return {"between": left, "low": low, "high": high, "negated": negated}

        if self.tok.is_kw("like"):
            self.advance()
            if self.tok.kind != "string":
                raise self.fail("a 'quoted' pattern after LIKE")
            pattern = _unquote(self.advance().text)
            return {"like": left, "pattern": pattern, "negated": negated}

        # A bare operand used as a whole predicate — only meaningful for a
        # boolean field ("is_active AND price > 0"); type_check() enforces
        # that, so here it's just sugar for "= TRUE".
        if "field" in left:
            return {"cmp": "=", "left": left, "right": {"value": True}}
        raise self.fail("a comparison operator, IS, IN, BETWEEN or LIKE")

    def parse_operand(self) -> dict:
        tok = self.tok
        if tok.kind == "ident":
            self.advance()
            fn = _FUNCTIONS.get(tok.text.lower())
            if fn and self.tok.is_op("("):
                self.advance()
                self.nest()
                arg = self.parse_operand()
                if not self.tok.is_op(")"):
                    raise self.fail(f'")" to close {tok.text.upper()}(')
                self.advance()
                self.depth -= 1
                return {fn: arg}
            return {"field": tok.text}
        if (
            tok.kind in ("number", "string")
            or tok.is_kw("true", "false")
            or tok.is_op("-")
        ):
            return {"value": self.parse_literal()}
        raise self.fail("a field name or a value")

    def parse_literal(self) -> Any:
        tok = self.tok
        if tok.is_op("-"):
            self.advance()
            if self.tok.kind != "number":
                raise self.fail('a number after "-"')
            return -_number(self.advance().text)
        if tok.kind == "number":
            self.advance()
            return _number(tok.text)
        if tok.kind == "string":
            self.advance()
            return _unquote(tok.text)
        if tok.is_kw("true", "false"):
            self.advance()
            return tok.text == "true"
        raise self.fail("a value (number, 'text', TRUE or FALSE)")


def _number(text: str) -> int | float:
    return float(text) if "." in text else int(text)


def _unquote(text: str) -> str:
    return text[1:-1].replace("''", "'")


def parse(expression: str) -> dict:
    """Parses a check expression into its AST. Field names are returned
    exactly as written — bind_fields() resolves them to column slugs."""
    text = "" if expression is None else str(expression).strip()
    if not text:
        raise CheckExpressionError("A check needs an expression, e.g. price >= 0.")
    if len(text) > MAX_EXPRESSION_LENGTH:
        raise CheckExpressionError(
            f"Check expressions are limited to {MAX_EXPRESSION_LENGTH} characters."
        )
    if "\x00" in text:
        # Postgres rejects NUL in any text value, so a literal holding one
        # could never reach the database.
        raise CheckExpressionError("Check expressions can't contain a NUL character.")
    return _Parser(text).parse()


# ───────────────────────────────────────────────
#  Tree walking helpers
# ───────────────────────────────────────────────
def _operands(node: dict) -> list[dict]:
    if "cmp" in node:
        return [node["left"], node["right"]]
    if "is_null" in node:
        return [node["is_null"]]
    if "in" in node:
        return [node["in"]]
    if "between" in node:
        return [node["between"], node["low"], node["high"]]
    if "like" in node:
        return [node["like"]]
    return []


def _children(node: dict) -> list[dict]:
    if "and" in node:
        return node["and"]
    if "or" in node:
        return node["or"]
    if "not" in node:
        return [node["not"]]
    return []


def _operand_fields(operand: dict) -> list[str]:
    if "field" in operand:
        return [operand["field"]]
    if "length" in operand:
        return _operand_fields(operand["length"])
    return []


def referenced_fields(ast: dict) -> list[str]:
    """Every field name the expression reads, in first-seen order."""
    seen: list[str] = []
    stack = [ast]
    while stack:
        node = stack.pop(0)
        for operand in _operands(node):
            for name in _operand_fields(operand):
                if name not in seen:
                    seen.append(name)
        stack[0:0] = _children(node)
    return seen


def _map_operands(ast: dict, fn) -> dict:
    """Copy of the AST with fn(operand) applied to every top-level operand
    of every predicate (fn handles LENGTH nesting itself)."""

    def walk(node: dict) -> dict:
        if "and" in node:
            return {"and": [walk(n) for n in node["and"]]}
        if "or" in node:
            return {"or": [walk(n) for n in node["or"]]}
        if "not" in node:
            return {"not": walk(node["not"])}
        out = dict(node)
        for key in ("left", "right", "is_null", "in", "between", "low", "high", "like"):
            if key in out:
                out[key] = fn(out[key])
        if "values" in out:
            out["values"] = list(out["values"])
        return out

    return walk(ast)


def bind_fields(ast: dict, resolve_name) -> dict:
    """Returns a copy of the AST with every field reference replaced by
    resolve_name(name) — the table's real column slug. resolve_name
    raises CheckExpressionError for an unknown field."""

    def bind_operand(operand: dict) -> dict:
        if "field" in operand:
            return {"field": resolve_name(operand["field"])}
        if "length" in operand:
            return {"length": bind_operand(operand["length"])}
        return dict(operand)

    return _map_operands(ast, bind_operand)


# ───────────────────────────────────────────────
#  Temporal literals
# ───────────────────────────────────────────────
# Deliberately strict: exactly the shapes every consumer (SQLite text
# comparison, Postgres casts, Python, JS Date) reads the same way.
_TEMPORAL_LITERAL_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,6}))?)?)?$"
)
_TZ_SUFFIX_RE = re.compile(r"(?:[zZ]|[+-]\d{2}:?\d{2})$")


def _parse_temporal_literal(value: str) -> tuple[datetime, bool] | None:
    """(value, has_time) for a valid zone-less date/date-time literal."""
    m = _TEMPORAL_LITERAL_RE.match(value)
    if not m:
        return None
    try:
        day = date.fromisoformat(m.group(1))
        if m.group(2) is None:
            return datetime(day.year, day.month, day.day), False
        micro = int((m.group(5) or "0").ljust(6, "0"))
        stamp = datetime(
            day.year,
            day.month,
            day.day,
            int(m.group(2)),
            int(m.group(3)),
            int(m.group(4) or 0),
            micro,
        )
        return stamp, True
    except ValueError:
        return None


def _iso_literal(stamp: datetime, field_type: str) -> str:
    if field_type == "date":
        return stamp.date().isoformat()
    return stamp.isoformat()


def _storage_literal(stamp: datetime, field_type: str) -> str:
    """How SQLAlchemy writes the value to SQLite (where dates are text
    and compared as text), which Postgres also accepts as input."""
    if field_type == "date":
        return stamp.date().isoformat()
    return stamp.strftime("%Y-%m-%d %H:%M:%S.%f")


# ───────────────────────────────────────────────
#  Type checking
# ───────────────────────────────────────────────
def _literal_kind(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    return "text"


def _field_type(name: str, column_types: dict[str, str]) -> str:
    try:
        return column_types[name]
    except KeyError:
        raise CheckExpressionError(f'"{name}" isn\'t a known field.') from None


def _operand_kind(operand: dict, column_types: dict[str, str]) -> tuple[str, str]:
    """(kind, label) — kind is number|text|boolean|date|datetime|json."""
    if "field" in operand:
        col_type = _field_type(operand["field"], column_types)
        if col_type in NUMERIC_TYPES:
            return "number", operand["field"]
        if col_type in TEXT_TYPES:
            return "text", operand["field"]
        return col_type, operand["field"]  # boolean | date | datetime | json
    if "length" in operand:
        inner_kind, inner_label = _operand_kind(operand["length"], column_types)
        if inner_kind != "text":
            raise CheckExpressionError(
                f"LENGTH() only works on text fields, and {inner_label} isn't text."
            )
        return "number", f"LENGTH({inner_label})"
    value = operand["value"]
    if isinstance(value, bool):
        return "boolean", "TRUE" if value else "FALSE"
    if isinstance(value, str):
        return "text", f"'{value}'"
    return "number", repr(value)


def _kind_label(kind: str) -> str:
    return {
        "number": "a number",
        "text": "text",
        "boolean": "true/false",
        "date": "a date",
        "datetime": "a date/time",
        "json": "JSON",
    }.get(kind, kind)


def _check_temporal_literal(kind: str, label: str, value: Any) -> None:
    if not isinstance(value, str):
        raise CheckExpressionError(
            f"{label} is {_kind_label(kind)}, so compare it with a 'YYYY-MM-DD' value."
        )
    if _TZ_SUFFIX_RE.search(value.strip()) and _TEMPORAL_LITERAL_RE.match(
        _TZ_SUFFIX_RE.sub("", value.strip())
    ):
        raise CheckExpressionError(
            f"Write '{value}' without a time zone (e.g. '2024-01-31T09:30:00') — "
            "check values are compared as plain date/times."
        )
    parsed = _parse_temporal_literal(value)
    if parsed is None:
        raise CheckExpressionError(
            f"'{value}' isn't a date {label} can be compared with — write it like "
            f"'2024-01-31'{'' if kind == 'date' else ' or 2024-01-31T09:30:00'}."
        )
    if kind == "date" and parsed[1]:
        raise CheckExpressionError(
            f"{label} is a date (no time of day), so compare it with a date like "
            f"'{parsed[0].date().isoformat()}', not '{value}'."
        )


def _check_pair(
    left: dict, right: dict, column_types: dict[str, str], context: str
) -> tuple[str, str]:
    """Validates that two operands can meet in one comparison; returns
    the shared kind (the field's side when one is a temporal literal)."""
    lk, llabel = _operand_kind(left, column_types)
    rk, rlabel = _operand_kind(right, column_types)
    if "json" in (lk, rk):
        raise CheckExpressionError(
            f"JSON fields can't be compared in a check ({context})."
        )
    if lk == rk:
        return lk
    temporal = {"date", "datetime"}
    if lk in temporal and rk in temporal:
        return "datetime"
    # A date/datetime column compares against a 'YYYY-MM-DD[THH:MM:SS]'
    # text literal — the only way to write a date constant in this grammar.
    # Only a literal qualifies: a date column vs a text COLUMN is a mistake.
    for kind, label, other_kind, other in (
        (lk, llabel, rk, right),
        (rk, rlabel, lk, left),
    ):
        if kind in temporal and other_kind == "text" and "value" in other:
            _check_temporal_literal(kind, label, other["value"])
            return kind
    for kind, label, other_kind, other in (
        (lk, llabel, rk, right),
        (rk, rlabel, lk, left),
    ):
        if kind != "boolean" and other_kind == "boolean" and "value" in other:
            raise CheckExpressionError(
                f"{label} isn't a true/false field, so it can't be used on its own or "
                f"compared with TRUE/FALSE — compare it with a value instead."
            )
    raise CheckExpressionError(
        f"{llabel} ({_kind_label(lk)}) can't be compared with {rlabel} "
        f"({_kind_label(rk)}) in {context}."
    )


_ORDERING_HELP = {
    "boolean": "TRUE/FALSE values can only be compared with = or <>",
    "text": (
        "text can only be compared with =, <>, IN, LIKE or LENGTH() — ordering text "
        "depends on the database's collation, so it wouldn't mean the same thing everywhere"
    ),
}


def _has_field(operands: list[dict]) -> bool:
    return any(_operand_fields(o) for o in operands)


def type_check(ast: dict, column_types: dict[str, str]) -> None:
    """Raises CheckExpressionError if any comparison mixes incompatible
    types. `ast` must already be bound (bind_fields) so every field is a
    real key of column_types."""

    def check(node: dict) -> None:
        for child in _children(node):
            check(child)
        operands = _operands(node)
        if operands and not _has_field(operands):
            raise CheckExpressionError(
                "A check has to involve at least one field — comparing fixed "
                "values is always the same answer."
            )
        if "cmp" in node:
            kind = _check_pair(
                node["left"], node["right"], column_types, f'"{node["cmp"]}"'
            )
            if node["cmp"] not in ("=", "<>") and kind in _ORDERING_HELP:
                raise CheckExpressionError(
                    f"{_ORDERING_HELP[kind]} (found {node['cmp']})."
                )
        elif "is_null" in node:
            _operand_kind(node["is_null"], column_types)
        elif "in" in node:
            for value in node["values"]:
                _check_pair(node["in"], {"value": value}, column_types, "IN (...)")
        elif "between" in node:
            kind = _check_pair(node["between"], node["low"], column_types, "BETWEEN")
            _check_pair(node["between"], node["high"], column_types, "BETWEEN")
            if kind in _ORDERING_HELP:
                raise CheckExpressionError(f"{_ORDERING_HELP[kind]} (found BETWEEN).")
        elif "like" in node:
            kind, label = _operand_kind(node["like"], column_types)
            if kind != "text":
                raise CheckExpressionError(
                    f"LIKE only works on text fields, and {label} isn't text."
                )

    check(ast)


def _rewrite_temporal_literals(ast: dict, column_types: dict[str, str], render) -> dict:
    """Copy of a type-checked AST with every text literal that meets a
    date/datetime FIELD replaced by render(parsed datetime, field type)."""

    def temporal_type(operand: dict) -> str | None:
        if "field" in operand:
            t = column_types.get(operand["field"])
            return t if t in TEMPORAL_TYPES else None
        return None

    def fix(value: Any, field_type: str | None) -> Any:
        if field_type is None or not isinstance(value, str):
            return value
        parsed = _parse_temporal_literal(value)
        return value if parsed is None else render(parsed[0], field_type)

    def walk(node: dict) -> dict:
        if "and" in node:
            return {"and": [walk(n) for n in node["and"]]}
        if "or" in node:
            return {"or": [walk(n) for n in node["or"]]}
        if "not" in node:
            return {"not": walk(node["not"])}
        out = dict(node)
        if "cmp" in out:
            lt, rt = temporal_type(out["left"]), temporal_type(out["right"])
            if "value" in out["left"]:
                out["left"] = {"value": fix(out["left"]["value"], rt)}
            if "value" in out["right"]:
                out["right"] = {"value": fix(out["right"]["value"], lt)}
        elif "in" in out:
            ft = temporal_type(out["in"])
            out["values"] = [fix(v, ft) for v in out["values"]]
        elif "between" in out:
            ft = temporal_type(out["between"])
            for key in ("low", "high"):
                if "value" in out[key]:
                    out[key] = {"value": fix(out[key]["value"], ft)}
        return out

    return walk(ast)


def canonicalize_literals(ast: dict, column_types: dict[str, str]) -> dict:
    """Rewrites date/time literals of a bound, type-checked AST into
    canonical ISO form ('2024-01-31' for a date field, '2024-01-31T09:30:00'
    for a date-time field) so every consumer of the stored AST parses
    exactly one shape."""
    return _rewrite_temporal_literals(ast, column_types, _iso_literal)


# ───────────────────────────────────────────────
#  Rendering — SQL
# ───────────────────────────────────────────────
def sql_identifier(name: str) -> str:
    return f'"{name}"' if name.lower() in _SQL_RESERVED else name


def sql_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def quoted_identifier(name: str) -> str:
    """Always quoted — for an ORM that quotes every identifier (Hibernate
    with globally_quoted_identifiers), where an unquoted name would be
    upper-cased by the database and no longer match."""
    return f'"{name}"'


def _sql_operand(operand: dict, ident=sql_identifier) -> str:
    if "field" in operand:
        return ident(operand["field"])
    if "length" in operand:
        return f"LENGTH({_sql_operand(operand['length'], ident)})"
    return sql_literal(operand["value"])


def _sql_like(node: dict, neg: str, ident=sql_identifier) -> str:
    target = _sql_operand(node["like"], ident)
    pattern = node["pattern"]
    escape = ""
    if "\\" in pattern:
        # Postgres treats "\" as LIKE's escape character by default and
        # SQLite doesn't; declaring it explicitly (and doubling each one)
        # makes it a literal backslash in both.
        pattern = pattern.replace("\\", "\\\\")
        escape = " ESCAPE '\\'"
    literal = sql_literal(pattern)
    if re.search(r"[A-Za-z]", pattern):
        # SQLite's LIKE ignores A-Z case; LOWER() both sides so Postgres
        # (case-sensitive LIKE) means the same thing.
        return f"LOWER({target}) {neg}LIKE LOWER({literal}){escape}"
    return f"{target} {neg}LIKE {literal}{escape}"


def render_sql(ast: dict, ident=sql_identifier) -> str:
    """Portable SQL for SQLite and Postgres (the two databases the
    deterministic FastAPI target supports via DATABASE_URL)."""

    def render(node: dict, top: bool = False) -> str:
        if "and" in node or "or" in node:
            joiner = " AND " if "and" in node else " OR "
            text = joiner.join(render(n) for n in _children(node))
            return text if top else f"({text})"
        if "not" in node:
            return f"NOT {render(node['not'])}"
        if "cmp" in node:
            return f"{_sql_operand(node['left'], ident)} {node['cmp']} {_sql_operand(node['right'], ident)}"
        if "is_null" in node:
            return f"{_sql_operand(node['is_null'], ident)} IS {'NOT ' if node['negated'] else ''}NULL"
        neg = "NOT " if node.get("negated") else ""
        if "in" in node:
            values = ", ".join(sql_literal(v) for v in node["values"])
            return f"{_sql_operand(node['in'], ident)} {neg}IN ({values})"
        if "between" in node:
            return (
                f"{_sql_operand(node['between'], ident)} {neg}BETWEEN "
                f"{_sql_operand(node['low'], ident)} AND {_sql_operand(node['high'], ident)}"
            )
        if "like" in node:
            return _sql_like(node, neg, ident)
        raise ValueError(f"Unknown check node: {node!r}")

    return render(ast, top=True)


def render_storage_sql(
    ast: dict,
    column_types: dict[str, str],
    fractional_digits: int = 6,
    utc_offset: bool = False,
    quote_all: bool = False,
) -> str:
    """render_sql() with date-time literals written the way the ORM
    stores date-times on SQLite: SQLAlchemy writes '2024-01-31
    09:30:00.000000' (the default), TypeORM '2024-01-31 09:30:00.000'
    (fractional_digits=3). SQLite compares dates as text, so a literal in
    any other shape (a 'T', fewer digits) would silently compare wrong
    there; Postgres reads either form. utc_offset adds "+00:00" for a
    TIMESTAMP WITH TIME ZONE column (so the database never reads the
    literal in its own zone); quote_all quotes every identifier."""

    def render(stamp: datetime, field_type: str) -> str:
        text = _storage_literal(stamp, field_type)
        if field_type == "date":
            return text
        if fractional_digits != 6:
            text = text[: len(text) - (6 - fractional_digits)]
        return text + "+00:00" if utc_offset else text

    return render_sql(
        _rewrite_temporal_literals(ast, column_types, render),
        quoted_identifier if quote_all else sql_identifier,
    )


# ───────────────────────────────────────────────
#  Evaluation — Python (three-valued, mirrors SQL)
# ───────────────────────────────────────────────
def _to_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(
                tzinfo=None
            )
        except ValueError:
            return None
    return None


def _to_number(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _eval_operand(
    operand: dict, row: dict, column_types: dict[str, str]
) -> tuple[Any, str]:
    if "field" in operand:
        name = operand["field"]
        return row.get(name), column_types.get(name, "string")
    if "length" in operand:
        inner, _ = _eval_operand(operand["length"], row, column_types)
        return (None if inner is None else len(str(inner))), "integer"
    value = operand["value"]
    kind = _literal_kind(value)
    return value, {"number": "float", "boolean": "boolean"}.get(kind, "string")


def _coerce_pair(a: Any, a_type: str, b: Any, b_type: str) -> tuple[Any, Any]:
    if a_type in TEMPORAL_TYPES or b_type in TEMPORAL_TYPES:
        return _to_datetime(a), _to_datetime(b)
    if a_type in NUMERIC_TYPES or b_type in NUMERIC_TYPES:
        return _to_number(a), _to_number(b)
    return a, b


def _compare(op: str, a: Any, b: Any) -> bool | None:
    if a is None or b is None:
        return None
    try:
        return {
            "=": a == b,
            "<>": a != b,
            "<": a < b,
            "<=": a <= b,
            ">": a > b,
            ">=": a >= b,
        }[op]
    except TypeError:
        return None


def _like_regex(pattern: str) -> re.Pattern:
    out = []
    for ch in pattern:
        if ch == "%":
            out.append(".*")
        elif ch == "_":
            out.append(".")
        else:
            out.append(re.escape(ch))
    # IGNORECASE + ASCII = only A-Z/a-z fold, exactly SQLite's LIKE.
    return re.compile("^" + "".join(out) + "$", re.DOTALL | re.IGNORECASE | re.ASCII)


def evaluate(
    ast: dict, row: dict, column_types: dict[str, str] | None = None
) -> bool | None:
    """True / False / None (SQL UNKNOWN). A CHECK constraint rejects a
    row only when this returns False."""
    types = column_types or {}

    def ev(node: dict) -> bool | None:
        if "and" in node:
            results = [ev(n) for n in node["and"]]
            if any(r is False for r in results):
                return False
            return None if any(r is None for r in results) else True
        if "or" in node:
            results = [ev(n) for n in node["or"]]
            if any(r is True for r in results):
                return True
            return None if any(r is None for r in results) else False
        if "not" in node:
            inner = ev(node["not"])
            return None if inner is None else not inner
        if "cmp" in node:
            a, at = _eval_operand(node["left"], row, types)
            b, bt = _eval_operand(node["right"], row, types)
            a, b = _coerce_pair(a, at, b, bt)
            return _compare(node["cmp"], a, b)
        if "is_null" in node:
            value, _ = _eval_operand(node["is_null"], row, types)
            result = value is None
            return (not result) if node["negated"] else result
        if "in" in node:
            value, vt = _eval_operand(node["in"], row, types)
            if value is None:
                return None
            hit = False
            for candidate in node["values"]:
                a, b = _coerce_pair(
                    value,
                    vt,
                    candidate,
                    "float" if _literal_kind(candidate) == "number" else "string",
                )
                if _compare("=", a, b):
                    hit = True
                    break
            return (not hit) if node["negated"] else hit
        if "between" in node:
            value, vt = _eval_operand(node["between"], row, types)
            low, lt = _eval_operand(node["low"], row, types)
            high, ht = _eval_operand(node["high"], row, types)
            v1, lo = _coerce_pair(value, vt, low, lt)
            v2, hi = _coerce_pair(value, vt, high, ht)
            ge = _compare(">=", v1, lo)
            le = _compare("<=", v2, hi)
            if ge is False or le is False:
                result: bool | None = False
            elif ge is None or le is None:
                result = None
            else:
                result = True
            if result is None:
                return None
            return (not result) if node["negated"] else result
        if "like" in node:
            value, _ = _eval_operand(node["like"], row, types)
            if value is None:
                return None
            hit = bool(_like_regex(node["pattern"]).match(str(value)))
            return (not hit) if node["negated"] else hit
        raise ValueError(f"Unknown check node: {node!r}")

    return ev(ast)
