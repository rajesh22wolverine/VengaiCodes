# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Deterministic Page Commands
#  services/page_commands.py — Turns a plain-English change request
#  into exact page_engine edit ops using an explicit rule table. NO AI:
#  every phrase this understands is listed below in a regex, and
#  anything outside that list comes back as "not understood" with the
#  supported phrasings, rather than being guessed at.
#
#  That refusal is the point. An AI would always produce *something*
#  for an unclear instruction; this returns understood=False and lets
#  the user rephrase or send a structured op instead, so a page is
#  never mutated on a guess about what was meant.
#
#  Targets are resolved against the real parsed page, so every edit
#  returned carries a concrete element index that is already known to
#  exist — never a selector that might match nothing later.
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from app.services.page_engine import Element, Page

# Words a person uses for an element vs the tags they mean.
FRIENDLY_TAGS: dict[str, list[str]] = {
    "heading": ["h1", "h2", "h3", "h4", "h5", "h6"],
    "headline": ["h1"],
    "title": ["h1"],
    "subheading": ["h2"],
    "paragraph": ["p"],
    "text": ["p"],
    "button": ["button"],
    "link": ["a"],
    "image": ["img"],
    "picture": ["img"],
    "logo": ["img"],
    "header": ["header"],
    "footer": ["footer"],
    "nav": ["nav"],
    "navbar": ["nav"],
    "menu": ["nav"],
    "form": ["form"],
    "input": ["input"],
    "field": ["input"],
    "list": ["ul", "ol"],
    "table": ["table"],
    "section": ["section"],
    "sidebar": ["aside"],
    "container": ["div"],
    "box": ["div"],
}

NAMED_COLORS = {
    "black", "white", "red", "green", "blue", "yellow", "orange", "purple",
    "pink", "grey", "gray", "brown", "cyan", "magenta", "navy", "teal",
    "olive", "maroon", "silver", "gold", "beige", "transparent",
}

_ORDINALS = {
    "first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2,
    "fourth": 3, "4th": 3, "fifth": 4, "5th": 4, "last": -1,
}

_SIZE_STEP = 1.25
_DEFAULT_FONT_SIZE_PX = 16.0


@dataclass
class CommandResult:
    understood: bool
    edits: list[dict] = field(default_factory=list)
    explanation: str = ""
    error: str = ""
    suggestions: list[str] = field(default_factory=list)


class _TargetError(Exception):
    pass


SUPPORTED_PHRASINGS = [
    'change the heading text to "New title"',
    'set the .price text to "$49/month"',
    "make the header background blue",
    "change the button color to #ffffff",
    "make the heading font size 32px",
    "make the button text bigger",
    "hide the footer",
    "remove the nav",
    "center the heading",
    "make the heading bold",
    "add class featured to the section",
    "remove class cta from the button",
    'set the link href to "/pricing"',
    'set the image alt to "Product photo"',
    "add 24px padding to the section",
]


# ───────────────────────────────────────────────
#  Target resolution
# ───────────────────────────────────────────────
def _clean_target_phrase(phrase: str) -> tuple[str, Optional[int]]:
    """Strips leading articles and pulls out an ordinal ('the second
    button' -> ('button', 1))."""
    text = phrase.strip().strip(".").strip()
    text = re.sub(r"^(the|a|an)\s+", "", text, flags=re.I).strip()

    ordinal = None
    match = re.match(r"^(\w+)\s+(.*)$", text)
    if match and match.group(1).lower() in _ORDINALS:
        ordinal = _ORDINALS[match.group(1).lower()]
        text = match.group(2).strip()
    return text, ordinal


