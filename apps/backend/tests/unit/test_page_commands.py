"""Coverage for the deterministic English->edit rule table. The refusal
paths matter as much as the happy paths: an instruction outside the rule
table must come back understood=False rather than mutating the page on a
guess, which is the whole reason this layer exists instead of an AI call.
"""

import pytest

from app.services.page_commands import SUPPORTED_PHRASINGS, parse_command, parse_commands
from app.services.page_engine import Page, edit_page

SAMPLE = """<html lang="en">
<head><title>T</title><meta name="viewport" content="width=device-width"></head>
<body>
  <header class="site-header">
    <h1 id="headline">Simple pricing</h1>
    <nav><a href="/docs">Docs</a><a href="/blog">Blog</a></nav>
  </header>
  <section class="plan">
    <h2>Pro</h2>
    <p class="price" style="font-size: 14px">$29/month</p>
    <img src="/pro.png" alt="Pro">
    <button class="cta">Buy now</button>
  </section>
  <footer>© 2026</footer>
</body>
</html>"""


def _page() -> Page:
    return Page(SAMPLE)


def _apply(command: str) -> str:
    """Parses a command and actually applies it, so these tests prove the
    produced ops really work against the engine, not just that they parse."""
    page = _page()
    result = parse_command(command, page)
    assert result.understood, result.error
    return edit_page(SAMPLE, "", result.edits)["html"]


# ─── text ───
def test_change_text_by_friendly_name():
    assert ">Plans and pricing<" in _apply('change the headline to "Plans and pricing"')


def test_change_text_by_selector():
    assert '<p class="price" style="font-size: 14px">$49/month</p>' in _apply('set the .price text to "$49/month"')


def test_change_text_of_phrasing():
    assert "<h2>Professional</h2>" in _apply('change the text of the h2 to "Professional"')


def test_rename_phrasing():
    assert ">Team<" in _apply('rename #headline to "Team"')


def test_value_containing_and_is_not_split_in_half():
    html = _apply('set the h2 text to "Tom and Jerry"')
    assert "<h2>Tom and Jerry</h2>" in html


def test_title_reads_as_the_visible_heading_not_the_head_title_tag():
    # "title" collides three ways: an HTML attribute, the <title> tag in
    # <head>, and what people actually mean (the visible headline). The
    # attribute rule can't resolve a target so it falls through, and the
    # friendly mapping wins over the literal <title> tag.
    html = _apply('change the title to "Plans"')
    assert '<h1 id="headline">Plans</h1>' in html
    assert "<title>T</title>" in html  # the real <title> tag is untouched


def test_the_literal_title_tag_is_still_reachable_via_a_css_selector():
    html = _apply('change the text of head title to "Pricing page"')
    assert "<title>Pricing page</title>" in html
    assert ">Simple pricing<" in html  # the h1 is untouched


def test_the_word_link_means_an_anchor_not_a_stylesheet_link_tag():
    page = Page('<html><head><link rel="stylesheet" href="/a.css"></head><body><a href="/x">X</a></body></html>')
    result = parse_command('change the link to "Y"', page)
    assert result.understood, result.error
    html = edit_page(page.source, "", result.edits)["html"]
    assert '<a href="/x">Y</a>' in html
    assert '<link rel="stylesheet" href="/a.css">' in html


def test_title_attribute_still_settable_when_the_target_is_explicit():
    html = _apply('set the button title to "Click to buy"')
    assert 'title="Click to buy"' in html


# ─── colour ───
def test_background_colour_named():
    assert 'style="background-color: blue"' in _apply("make the header background blue")


def test_background_colour_hex_with_of_phrasing():
    assert "background-color: #2563eb" in _apply("change the background color of the footer to #2563eb")


def test_text_colour_merges_with_existing_inline_style():
    assert 'style="font-size: 14px; color: red"' in _apply("make the .price color red")


def test_unknown_colour_is_refused_with_a_useful_message():
    result = parse_command("make the header background ultraviolet", _page())
    assert result.understood is False
    assert "isn't a colour I recognise" in result.error


# ─── size ───
def test_explicit_font_size():
    assert "font-size: 32px" in _apply("make the headline font size 32px")


def test_font_size_without_unit_defaults_to_px():
    assert "font-size: 20px" in _apply("set the h2 font size 20")


