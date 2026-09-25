# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Knowledge registry (languages, frameworks, SDLC phases)
#  ai/knowledge/ — What VengaiCode knows about the languages and
#  frameworks it builds with, as data (languages.py, frameworks.py,
#  sdlc.py), and the functions every other part of the app uses it
#  through:
#    field_problem / table_problem   a name that would break the chosen
#        stack's generated code (a keyword once converted to that
#        language's naming, or a name the framework already uses) —
#        db_schema refuses it in the Architecture editor
#    language_rules_for_prompt       the language + framework rules added
#        to every AI code prompt (codegen_shared.generate_text_validated)
#    naming_constraints_for_prompt   names the Architecture AI must avoid
#    phase_rules_for_prompt          good practice for an SDLC phase
#    language_for_path               which language a generated file is
#    catalog                         everything, for GET /api/v1/knowledge
#  Nothing here imports the rest of the app, so anything can import it.
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations

import functools
import re

from app.ai.knowledge.frameworks import FRAMEWORKS, FrameworkSpec, framework
from app.ai.knowledge.languages import LANGUAGES, LanguageSpec, is_keyword, language
from app.ai.knowledge.sdlc import SDLC_PHASES, PhaseSpec, phase

__all__ = [
    "FRAMEWORKS",
    "LANGUAGES",
    "SDLC_PHASES",
    "FrameworkSpec",
    "LanguageSpec",
    "PhaseSpec",
    "catalog",
    "field_problem",
    "framework",
    "identifier_for",
    "language",
    "language_for_path",
    "language_rules_for_prompt",
    "naming_constraints_for_prompt",
    "phase",
    "phase_rules_for_prompt",
    "table_problem",
    "adds_phase_rules",
    "with_phase_rules",
]


def identifier_for(slug: str, case: str) -> str:
    """A snake_case slug as the generated code spells it."""
    parts = [p for p in slug.split("_") if p]
    if not parts:
        return slug
    if case == "camel":
        return parts[0] + "".join(p.capitalize() for p in parts[1:])
    if case == "pascal":
        return "".join(p.capitalize() for p in parts)
    return slug


def _primary_language(fw: FrameworkSpec) -> LanguageSpec | None:
    return language(fw.languages[0]) if fw.languages else None


def field_problem(
    slug: str, backend: str | None, table_name: str | None = None
) -> str | None:
    """Why a field can't have this name in the chosen backend's generated
    code, or None. Phrased to follow '"<slug>" is …'."""
    fw = framework(backend)
    if fw is None:
        return None
    if slug in fw.reserved_fields:
        return f"{fw.reserved_fields[slug]} ({fw.label})"
    lang = _primary_language(fw)
    if lang is not None and fw.field_case in ("snake", "camel", "pascal"):
        name = identifier_for(slug, fw.field_case)
        if is_keyword(name, lang):
            return f"the {lang.label} keyword `{name}` once {fw.label} code names the field"
    if fw.member_named_like_type_forbidden and table_name:
        cls = identifier_for(
            re.sub(r"[^a-z0-9]+", "_", table_name.lower()).strip("_"), "pascal"
        )
        if identifier_for(slug, "pascal") == cls:
            label = lang.label if lang else fw.label
            return f"the name of its own table's class ({cls}) — a {label} property can't share its class's name"
    return None


def table_problem(slug: str, backend: str | None) -> str | None:
    """Why a table can't have this name (its model class would shadow a
    standard type or be a keyword), or None."""
    fw = framework(backend)
    if fw is None:
        return None
    cls = identifier_for(slug, "pascal")
    lang = _primary_language(fw)
    insensitive = bool(lang and lang.keywords_case_insensitive)
    reserved = (
        {t.lower() for t in fw.reserved_types}
        if insensitive
        else set(fw.reserved_types)
    )
    if (cls.lower() if insensitive else cls) in reserved:
        where = f"{lang.label}/{fw.label}" if lang else fw.label
        return f"the name of a standard {where} type ({cls}), which the model class would shadow"
    if lang is not None and is_keyword(cls, lang):
        return (
            f"a {lang.label} keyword once {fw.label} code names the model class ({cls})"
        )
    return None


def _bullets(title: str, rules: tuple[str, ...]) -> list[str]:
    return [f"{title}:"] + [f"- {r}" for r in rules] if rules else []