def resolve_targets(phrase: str, page: Page) -> list[Element]:
    """Maps an English phrase, a CSS selector, or `that says "x"` onto
    real elements. Raises _TargetError with a specific reason when it
    can't — never falls back to a nearest guess."""
    text, ordinal = _clean_target_phrase(phrase)
    if not text:
        raise _TargetError("No element named in that request.")

    # `button that says "Buy now"` / `link with text "Docs"`
    text_match = re.match(r'^(?P<what>.+?)\s+(?:that says|with text|labelled|labeled|saying)\s+["\']?(?P<label>[^"\']+)["\']?$', text, re.I)
    label = None
    if text_match:
        text = text_match.group("what").strip()
        label = text_match.group("label").strip().lower()

    candidates: list[Element] = []

    # A friendly word wins over a same-spelled tag, because the tag is
    # almost never what someone means: "the link" means an <a>, not the
    # <link rel=stylesheet> sitting in <head> on virtually every page, and
    # "the title" means the visible headline, not the <title> in <head>.
    # The literal tag stays reachable through a real CSS selector with a
    # combinator ("head title"), which skips this mapping entirely.
    tags = FRIENDLY_TAGS.get(text.lower())
    if tags:
        candidates = [e for e in page.elements if e.tag in tags]

    if not candidates and (text.startswith((".", "#", "[")) or re.fullmatch(r"[a-zA-Z][\w-]*([.#\[].*)?", text or "") or " " in text):
        try:
            candidates = page.select(text)
        except Exception:
            candidates = []

    if not candidates:
        raise _TargetError(
            f"Couldn't find {phrase.strip()!r} on the page. "
            f"Use a CSS selector (#id, .class, tag) or one of: {', '.join(sorted(FRIENDLY_TAGS))}."
        )

    if label is not None:
        candidates = [e for e in candidates if label in page.text_of(e).lower()]
        if not candidates:
            raise _TargetError(f"No {text} on the page has the text {label!r}.")

    if ordinal is not None:
        try:
            return [candidates[ordinal]]
        except IndexError:
            raise _TargetError(f"There aren't that many {text} elements on the page (found {len(candidates)}).")

    return candidates


def _single_target(phrase: str, page: Page) -> Element:
    matches = resolve_targets(phrase, page)
    if len(matches) > 1:
        raise _TargetError(
            f"{phrase.strip()!r} matches {len(matches)} elements (indexes {[m.index for m in matches][:8]}). "
            f"Say which one (e.g. 'the first {_clean_target_phrase(phrase)[0]}') or use a more specific selector."
        )
    return matches[0]


def _color_value(raw: str) -> str:
    value = raw.strip().strip("\"'").lower()
    if value in NAMED_COLORS:
        return value
    if re.fullmatch(r"#[0-9a-f]{3,8}", value) or re.fullmatch(r"(rgb|rgba|hsl|hsla)\([^)]*\)", value):
        return value
    raise _TargetError(f"{raw.strip()!r} isn't a colour I recognise. Use a hex value like #2563eb or one of: {', '.join(sorted(NAMED_COLORS))}.")


def _current_font_size_px(element: Element, page: Page) -> float:
    inline = element.styles.get("font-size")
    if inline:
        match = re.match(r"^([\d.]+)(px|rem|em|%)?$", inline.strip())
        if match:
            number = float(match.group(1))
            unit = match.group(2) or "px"
            if unit == "px":
                return number
            if unit in ("rem", "em"):
                return number * _DEFAULT_FONT_SIZE_PX
            if unit == "%":
                return _DEFAULT_FONT_SIZE_PX * number / 100
    return _DEFAULT_FONT_SIZE_PX


# ───────────────────────────────────────────────
#  Rule handlers
# ───────────────────────────────────────────────
def _h_set_text(match: re.Match, page: Page) -> tuple[list[dict], str]:
    element = _single_target(match.group("target"), page)
    value = match.group("value").strip().strip("\"'")
    return (
        [{"op": "set_text", "target": {"index": element.index}, "value": value}],
        f"Set the text of <{element.tag}> (element {element.index}) to {value!r}.",
    )


