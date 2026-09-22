# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Deterministic Page Engine
#  services/page_engine.py — Reads a real HTML page, inventories
#  everything in it, and applies precise edits to it. NO AI anywhere
#  in this module, by design: it never imports app.ai, never makes a
#  network call, and given the same page + same edits always produces
#  byte-identical output. That means edits are instant, free, and
#  can't hallucinate a change the user didn't ask for.
#
#  Fidelity: edits are applied as SPLICES into the original source
#  string, not by re-serializing a parsed tree. Only the byte ranges
#  actually being changed are rewritten — every other byte of the
#  page (formatting, comments, attribute quoting, whitespace) comes
#  out exactly as it went in. A full parse/re-serialize round trip
#  would quietly normalize the whole document on every small edit.
#
#  Built on the stdlib html.parser (no bs4/lxml dependency): it gives
#  getpos() + get_starttag_text(), which is all that's needed to map
#  every element back to its exact source byte range.
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations

import html as html_module
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Optional

# Elements that never have a closing tag — they must not be pushed onto
# the open-element stack or every later element nests under them.
VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}

_TAG_STRIP_RE = re.compile(r"<[^>]*>")
_WHITESPACE_RE = re.compile(r"\s+")
_COLOR_RE = re.compile(r"#(?:[0-9a-fA-F]{3,8})\b|\brgba?\([^)]*\)|\bhsla?\([^)]*\)")


class PageEditError(Exception):
    """Raised for an edit that cannot be applied deterministically —
    an unknown op, an unresolvable target, or overlapping edits. Never
    guessed around: a request this engine can't satisfy exactly is an
    error, not a best-effort approximation."""


# ───────────────────────────────────────────────
#  Element model
# ───────────────────────────────────────────────
@dataclass
class Element:
    index: int
    tag: str
    attrs: list[tuple[str, Optional[str]]]
    depth: int
    parent: Optional[int]
    start_span: tuple[int, int]
    end_span: Optional[tuple[int, int]] = None
    children: list[int] = field(default_factory=list)
    self_closing: bool = False

    @property
    def outer_span(self) -> tuple[int, int]:
        if self.end_span:
            return (self.start_span[0], self.end_span[1])
        return self.start_span

    @property
    def inner_span(self) -> Optional[tuple[int, int]]:
        """Byte range between the start and end tags. None for void or
        self-closing elements, which have no inner content to address."""
        if self.end_span is None:
            return None
        return (self.start_span[1], self.end_span[0])

    def attr(self, name: str) -> Optional[str]:
        for key, value in self.attrs:
            if key.lower() == name.lower():
                return value
        return None

    def has_attr(self, name: str) -> bool:
        return any(key.lower() == name.lower() for key, _ in self.attrs)

    @property
    def id(self) -> Optional[str]:
        return self.attr("id")

    @property
    def classes(self) -> list[str]:
        return (self.attr("class") or "").split()

    @property
    def styles(self) -> dict[str, str]:
        return parse_style_attribute(self.attr("style") or "")


# ───────────────────────────────────────────────
#  Small deterministic helpers
# ───────────────────────────────────────────────
def escape_attribute(value: str) -> str:
    return value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