def test_bigger_steps_up_from_the_existing_inline_size():
    # .price is 14px inline -> 14 * 1.25 = 17.5px
    assert "font-size: 17.5px" in _apply("make the .price text bigger")


def test_smaller_steps_down_from_the_default_when_no_size_is_set():
    # h2 has no font-size -> default 16px / 1.25 = 12.8px
    assert "font-size: 12.8px" in _apply("make the h2 smaller")


# ─── visibility / removal ───
def test_hide_sets_display_none():
    assert '<footer style="display: none">' in _apply("hide the footer")


def test_show_removes_the_display_style():
    page = Page('<div id="x" style="display: none; color: red">hi</div>')
    result = parse_command("show #x", page)
    assert result.understood
    html = edit_page(page.source, "", result.edits)["html"]
    assert html == '<div id="x" style="color: red">hi</div>'


def test_remove_deletes_the_whole_element():
    html = _apply("remove the nav")
    assert "<nav>" not in html
    assert "/docs" not in html
    assert "Simple pricing" in html


# ─── layout / emphasis ───
def test_center_sets_text_align():
    assert "text-align: center" in _apply("center the headline")


def test_align_right():
    assert "text-align: right" in _apply("align the footer to the right")


def test_bold_and_italic():
    assert "font-weight: bold" in _apply("make the h2 bold")
    assert "font-style: italic" in _apply("make the h2 italic")


def test_padding():
    assert "padding: 24px" in _apply("add 24px padding to the section")


# ─── classes & attributes ───
def test_add_class():
    assert 'class="plan featured"' in _apply("add class featured to the section")


def test_remove_class():
    assert "<button>Buy now</button>" in _apply("remove class cta from the button")


def test_set_attribute_href():
    assert 'href="/pricing"' in _apply('set the first link href to "/pricing"')


def test_set_attribute_alt_with_of_phrasing():
    assert 'alt="Product photo"' in _apply('set the alt of the image to "Product photo"')


# ─── targeting ───
def test_ordinal_picks_the_right_one_of_several():
    html = _apply('change the second link to "Writing"')
    assert ">Docs<" in html
    assert ">Writing<" in html


def test_last_ordinal():
    html = _apply('change the last link to "Archive"')
    assert ">Docs<" in html
    assert ">Archive<" in html


def test_target_by_visible_text():
    html = _apply('change the button that says "Buy now" to "Subscribe"')
    assert ">Subscribe<" in html


def test_ambiguous_target_is_refused_with_the_matching_indexes():
    result = parse_command('change the link to "X"', _page())
    assert result.understood is False
    assert "matches 2 elements" in result.error
    assert "the first link" in result.error


def test_missing_target_is_refused_with_guidance():
    result = parse_command("hide the carousel", _page())
    assert result.understood is False
    assert "Couldn't find" in result.error


def test_text_target_that_matches_nothing_is_refused():
    result = parse_command('change the button that says "Checkout" to "X"', _page())
    assert result.understood is False
    assert "has the text" in result.error


# ─── refusal behaviour (the point of this layer) ───
def test_unknown_instruction_is_refused_rather_than_guessed():
    result = parse_command("make it look more premium and modern", _page())
    assert result.understood is False
    assert result.edits == []
    assert result.suggestions == SUPPORTED_PHRASINGS


def test_empty_instruction_is_refused():
    result = parse_command("   ", _page())
    assert result.understood is False
    assert result.edits == []


def test_refused_command_produces_no_edits_at_all():
    page = _page()
    for bad in ["redesign the page", "make it pop", "improve the layout", "fix the spacing vibes"]:
        result = parse_command(bad, page)
        assert result.understood is False
        assert result.edits == []


# ─── multiple commands ───
def test_multiple_commands_split_on_newlines_and_semicolons():
    page = _page()
    results = parse_commands('change the headline to "Plans"\nhide the footer; center the h2', page)
    assert len(results) == 3
    assert all(r.understood for r in results)

    edits = [edit for r in results for edit in r.edits]
    html = edit_page(SAMPLE, "", edits)["html"]
    assert ">Plans<" in html
    assert 'style="display: none"' in html
    assert "text-align: center" in html


def test_one_bad_command_does_not_invalidate_the_good_ones():
    results = parse_commands('hide the footer\nmake it beautiful', _page())
    assert [r.understood for r in results] == [True, False]
    assert results[1].edits == []