def _h_background(match: re.Match, page: Page) -> tuple[list[dict], str]:
    element = _single_target(match.group("target"), page)
    color = _color_value(match.group("value"))
    return (
        [{"op": "set_style", "target": {"index": element.index}, "property": "background-color", "value": color}],
        f"Set background-color of <{element.tag}> (element {element.index}) to {color}.",
    )


def _h_text_color(match: re.Match, page: Page) -> tuple[list[dict], str]:
    element = _single_target(match.group("target"), page)
    color = _color_value(match.group("value"))
    return (
        [{"op": "set_style", "target": {"index": element.index}, "property": "color", "value": color}],
        f"Set color of <{element.tag}> (element {element.index}) to {color}.",
    )


def _h_font_size(match: re.Match, page: Page) -> tuple[list[dict], str]:
    element = _single_target(match.group("target"), page)
    size = match.group("value").strip()
    if re.fullmatch(r"[\d.]+", size):
        size = f"{size}px"
    if not re.fullmatch(r"[\d.]+(px|rem|em|%|pt)", size):
        raise _TargetError(f"{size!r} isn't a size I recognise. Use something like 18px, 1.5rem or 120%.")
    return (
        [{"op": "set_style", "target": {"index": element.index}, "property": "font-size", "value": size}],
        f"Set font-size of <{element.tag}> (element {element.index}) to {size}.",
    )


def _h_size_step(match: re.Match, page: Page) -> tuple[list[dict], str]:
    element = _single_target(match.group("target"), page)
    direction = match.group("direction").lower()
    current = _current_font_size_px(element, page)
    new_size = current * _SIZE_STEP if direction in ("bigger", "larger") else current / _SIZE_STEP
    rounded = f"{round(new_size, 1):g}px"
    return (
        [{"op": "set_style", "target": {"index": element.index}, "property": "font-size", "value": rounded}],
        f"Set font-size of <{element.tag}> (element {element.index}) to {rounded} (was {current:g}px).",
    )


def _h_hide(match: re.Match, page: Page) -> tuple[list[dict], str]:
    element = _single_target(match.group("target"), page)
    return (
        [{"op": "set_style", "target": {"index": element.index}, "property": "display", "value": "none"}],
        f"Hid <{element.tag}> (element {element.index}) with display: none.",
    )


def _h_show(match: re.Match, page: Page) -> tuple[list[dict], str]:
    element = _single_target(match.group("target"), page)
    return (
        [{"op": "remove_style", "target": {"index": element.index}, "property": "display"}],
        f"Removed the display style from <{element.tag}> (element {element.index}).",
    )


def _h_remove(match: re.Match, page: Page) -> tuple[list[dict], str]:
    element = _single_target(match.group("target"), page)
    return (
        [{"op": "remove_element", "target": {"index": element.index}}],
        f"Removed <{element.tag}> (element {element.index}) and everything inside it.",
    )


def _h_center(match: re.Match, page: Page) -> tuple[list[dict], str]:
    element = _single_target(match.group("target"), page)
    return (
        [{"op": "set_style", "target": {"index": element.index}, "property": "text-align", "value": "center"}],
        f"Centred <{element.tag}> (element {element.index}).",
    )


def _h_align(match: re.Match, page: Page) -> tuple[list[dict], str]:
    element = _single_target(match.group("target"), page)
    return (
        [{"op": "set_style", "target": {"index": element.index}, "property": "text-align", "value": match.group("value").lower()}],
        f"Aligned <{element.tag}> (element {element.index}) {match.group('value').lower()}.",
    )


def _h_bold(match: re.Match, page: Page) -> tuple[list[dict], str]:
    element = _single_target(match.group("target"), page)
    style = "italic" if "italic" in match.group(0).lower() else "bold"
    prop, value = ("font-style", "italic") if style == "italic" else ("font-weight", "bold")
    return (
        [{"op": "set_style", "target": {"index": element.index}, "property": prop, "value": value}],
        f"Made <{element.tag}> (element {element.index}) {style}.",
    )