def language_rules_for_prompt(
    lang_key: str | None, framework_key: str | None = None
) -> str:
    """The rules block added to an AI code prompt — empty when the
    language isn't a programming language the registry knows."""
    lang = language(lang_key)
    fw = framework(framework_key)
    if fw is not None and lang is not None and lang.key not in fw.languages:
        fw = None  # e.g. a package.json written by a Python backend's adapter
    lines: list[str] = []
    if lang is not None:
        lines += _bullets(f"{lang.label} rules (follow all of them)", lang.rules)
        if lang.keywords and len(lang.keywords) <= 120:
            lines.append(
                f"- Reserved words that can't be identifiers: {', '.join(sorted(lang.keywords))}."
            )
    if fw is not None:
        lines += _bullets(f"{fw.label} rules", fw.rules)
    return "\n".join(lines)


def naming_constraints_for_prompt(backend: str | None) -> str:
    """For the Architecture prompt: table/field names the chosen backend
    can't use, so the AI avoids them in the first place."""
    fw = framework(backend)
    if fw is None:
        return ""
    lang = _primary_language(fw)
    notes = []
    if fw.reserved_fields:
        notes.append(
            f"field names {', '.join(sorted(fw.reserved_fields))} (the framework already uses them)"
        )
    if (
        lang is not None
        and fw.field_case in ("snake", "camel", "pascal")
        and lang.keywords
    ):
        # Only words a lower-case field name could actually be.
        sample = ", ".join(
            sorted(w for w in lang.keywords if re.fullmatch(r"[a-z][a-z0-9_]*", w))[:25]
        )
        notes.append(f"{lang.label} keywords as field names (e.g. {sample})")
    if fw.reserved_types:
        notes.append(
            f"table names that would shadow standard types ({', '.join(sorted(fw.reserved_types)[:20])})"
        )
    if fw.member_named_like_type_forbidden:
        notes.append("a field with the same name as its table")
    return f"For {fw.label}, avoid: " + "; ".join(notes) + "." if notes else ""


def phase_rules_for_prompt(phase_key: str | None) -> str:
    spec = phase(phase_key)
    if spec is None:
        return ""
    return "\n".join(_bullets(f"{spec.label} good practice", spec.rules))


_FINAL_INSTRUCTION = re.compile(r"\n+(?=(?:Respond|Return) with ONLY[^\n]*\s*$)")


def with_phase_rules(prompt: str, phase_key: str) -> str:
    """The prompt with its phase's rules added — just before a closing
    "Respond with ONLY …" line when there is one, so that instruction
    stays last."""
    rules = phase_rules_for_prompt(phase_key)
    if not rules:
        return prompt
    match = _FINAL_INSTRUCTION.search(prompt)
    if match:
        return f"{prompt[: match.start()]}\n\n{rules}\n\n{prompt[match.end() :]}"
    return f"{prompt}\n\n{rules}"


def adds_phase_rules(phase_key: str):
    """Decorator for a prompt builder: its result gets with_phase_rules()."""

    def wrap(fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            return with_phase_rules(fn(*args, **kwargs), phase_key)

        return inner

    return wrap


_EXTENSION_INDEX: dict[str, str] = {}
for _spec in LANGUAGES.values():
    for _ext in _spec.extensions:
        _EXTENSION_INDEX.setdefault(_ext, _spec.key)


def language_for_path(path: str) -> LanguageSpec | None:
    lower = path.lower()
    for ext in sorted(_EXTENSION_INDEX, key=len, reverse=True):
        if lower.endswith(ext):
            return LANGUAGES[_EXTENSION_INDEX[ext]]
    return None


def catalog() -> dict:
    return {
        "languages": [
            {
                "key": s.key,
                "label": s.label,
                "extensions": list(s.extensions),
                "typing": s.typing,
                "reserved_words": sorted(s.keywords),
                "avoid_shadowing": sorted(s.avoid),
                "naming": s.naming,
                "comments": {
                    "line": s.line_comment,
                    "block": list(s.block_comment) if s.block_comment else None,
                },
                "toolchain": {
                    "package_manager": s.package_manager,
                    "manifest": s.manifest,
                    "formatter": s.formatter,
                    "linter": s.linter,
                    "test_frameworks": list(s.test_frameworks),
                },
                "rules": list(s.rules),
            }
            for s in LANGUAGES.values()
        ],
        "frameworks": [
            {
                "key": f.key,
                "label": f.label,
                "category": f.category,
                "languages": list(f.languages),
                "orm": f.orm,
                "migrations": f.migrations,
                "layout": f.layout,
                "commands": f.commands,
                "default_port": f.default_port,
                "reserved_field_names": f.reserved_fields,
                "reserved_type_names": sorted(f.reserved_types),
                "docs": f.docs,
                "rules": list(f.rules),
            }
            for f in FRAMEWORKS.values()
        ],
        "sdlc_phases": [
            {
                "key": p.key,
                "label": p.label,
                "methods": list(p.methods),
                "tools": list(p.tools),
                "rules": list(p.rules),
            }
            for p in SDLC_PHASES
        ],
    }
