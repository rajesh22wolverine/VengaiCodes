# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Grammar-based syntax checking
#  ai/syntax_check.py — Parses generated files with the real grammar of
#  their language (tree-sitter; one small prebuilt grammar package per
#  language, pinned in requirements.txt — nothing is downloaded at run
#  time) and reports the first syntax error with its line. Replaces the
#  old "count the brackets" heuristic for every language that has a
#  grammar; Python keeps ast.parse (CPython's own parser).
#
#  The grammar comes from the FILE when its path is known (extension →
#  knowledge.language_for_path), because a GeneratedFile's `language`
#  label isn't always the file's language (a Cargo.toml written by a Rust
#  adapter, a .vue component labelled "javascript"). A path with no
#  known extension (go.mod, Gemfile, Dockerfile) isn't grammar-checked.
#  Vue/Svelte single-file components: each <script> block is parsed with
#  the JS/TS grammar; template syntax isn't HTML, so templates aren't.
#
#  Returns a user-facing problem string, or None when the file parses —
#  or when there's no grammar for it (the caller falls back to its
#  heuristic).
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations

import importlib
import re
from functools import lru_cache

from app.ai import knowledge

try:  # the grammars are an optional speed-up of correctness, never a hard dependency
    from tree_sitter import Language, Node, Parser
except ImportError:  # pragma: no cover — requirements.txt installs it
    Language = Node = Parser = None  # type: ignore[assignment,misc]

# language key -> (grammar module, function returning the language pointer)
_GRAMMARS: dict[str, tuple[str, str]] = {
    "python": ("tree_sitter_python", "language"),
    "javascript": ("tree_sitter_javascript", "language"),
    "typescript": ("tree_sitter_typescript", "language_typescript"),
    "tsx": ("tree_sitter_typescript", "language_tsx"),
    "java": ("tree_sitter_java", "language"),
    "kotlin": ("tree_sitter_kotlin", "language"),
    "csharp": ("tree_sitter_c_sharp", "language"),
    "go": ("tree_sitter_go", "language"),
    "rust": ("tree_sitter_rust", "language"),
    "php": ("tree_sitter_php", "language_php"),
    "ruby": ("tree_sitter_ruby", "language"),
    "dart": ("tree_sitter_dart", "language"),
    "swift": ("tree_sitter_swift", "language"),
    "gdscript": ("tree_sitter_gdscript", "language"),
    "lua": ("tree_sitter_lua", "language"),
    "cpp": ("tree_sitter_cpp", "language"),
    "html": ("tree_sitter_html", "language"),
    "css": ("tree_sitter_css", "language"),
    "json": ("tree_sitter_json", "language"),
    "yaml": ("tree_sitter_yaml", "language"),
    "toml": ("tree_sitter_toml", "language"),
    "xml": ("tree_sitter_xml", "language_xml"),
    "bash": ("tree_sitter_bash", "language"),
    # No SQL: every database has its own dialect (SQLite's AUTOINCREMENT,
    # Postgres's SERIAL…) and the one generic grammar rejects valid DDL.
}

_SFC_SUFFIXES = (".vue", ".svelte")
_SCRIPT_BLOCK = re.compile(
    r"<script\b([^>]*)>(.*?)</script\s*>", re.DOTALL | re.IGNORECASE
)


@lru_cache(maxsize=None)
def _language(key: str):
    if Language is None or key not in _GRAMMARS:
        return None
    module, fn = _GRAMMARS[key]
    try:
        return Language(getattr(importlib.import_module(module), fn)())
    except (ImportError, AttributeError, ValueError):
        return None


def available(key: str) -> bool:
    return _language(key) is not None


def _tolerated(node: Node, data: bytes) -> bool:
    """Grammar gaps checked against real compilers: tree-sitter's JSX
    grammar rejects a bare `&` in element text ("Approve & Continue"),
    which TypeScript, Babel and esbuild all accept."""
    return (
        node.type == "ERROR"
        and node.parent is not None
        and node.parent.type in ("jsx_element", "jsx_fragment")
        and data[node.start_byte : node.end_byte].lstrip().startswith(b"&")
    )


def _first_problem(node: Node, data: bytes) -> Node | None:
    """The first ERROR or MISSING node that isn't a known grammar gap,
    depth first."""
    if node.is_missing or node.type == "ERROR":
        return None if _tolerated(node, data) else node
    if not node.has_error:
        return None
    for child in node.children:
        found = _first_problem(child, data)
        if found is not None:
            return found
    return None


def _parse_problem(grammar: str, source: str, line_offset: int = 0) -> str | None:
    lang = _language(grammar)
    if lang is None:
        return None
    data = source.encode("utf-8")
    tree = Parser(lang).parse(data)
    if not tree.root_node.has_error:
        return None
    bad = _first_problem(tree.root_node, data)
    if bad is None:
        return None
    line = bad.start_point[0] + 1 + line_offset
    if bad.is_missing:
        return (
            f"line {line}: missing `{bad.type}` (the file looks cut off or unbalanced)"
        )
    snippet = (
        data[bad.start_byte : bad.end_byte]
        .decode("utf-8", "replace")
        .strip()
        .splitlines()
    )
    near = f" near `{snippet[0][:60]}`" if snippet and snippet[0] else ""
    return f"line {line}: syntax error{near}"


def _resolve(language: str | None, path: str | None) -> tuple[str | None, bool]:
    """(grammar key, is a Vue/Svelte single-file component)."""
    if path:
        lower = path.lower()
        if lower.endswith(_SFC_SUFFIXES):
            return "javascript", True
        spec = knowledge.language_for_path(path)
        if spec is None:
            return None, False
        if lower.endswith(".tsx"):
            return "tsx", False
        return spec.key, False
    spec = knowledge.language(language)
    return (spec.key if spec else None), False


def checkable(language: str | None = None, path: str | None = None) -> bool:
    """Whether check() can parse this kind of file (a grammar is installed)."""
    grammar, _sfc = _resolve(language, path)
    return grammar is not None and available(grammar)


def check(
    content: str, language: str | None = None, path: str | None = None
) -> str | None:
    """A readable syntax problem, or None (parses, or can't be checked)."""
    grammar, sfc = _resolve(language, path)
    if grammar is None:
        return None
    label = (
        knowledge.language(grammar).label if knowledge.language(grammar) else grammar
    )
    stripped = content.lstrip()
    if sfc or (
        grammar in ("javascript", "typescript")
        and stripped.startswith(("<template", "<script"))
    ):
        for match in _SCRIPT_BLOCK.finditer(content):
            attrs, body = match.group(1), match.group(2)
            block_grammar = (
                "typescript"
                if re.search(r"lang\s*=\s*[\"']ts", attrs)
                else "javascript"
            )
            offset = content.count("\n", 0, match.start(2))
            problem = _parse_problem(block_grammar, body, offset)
            if problem:
                return f"invalid {label} in <script>: {problem}"
        return None
    if grammar == "typescript" and not path:
        # Without a path, a .tsx file can't be told apart — accept either grammar.
        problem = _parse_problem("typescript", content)
        if problem and _parse_problem("tsx", content) is None:
            return None
    else:
        problem = _parse_problem(grammar, content)
    return f"invalid {label} syntax — {problem}" if problem else None