def _h_add_class(match: re.Match, page: Page) -> tuple[list[dict], str]:
    element = _single_target(match.group("target"), page)
    name = match.group("value").strip().lstrip(".")
    return (
        [{"op": "add_class", "target": {"index": element.index}, "value": name}],
        f"Added class {name!r} to <{element.tag}> (element {element.index}).",
    )


def _h_remove_class(match: re.Match, page: Page) -> tuple[list[dict], str]:
    element = _single_target(match.group("target"), page)
    name = match.group("value").strip().lstrip(".")
    return (
        [{"op": "remove_class", "target": {"index": element.index}, "value": name}],
        f"Removed class {name!r} from <{element.tag}> (element {element.index}).",
    )


def _h_set_attribute(match: re.Match, page: Page) -> tuple[list[dict], str]:
    element = _single_target(match.group("target"), page)
    name = match.group("name").strip().lower()
    value = match.group("value").strip().strip("\"'")
    return (
        [{"op": "set_attribute", "target": {"index": element.index}, "name": name, "value": value}],
        f"Set {name}={value!r} on <{element.tag}> (element {element.index}).",
    )


def _h_padding(match: re.Match, page: Page) -> tuple[list[dict], str]:
    element = _single_target(match.group("target"), page)
    prop = "margin" if "margin" in match.group(0).lower() else "padding"
    amount = match.group("value").strip()
    if re.fullmatch(r"[\d.]+", amount):
        amount = f"{amount}px"
    return (
        [{"op": "set_style", "target": {"index": element.index}, "property": prop, "value": amount}],
        f"Set {prop} of <{element.tag}> (element {element.index}) to {amount}.",
    )


# ───────────────────────────────────────────────
#  Rule table — the complete list of understood phrasings
# ───────────────────────────────────────────────
Rule = tuple[re.Pattern, Callable[[re.Match, Page], tuple[list[dict], str]]]