def escape_text(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def parse_style_attribute(style: str) -> dict[str, str]:
    """Splits `color: red; font-size: 12px` into an ordered dict. Later
    duplicates win, matching how a browser resolves an inline style."""
    out: dict[str, str] = {}
    for declaration in style.split(";"):
        if ":" not in declaration:
            continue
        prop, _, value = declaration.partition(":")
        prop = prop.strip().lower()
        value = value.strip()
        if prop and value:
            out[prop] = value
    return out


def render_style_attribute(styles: dict[str, str]) -> str:
    return "; ".join(f"{prop}: {value}" for prop, value in styles.items())


def render_start_tag(tag: str, attrs: list[tuple[str, Optional[str]]], self_closing: bool) -> str:
    parts = [tag]
    for name, value in attrs:
        parts.append(name if value is None else f'{name}="{escape_attribute(value)}"')
    return "<" + " ".join(parts) + (" />" if self_closing else ">")


def visible_text(source: str, span: Optional[tuple[int, int]]) -> str:
    """Strips tags from a source range and collapses whitespace. Used for
    the analysis inventory, never for editing (edits always address exact
    byte ranges, so this lossy view can't corrupt a page)."""
    if span is None:
        return ""
    raw = source[span[0]:span[1]]
    raw = re.sub(r"<(script|style)\b.*?</\1>", " ", raw, flags=re.S | re.I)
    stripped = _TAG_STRIP_RE.sub(" ", raw)
    return _WHITESPACE_RE.sub(" ", html_module.unescape(stripped)).strip()


# ───────────────────────────────────────────────
#  Indexer — maps every element to its exact byte range
# ───────────────────────────────────────────────
class _Indexer(HTMLParser):
    def __init__(self, source: str) -> None:
        # convert_charrefs would rewrite entity text handed to handle_data;
        # every value this class keeps is sliced from `source` directly, so
        # it is only disabled to keep offsets and raw text honest.
        super().__init__(convert_charrefs=False)
        self.source = source
        self.line_starts = self._build_line_starts(source)
        self.elements: list[Element] = []
        self.comments: list[tuple[int, str]] = []
        self.doctype: Optional[str] = None
        self._stack: list[int] = []

    @staticmethod
    def _build_line_starts(source: str) -> list[int]:
        starts = [0]
        for i, char in enumerate(source):
            if char == "\n":
                starts.append(i + 1)
        return starts

    def _offset(self) -> int:
        line, col = self.getpos()
        if line - 1 >= len(self.line_starts):
            return len(self.source)
        return min(self.line_starts[line - 1] + col, len(self.source))

    def _open(self, tag: str, attrs, self_closing: bool) -> Element:
        start = self._offset()
        raw = self.get_starttag_text() or ""
        element = Element(
            index=len(self.elements),
            tag=tag.lower(),
            attrs=[(name, value) for name, value in attrs],
            depth=len(self._stack),
            parent=self._stack[-1] if self._stack else None,
            start_span=(start, start + len(raw)),
            self_closing=self_closing,
        )
        if element.parent is not None:
            self.elements[element.parent].children.append(element.index)
        self.elements.append(element)
        return element

    def handle_starttag(self, tag, attrs):
        element = self._open(tag, attrs, self_closing=False)
        if element.tag not in VOID_ELEMENTS:
            self._stack.append(element.index)

    def handle_startendtag(self, tag, attrs):
        self._open(tag, attrs, self_closing=True)

    def handle_endtag(self, tag):
        tag = tag.lower()
        start = self._offset()
        closing = self.source.find(">", start)
        end = (closing + 1) if closing != -1 else start + len(f"</{tag}>")

        # Walk back to the matching open element. Unclosed inner tags (legal
        # in HTML, e.g. <li> without </li>) are closed implicitly at the
        # same point rather than derailing the rest of the index.
        for depth in range(len(self._stack) - 1, -1, -1):
            if self.elements[self._stack[depth]].tag == tag:
                for orphan in self._stack[depth + 1:]:
                    if self.elements[orphan].end_span is None:
                        self.elements[orphan].end_span = (start, start)
                self.elements[self._stack[depth]].end_span = (start, end)
                del self._stack[depth:]
                return

    def handle_comment(self, data):
        self.comments.append((self._offset(), data))

    def handle_decl(self, decl):
        if decl.lower().startswith("doctype"):
            self.doctype = decl


# ───────────────────────────────────────────────
#  Selector matching (deterministic subset)
# ───────────────────────────────────────────────
_SIMPLE_SELECTOR_RE = re.compile(
    r"^(?P<tag>[a-zA-Z][\w-]*|\*)?"
    r"(?P<idpart>#[\w-]+)?"
    r"(?P<classes>(?:\.[\w-]+)*)"
    r"(?P<attrs>(?:\[[^\]]+\])*)$"
)
_ATTR_RE = re.compile(r"\[\s*([\w-]+)\s*(?:([~|^$*]?=)\s*\"?([^\"\]]*)\"?)?\s*\]")


@dataclass
class _SimpleSelector:
    tag: Optional[str]
    element_id: Optional[str]
    classes: list[str]
    attrs: list[tuple[str, Optional[str], Optional[str]]]

    def matches(self, element: Element) -> bool:
        if self.tag and self.tag != "*" and element.tag != self.tag:
            return False
        if self.element_id and element.id != self.element_id:
            return False
        if self.classes:
            have = set(element.classes)
            if not set(self.classes).issubset(have):
                return False
        for name, operator, value in self.attrs:
            actual = element.attr(name)
            if actual is None and not element.has_attr(name):
                return False
            if operator is None:
                continue
            actual = actual or ""
            if operator == "=" and actual != value:
                return False
            if operator == "^=" and not actual.startswith(value or ""):
                return False
            if operator == "$=" and not actual.endswith(value or ""):
                return False
            if operator == "*=" and (value or "") not in actual:
                return False
            if operator == "~=" and (value or "") not in actual.split():
                return False
        return True


def _parse_simple_selector(part: str) -> _SimpleSelector:
    attrs: list[tuple[str, Optional[str], Optional[str]]] = []
    for name, operator, value in _ATTR_RE.findall(part):
        attrs.append((name, operator or None, value if operator else None))
    stripped = _ATTR_RE.sub("", part)

    match = _SIMPLE_SELECTOR_RE.match(stripped + "")
    if not match:
        raise PageEditError(f"Unsupported selector part: {part!r}")
    classes = [c for c in match.group("classes").split(".") if c]
    idpart = match.group("idpart")
    return _SimpleSelector(
        tag=(match.group("tag") or "").lower() or None,
        element_id=idpart[1:] if idpart else None,
        classes=classes,
        attrs=attrs,
    )


# ───────────────────────────────────────────────
#  Page — parse, analyze, edit
# ───────────────────────────────────────────────
@dataclass
class Splice:
    start: int
    end: int
    replacement: str
    description: str


class Page:
    def __init__(self, html: str, css: str = "") -> None:
        self.source = html or ""
        self.css = css or ""
        indexer = _Indexer(self.source)
        indexer.feed(self.source)
        indexer.close()
        self.elements: list[Element] = indexer.elements
        self.comments = indexer.comments
        self.doctype = indexer.doctype

    # ── lookup ──
    def element(self, index: int) -> Element:
        if index < 0 or index >= len(self.elements):
            raise PageEditError(f"No element with index {index} (page has {len(self.elements)}).")
        return self.elements[index]

    def select(self, selector: str) -> list[Element]:
        """Supports `tag`, `#id`, `.class`, `[attr]`, `[attr=value]`,
        combinations of those, and descendant chains separated by spaces.
        Deliberately a documented subset — an unsupported selector raises
        rather than silently matching the wrong thing."""
        selector = (selector or "").strip()
        if not selector:
            raise PageEditError("Empty selector.")

        groups = [g.strip() for g in selector.split(",") if g.strip()]
        if len(groups) > 1:
            seen: dict[int, Element] = {}
            for group in groups:
                for element in self.select(group):
                    seen[element.index] = element
            return [seen[i] for i in sorted(seen)]

        parts = [p for p in selector.split() if p]
        parsed = [_parse_simple_selector(p) for p in parts]

        matches = [e for e in self.elements if parsed[-1].matches(e)]
        for ancestor_selector in reversed(parsed[:-1]):
            matches = [e for e in matches if self._has_ancestor(e, ancestor_selector)]
        return matches

    def _has_ancestor(self, element: Element, selector: _SimpleSelector) -> bool:
        parent = element.parent
        while parent is not None:
            candidate = self.elements[parent]
            if selector.matches(candidate):
                return True
            parent = candidate.parent
        return False

    def resolve_target(self, target: dict) -> list[Element]:
        """A target is either {"index": N} (exact, no ambiguity — what the
        UI should send) or {"selector": "..."} with optional "all": true.
        A selector matching several elements without "all" is an error, so
        an ambiguous request is never resolved by guessing."""
        if not isinstance(target, dict):
            raise PageEditError("Edit target must be an object with 'index' or 'selector'.")

        if "index" in target and target["index"] is not None:
            return [self.element(int(target["index"]))]

        selector = target.get("selector")
        if not selector:
            raise PageEditError("Edit target needs either 'index' or 'selector'.")

        matches = self.select(selector)
        if not matches:
            raise PageEditError(f"Nothing on the page matches {selector!r}.")
        if len(matches) > 1 and not target.get("all"):
            raise PageEditError(
                f"{selector!r} matches {len(matches)} elements "
                f"(indexes {[m.index for m in matches][:8]}). "
                f"Pass \"all\": true to change them all, or target one by index."
            )
        return matches

    def text_of(self, element: Element) -> str:
        return visible_text(self.source, element.inner_span)

    # ── analysis ──
    def analyze(self) -> dict[str, Any]:
        """Full deterministic inventory of the page: every element, what
        it is, where it is, plus roll-ups (images/links/forms/headings/
        colors/fonts) and structural issues worth flagging."""
        elements_out = []
        by_tag: dict[str, int] = {}
        images, links, forms, headings, buttons, inputs = [], [], [], [], [], []
        inline_style_props: set[str] = set()
        colors: set[str] = set()
        fonts: set[str] = set()
        scripts, external = [], []

        for element in self.elements:
            by_tag[element.tag] = by_tag.get(element.tag, 0) + 1
            text = self.text_of(element)
            styles = element.styles
            inline_style_props.update(styles.keys())
            for value in styles.values():
                colors.update(_COLOR_RE.findall(value))
            if "font-family" in styles:
                fonts.add(styles["font-family"])

            elements_out.append(
                {
                    "index": element.index,
                    "tag": element.tag,
                    "id": element.id,
                    "classes": element.classes,
                    "attributes": {name: value for name, value in element.attrs},
                    "inline_styles": styles,
                    "text": text[:200],
                    "depth": element.depth,
                    "parent": element.parent,
                    "children": list(element.children),
                    "editable": element.inner_span is not None,
                    "outer_span": list(element.outer_span),
                }
            )

            if element.tag == "img":
                images.append({"index": element.index, "src": element.attr("src"), "alt": element.attr("alt")})
            elif element.tag == "a":
                links.append({"index": element.index, "href": element.attr("href"), "text": text[:120]})
            elif element.tag == "form":
                forms.append(
                    {
                        "index": element.index,
                        "action": element.attr("action"),
                        "method": (element.attr("method") or "get").lower(),
                        "fields": [
                            {"name": self.elements[c].attr("name"), "type": self.elements[c].attr("type") or self.elements[c].tag}
                            for c in self._descendants(element)
                            if self.elements[c].tag in ("input", "select", "textarea")
                        ],
                    }
                )
            elif element.tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                headings.append({"index": element.index, "level": int(element.tag[1]), "text": text[:120]})
            elif element.tag == "button" or (element.tag == "input" and (element.attr("type") or "").lower() in ("button", "submit")):
                buttons.append({"index": element.index, "text": text[:80] or element.attr("value")})
            elif element.tag in ("input", "select", "textarea"):
                inputs.append({"index": element.index, "name": element.attr("name"), "type": element.attr("type") or element.tag})

            if element.tag == "script":
                scripts.append({"index": element.index, "src": element.attr("src"), "inline": element.attr("src") is None})
            src = element.attr("src") or element.attr("href")
            if src and src.startswith(("http://", "https://", "//")):
                external.append({"index": element.index, "tag": element.tag, "url": src})

        stylesheet = analyze_css(self.css)
        colors.update(stylesheet.pop("_colors", []))
        fonts.update(stylesheet.pop("_fonts", []))

        return {
            "elements": elements_out,
            "summary": {
                "element_count": len(self.elements),
                "by_tag": dict(sorted(by_tag.items(), key=lambda kv: -kv[1])),
                "ids": [e.id for e in self.elements if e.id],
                "classes": sorted({c for e in self.elements for c in e.classes}),
                "headings": headings,
                "images": images,
                "links": links,
                "forms": forms,
                "buttons": buttons,
                "inputs": inputs,
                "scripts": scripts,
                "external_resources": external,
                "inline_style_properties": sorted(inline_style_props),
                "colors_used": sorted(colors),
                "fonts_used": sorted(fonts),
                "stylesheet": stylesheet,
                "comment_count": len(self.comments),
                "has_doctype": self.doctype is not None,
                "word_count": len(visible_text(self.source, (0, len(self.source))).split()),
            },
            "issues": self._issues(images, links, headings, forms),
        }

    def _descendants(self, element: Element) -> list[int]:
        out: list[int] = []
        stack = list(element.children)
        while stack:
            index = stack.pop()
            out.append(index)
            stack.extend(self.elements[index].children)
        return sorted(out)

    def _issues(self, images, links, headings, forms) -> list[dict]:
        """Structural/accessibility checks — the 'check every aspect' pass.
        Every one of these is a fact about the page, not an opinion from a
        model: each names the exact element index it came from."""
        issues: list[dict] = []

        seen_ids: dict[str, int] = {}
        for element in self.elements:
            if element.id:
                if element.id in seen_ids:
                    issues.append({
                        "type": "duplicate_id",
                        "index": element.index,
                        "message": f"id=\"{element.id}\" is already used by element {seen_ids[element.id]} — selectors targeting it are ambiguous.",
                    })
                else:
                    seen_ids[element.id] = element.index

        for image in images:
            if not image.get("alt"):
                issues.append({"type": "image_missing_alt", "index": image["index"], "message": "Image has no alt text."})
        for link in links:
            if not link.get("href"):
                issues.append({"type": "link_missing_href", "index": link["index"], "message": "Link has no href."})
            elif not link.get("text"):
                issues.append({"type": "link_missing_text", "index": link["index"], "message": "Link has no visible text."})

        html_elements = [e for e in self.elements if e.tag == "html"]
        if html_elements and not html_elements[0].attr("lang"):
            issues.append({"type": "missing_lang", "index": html_elements[0].index, "message": "<html> has no lang attribute."})
        if not any(e.tag == "title" for e in self.elements):
            issues.append({"type": "missing_title", "index": None, "message": "Page has no <title>."})
        if not any(e.tag == "meta" and (e.attr("name") or "").lower() == "viewport" for e in self.elements):
            issues.append({"type": "missing_viewport", "index": None, "message": "No viewport meta tag — the page won't scale on mobile."})

        levels = [h["level"] for h in headings]
        if levels and levels[0] != 1:
            issues.append({"type": "heading_does_not_start_at_h1", "index": headings[0]["index"], "message": f"First heading is h{levels[0]}, not h1."})
        for previous, current in zip(levels, levels[1:]):
            if current > previous + 1:
                issues.append({"type": "heading_level_skipped", "index": None, "message": f"Heading jumps from h{previous} to h{current}."})
                break

        for form in forms:
            for field_info in form["fields"]:
                if not field_info.get("name"):
                    issues.append({"type": "form_field_without_name", "index": form["index"], "message": "A form field has no name — it won't submit a value."})
                    break

        return issues

    # ── editing ──
    def apply(self, edits: list[dict]) -> tuple[str, str, list[dict]]:
        """Applies every edit against THIS page's source and returns
        (new_html, new_css, per-edit results). All element splices are
        computed against the original source and applied back-to-front,
        so offsets stay valid; overlapping edits are rejected rather than
        silently clobbering each other."""
        if not isinstance(edits, list) or not edits:
            raise PageEditError("No edits given.")

        splices: list[Splice] = []
        results: list[dict] = []
        css = self.css

        for position, edit in enumerate(edits):
            if not isinstance(edit, dict):
                raise PageEditError(f"Edit #{position + 1} is not an object.")
            op = (edit.get("op") or "").strip().lower()
            if not op:
                raise PageEditError(f"Edit #{position + 1} has no 'op'.")

            if op in _CSS_OPS:
                css, described = _CSS_OPS[op](css, edit)
                results.append({"edit": position, "op": op, "targets": [], "description": described})
                continue

            handler = _ELEMENT_OPS.get(op)
            if handler is None:
                known = ", ".join(sorted(list(_ELEMENT_OPS) + list(_CSS_OPS)))
                raise PageEditError(f"Unknown op {op!r}. Supported ops: {known}.")

            targets = self.resolve_target(edit.get("target") or {})
            described = []
            for element in targets:
                splice = handler(self, element, edit)
                splices.append(splice)
                described.append(splice.description)
            results.append({"edit": position, "op": op, "targets": [t.index for t in targets], "description": "; ".join(described)})

        new_html = self._splice(splices)
        return new_html, css, results

    def _splice(self, splices: list[Splice]) -> str:
        ordered = sorted(splices, key=lambda s: (s.start, s.end))
        for previous, current in zip(ordered, ordered[1:]):
            if current.start < previous.end:
                raise PageEditError(
                    "Two edits touch the same part of the page "
                    f"({previous.description!r} and {current.description!r}). Apply them one at a time."
                )
        out = self.source
        for splice in reversed(ordered):
            out = out[:splice.start] + splice.replacement + out[splice.end:]
        return out


# ───────────────────────────────────────────────
#  Element operations
# ───────────────────────────────────────────────
def _require(edit: dict, key: str) -> Any:
    if key not in edit or edit[key] is None:
        raise PageEditError(f"Op {edit.get('op')!r} needs a {key!r} value.")
    return edit[key]


def _rewrite_start_tag(element: Element, attrs: list[tuple[str, Optional[str]]], description: str) -> Splice:
    return Splice(
        start=element.start_span[0],
        end=element.start_span[1],
        replacement=render_start_tag(element.tag, attrs, element.self_closing),
        description=description,
    )


def _set_attr_list(element: Element, name: str, value: Optional[str]) -> list[tuple[str, Optional[str]]]:
    attrs = [(key, val) for key, val in element.attrs]
    for i, (key, _) in enumerate(attrs):
        if key.lower() == name.lower():
            attrs[i] = (key, value)
            return attrs
    attrs.append((name, value))
    return attrs


def _op_set_text(page: Page, element: Element, edit: dict) -> Splice:
    span = element.inner_span
    if span is None:
        raise PageEditError(f"<{element.tag}> (element {element.index}) has no inner content to set text on.")
    text = str(_require(edit, "value"))
    return Splice(span[0], span[1], escape_text(text), f"set text of <{element.tag}> #{element.index}")


def _op_set_html(page: Page, element: Element, edit: dict) -> Splice:
    span = element.inner_span
    if span is None:
        raise PageEditError(f"<{element.tag}> (element {element.index}) has no inner content to replace.")
    return Splice(span[0], span[1], str(_require(edit, "value")), f"set inner HTML of <{element.tag}> #{element.index}")


def _op_set_attribute(page: Page, element: Element, edit: dict) -> Splice:
    name = str(_require(edit, "name"))
    value = edit.get("value")
    attrs = _set_attr_list(element, name, None if value is None else str(value))
    return _rewrite_start_tag(element, attrs, f"set {name} on <{element.tag}> #{element.index}")


def _op_remove_attribute(page: Page, element: Element, edit: dict) -> Splice:
    name = str(_require(edit, "name")).lower()
    attrs = [(key, value) for key, value in element.attrs if key.lower() != name]
    return _rewrite_start_tag(element, attrs, f"remove {name} from <{element.tag}> #{element.index}")


def _op_add_class(page: Page, element: Element, edit: dict) -> Splice:
    wanted = str(_require(edit, "value")).split()
    classes = element.classes
    for name in wanted:
        if name not in classes:
            classes.append(name)
    attrs = _set_attr_list(element, "class", " ".join(classes))
    return _rewrite_start_tag(element, attrs, f"add class {' '.join(wanted)} to <{element.tag}> #{element.index}")


def _op_remove_class(page: Page, element: Element, edit: dict) -> Splice:
    unwanted = set(str(_require(edit, "value")).split())
    classes = [c for c in element.classes if c not in unwanted]
    attrs = _set_attr_list(element, "class", " ".join(classes)) if classes else [
        (key, value) for key, value in element.attrs if key.lower() != "class"
    ]
    return _rewrite_start_tag(element, attrs, f"remove class {' '.join(sorted(unwanted))} from <{element.tag}> #{element.index}")


def _op_set_style(page: Page, element: Element, edit: dict) -> Splice:
    styles = element.styles
    updates = edit.get("styles")
    if updates is None:
        updates = {str(_require(edit, "property")): str(_require(edit, "value"))}
    if not isinstance(updates, dict):
        raise PageEditError("set_style needs either property/value or a styles object.")
    for prop, value in updates.items():
        styles[str(prop).strip().lower()] = str(value).strip()
    attrs = _set_attr_list(element, "style", render_style_attribute(styles))
    changed = ", ".join(f"{k}: {v}" for k, v in updates.items())
    return _rewrite_start_tag(element, attrs, f"set style ({changed}) on <{element.tag}> #{element.index}")


def _op_remove_style(page: Page, element: Element, edit: dict) -> Splice:
    prop = str(_require(edit, "property")).strip().lower()
    styles = element.styles
    styles.pop(prop, None)
    attrs = (
        _set_attr_list(element, "style", render_style_attribute(styles))
        if styles
        else [(key, value) for key, value in element.attrs if key.lower() != "style"]
    )
    return _rewrite_start_tag(element, attrs, f"remove style {prop} from <{element.tag}> #{element.index}")


def _op_remove_element(page: Page, element: Element, edit: dict) -> Splice:
    start, end = element.outer_span
    return Splice(start, end, "", f"remove <{element.tag}> #{element.index}")


def _op_replace_element(page: Page, element: Element, edit: dict) -> Splice:
    start, end = element.outer_span
    return Splice(start, end, str(_require(edit, "value")), f"replace <{element.tag}> #{element.index}")


def _op_insert_html(page: Page, element: Element, edit: dict) -> Splice:
    html_value = str(_require(edit, "value"))
    position = (edit.get("position") or "after").lower()
    outer_start, outer_end = element.outer_span
    inner = element.inner_span

    if position == "before":
        return Splice(outer_start, outer_start, html_value, f"insert before <{element.tag}> #{element.index}")
    if position == "after":
        return Splice(outer_end, outer_end, html_value, f"insert after <{element.tag}> #{element.index}")
    if position == "prepend":
        if inner is None:
            raise PageEditError(f"<{element.tag}> (element {element.index}) has no inner content to prepend into.")
        return Splice(inner[0], inner[0], html_value, f"prepend into <{element.tag}> #{element.index}")
    if position == "append":
        if inner is None:
            raise PageEditError(f"<{element.tag}> (element {element.index}) has no inner content to append into.")
        return Splice(inner[1], inner[1], html_value, f"append into <{element.tag}> #{element.index}")
    raise PageEditError(f"Unknown insert position {position!r}. Use before, after, prepend, or append.")


_ELEMENT_OPS = {
    "set_text": _op_set_text,
    "set_html": _op_set_html,
    "set_attribute": _op_set_attribute,
    "remove_attribute": _op_remove_attribute,
    "add_class": _op_add_class,
    "remove_class": _op_remove_class,
    "set_style": _op_set_style,
    "remove_style": _op_remove_style,
    "remove_element": _op_remove_element,
    "replace_element": _op_replace_element,
    "insert_html": _op_insert_html,
}


# ───────────────────────────────────────────────
#  Stylesheet operations
# ───────────────────────────────────────────────
def _iter_top_level_rules(css: str):
    """Yields (selector, selector_span, block_span) for every top-level
    rule. At-rules (@media and friends) are skipped rather than guessed
    at — their nested blocks need their own pass, and silently editing
    the wrong one is worse than reporting the rule as absent."""
    i, length = 0, len(css)
    while i < length:
        brace = css.find("{", i)
        if brace == -1:
            return
        selector = css[i:brace]
        if selector.strip().startswith("@"):
            depth, j = 0, brace
            while j < length:
                if css[j] == "{":
                    depth += 1
                elif css[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            i = j + 1
            continue
        close = css.find("}", brace)
        if close == -1:
            return
        yield selector.strip(), (i, brace), (brace + 1, close)
        i = close + 1


def _normalize_selector(selector: str) -> str:
    return _WHITESPACE_RE.sub(" ", selector.replace(" ,", ",").replace(", ", ",")).strip().lower()


def set_css_declaration(css: str, selector: str, prop: str, value: str) -> tuple[str, bool]:
    """Sets one declaration inside a top-level rule, creating the rule if
    it doesn't exist. Returns (css, created_rule)."""
    prop = prop.strip().lower()
    value = value.strip()
    wanted = _normalize_selector(selector)

    for rule_selector, _selector_span, block_span in _iter_top_level_rules(css):
        if _normalize_selector(rule_selector) != wanted:
            continue
        block = css[block_span[0]:block_span[1]]
        declarations = parse_style_attribute(block)
        declarations[prop] = value
        indent = "\n  "
        rebuilt = indent + (";" + indent).join(f"{p}: {v}" for p, v in declarations.items()) + ";\n"
        return css[:block_span[0]] + rebuilt + css[block_span[1]:], False

    separator = "" if (not css or css.endswith("\n")) else "\n"
    return f"{css}{separator}{selector.strip()} {{\n  {prop}: {value};\n}}\n", True


def remove_css_declaration(css: str, selector: str, prop: str) -> tuple[str, bool]:
    """Removes one declaration from a top-level rule. Returns (css, found)."""
    prop = prop.strip().lower()
    wanted = _normalize_selector(selector)

    for rule_selector, _selector_span, block_span in _iter_top_level_rules(css):
        if _normalize_selector(rule_selector) != wanted:
            continue
        block = css[block_span[0]:block_span[1]]
        declarations = parse_style_attribute(block)
        if prop not in declarations:
            return css, False
        declarations.pop(prop)
        if not declarations:
            rebuilt = ""
        else:
            indent = "\n  "
            rebuilt = indent + (";" + indent).join(f"{p}: {v}" for p, v in declarations.items()) + ";\n"
        return css[:block_span[0]] + rebuilt + css[block_span[1]:], True
    return css, False


def _css_op_set(css: str, edit: dict) -> tuple[str, str]:
    selector = str(_require(edit, "selector"))
    updates = edit.get("styles")
    if updates is None:
        updates = {str(_require(edit, "property")): str(_require(edit, "value"))}
    for prop, value in updates.items():
        css, _created = set_css_declaration(css, selector, str(prop), str(value))
    changed = ", ".join(f"{k}: {v}" for k, v in updates.items())
    return css, f"set stylesheet rule {selector} {{ {changed} }}"


def _css_op_remove(css: str, edit: dict) -> tuple[str, str]:
    selector = str(_require(edit, "selector"))
    prop = str(_require(edit, "property"))
    css, found = remove_css_declaration(css, selector, prop)
    if not found:
        raise PageEditError(f"No {prop!r} declaration found in a top-level {selector!r} rule.")
    return css, f"remove {prop} from stylesheet rule {selector}"


_CSS_OPS = {
    "set_css": _css_op_set,
    "remove_css": _css_op_remove,
}


def analyze_css(css: str) -> dict[str, Any]:
    selectors, properties = [], set()
    colors, fonts = set(), set()
    for selector, _selector_span, block_span in _iter_top_level_rules(css or ""):
        selectors.append(selector)
        declarations = parse_style_attribute(css[block_span[0]:block_span[1]])
        properties.update(declarations.keys())
        for prop, value in declarations.items():
            colors.update(_COLOR_RE.findall(value))
            if prop == "font-family":
                fonts.add(value)
    return {
        "rule_count": len(selectors),
        "selectors": selectors,
        "properties_used": sorted(properties),
        "at_rule_count": len(re.findall(r"@[\w-]+", css or "")),
        "_colors": sorted(colors),
        "_fonts": sorted(fonts),
    }


# ───────────────────────────────────────────────
#  Public entry points
# ───────────────────────────────────────────────
def analyze_page(html: str, css: str = "") -> dict[str, Any]:
    return Page(html, css).analyze()


def edit_page(html: str, css: str, edits: list[dict]) -> dict[str, Any]:
    page = Page(html, css)
    new_html, new_css, results = page.apply(edits)
    return {
        "html": new_html,
        "css": new_css,
        "applied": results,
        "html_changed": new_html != page.source,
        "css_changed": new_css != page.css,
    }