# ORDER MATTERS: most specific first. A generic pattern placed above a
# specific one swallows it — e.g. the bare "remove <target>" rule will
# happily read "remove class cta from the button" as an element named
# "class cta from the button" if it gets first look.
RULES: list[Rule] = [
    # Classes — before the generic remove/add rules below.
    (re.compile(r"^add\s+(?:the\s+)?class\s+(?P<value>[\w.-]+)\s+to\s+(?P<target>.+)$", re.I), _h_add_class),
    (re.compile(r"^remove\s+(?:the\s+)?class\s+(?P<value>[\w.-]+)\s+from\s+(?P<target>.+)$", re.I), _h_remove_class),

    # Attributes — a closed keyword list, so more specific than free text.
    (re.compile(r"^(?:set|change|update)\s+the\s+(?P<name>href|src|alt|title|placeholder|value|type|name|target|id)\s+(?:text\s+)?of\s+(?P<target>.+?)\s+to\s+(?P<value>.+)$", re.I), _h_set_attribute),
    (re.compile(r"^(?:set|change|update)\s+(?P<target>.+?)\s+(?P<name>href|src|alt|title|placeholder|value|type|name|target|id)\s+(?:to\s+)?(?P<value>.+)$", re.I), _h_set_attribute),

    # Text — "the text of X" before the generic "X to ..." form.
    (re.compile(r"^(?:change|set|update|edit)\s+the\s+text\s+of\s+(?P<target>.+?)\s+to\s+[\"'](?P<value>.*)[\"']$", re.I), _h_set_text),
    (re.compile(r"^(?:rename|retitle)\s+(?P<target>.+?)\s+to\s+[\"'](?P<value>.*)[\"']$", re.I), _h_set_text),
    (re.compile(r"^(?:change|set|update|edit)\s+(?P<target>.+?)\s+(?:text\s+)?to\s+[\"'](?P<value>.*)[\"']$", re.I), _h_set_text),

    # Colour
    (re.compile(r"^(?:change|set)\s+the\s+background(?:\s+colou?r)?\s+of\s+(?P<target>.+?)\s+to\s+(?P<value>\S+)$", re.I), _h_background),
    (re.compile(r"^(?:make|set|change)\s+(?P<target>.+?)\s+background(?:\s+colou?r)?\s+(?:to\s+)?(?P<value>\S+)$", re.I), _h_background),
    (re.compile(r"^(?:change|set)\s+the\s+colou?r\s+of\s+(?P<target>.+?)\s+to\s+(?P<value>\S+)$", re.I), _h_text_color),
    (re.compile(r"^(?:make|set|change)\s+(?P<target>.+?)\s+(?:text\s+)?colou?r\s+(?:to\s+)?(?P<value>\S+)$", re.I), _h_text_color),

    # Size
    (re.compile(r"^(?:make|set|change)\s+(?P<target>.+?)\s+font(?:\s*-?\s*size)?\s+(?:to\s+)?(?P<value>[\d.]+\s*(?:px|rem|em|%|pt)?)$", re.I), _h_font_size),
    (re.compile(r"^(?:make|set|change)\s+(?P<target>.+?)\s+(?:text\s+)?(?P<direction>bigger|larger|smaller)$", re.I), _h_size_step),

    # Layout / emphasis
    (re.compile(r"^(?:add|set)\s+(?P<value>[\d.]+\s*(?:px|rem|em|%)?)\s+(?:of\s+)?(?:padding|margin)\s+(?:to|on)\s+(?P<target>.+)$", re.I), _h_padding),
    (re.compile(r"^(?:cent(?:er|re))\s+(?P<target>.+)$", re.I), _h_center),
    (re.compile(r"^(?:align|justify)\s+(?P<target>.+?)\s+(?:to\s+the\s+)?(?P<value>left|right|center|centre|justify)$", re.I), _h_align),
    (re.compile(r"^(?:make|set)\s+(?P<target>.+?)\s+(?:bold|italic)$", re.I), _h_bold),

    # Visibility / removal — generic, so last.
    (re.compile(r"^hide\s+(?P<target>.+)$", re.I), _h_hide),
    (re.compile(r"^(?:show|unhide|reveal)\s+(?P<target>.+)$", re.I), _h_show),
    (re.compile(r"^(?:remove|delete|drop)\s+(?P<target>.+)$", re.I), _h_remove),
]


def parse_command(command: str, page: Page) -> CommandResult:
    """Parses ONE instruction. Returns understood=False (with the
    supported phrasings) instead of guessing when nothing matches.

    A rule that matches the *phrasing* but whose target doesn't resolve
    against this page falls through to the remaining rules rather than
    failing outright — several keywords are legitimately ambiguous
    ("title" is both an element people name and an HTML attribute), and
    the right reading is whichever one actually resolves. If nothing
    resolves, the first specific error is what gets reported, since it's
    more useful than a generic "not understood"."""
    text = (command or "").strip().rstrip(".")
    if not text:
        return CommandResult(understood=False, error="Empty instruction.", suggestions=SUPPORTED_PHRASINGS)

    first_error: Optional[str] = None
    for pattern, handler in RULES:
        match = pattern.match(text)
        if not match:
            continue
        try:
            edits, explanation = handler(match, page)
        except _TargetError as error:
            if first_error is None:
                first_error = str(error)
            continue
        return CommandResult(understood=True, edits=edits, explanation=explanation)

    if first_error:
        return CommandResult(understood=False, error=first_error)
    return CommandResult(
        understood=False,
        error=f"I don't understand {text!r} well enough to change the page safely.",
        suggestions=SUPPORTED_PHRASINGS,
    )


def parse_commands(commands: str, page: Page) -> list[CommandResult]:
    """Splits on newlines and semicolons only — deliberately NOT on
    'and', which shows up inside values ('set the title to "Tom and
    Jerry"') and would silently split a request in half."""
    parts = [p.strip() for p in re.split(r"[\n;]+", commands or "") if p.strip()]
    return [parse_command(part, page) for part in parts]
