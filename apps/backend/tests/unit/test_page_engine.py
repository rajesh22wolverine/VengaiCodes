"""Coverage for the deterministic page engine — no AI, no network, so
every one of these asserts an exact expected output rather than a
"looks reasonable" shape. The byte-preservation guarantee (untouched
parts of the page come out identical) is what most of the edit tests
are really pinning down.
"""

import pytest

from app.services.page_engine import (
    Page,
    PageEditError,
    analyze_page,
    edit_page,
    parse_style_attribute,
    remove_css_declaration,
    render_style_attribute,
    set_css_declaration,
)

SAMPLE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Pricing</title>
</head>
<body>
  <header class="site-header">
    <h1 id="headline">Simple pricing</h1>
    <!-- nav goes here -->
    <nav><a href="/docs">Docs</a><a href="/blog">Blog</a></nav>
  </header>
  <main>
    <section class="plan featured" data-plan="pro">
      <h2>Pro</h2>
      <p class="price" style="color: #333; font-size: 14px">$29/month</p>
      <img src="/pro.png" alt="Pro plan">
      <button class="cta" type="submit">Buy now</button>
    </section>
    <form action="/subscribe" method="post">
      <input name="email" type="email">
      <input name="plan" type="hidden" value="pro">
    </form>
  </main>
</body>
</html>
"""


# ─── parsing / indexing ───
def test_indexes_every_element_with_exact_source_spans():
    page = Page(SAMPLE)
    for element in page.elements:
        start, end = element.start_span
        raw = page.source[start:end]
        assert raw.startswith(f"<{element.tag}"), (
            f"{element.tag} start span points at {raw[:40]!r}"
        )
        assert raw.endswith(">")


def test_outer_span_covers_the_whole_element_including_its_end_tag():
    page = Page(SAMPLE)
    header = page.select("header")[0]
    outer = page.source[header.outer_span[0] : header.outer_span[1]]
    assert outer.startswith('<header class="site-header">')
    assert outer.endswith("</header>")
    assert "Docs" in outer


def test_void_elements_do_not_swallow_their_siblings():
    page = Page(SAMPLE)
    img = page.select("img")[0]
    button = page.select("button")[0]
    # <img> has no end tag, so the button must be its sibling, not its child.
    assert button.parent == img.parent
    assert img.inner_span is None


def test_parent_child_relationships_are_tracked():
    page = Page(SAMPLE)
    section = page.select("section")[0]
    h2 = page.select("section h2")[0]
    assert h2.parent == section.index
    assert h2.index in section.children


def test_handles_unclosed_tags_without_derailing_the_index():
    page = Page("<ul><li>one<li>two</ul><p>after</p>")
    assert [e.tag for e in page.elements] == ["ul", "li", "li", "p"]
    assert page.text_of(page.select("p")[0]) == "after"


# ─── selectors ───
@pytest.mark.parametrize(
    "selector,expected_tags",
    [
        ("h1", ["h1"]),
        ("#headline", ["h1"]),
        (".price", ["p"]),
        ("section.featured", ["section"]),
        ("[data-plan]", ["section"]),
        ('[data-plan="pro"]', ["section"]),
        ("header nav a", ["a", "a"]),
        ("h1, h2", ["h1", "h2"]),
    ],
)
def test_selector_subset_matches_expected_elements(selector, expected_tags):
    page = Page(SAMPLE)
    assert [e.tag for e in page.select(selector)] == expected_tags


def test_descendant_selector_does_not_match_outside_its_ancestor():
    page = Page("<div class='a'><span>x</span></div><span>y</span>")
    matches = page.select(".a span")
    assert len(matches) == 1
    assert page.text_of(matches[0]) == "x"


def test_ambiguous_selector_is_an_error_rather_than_a_guess():
    page = Page(SAMPLE)
    with pytest.raises(PageEditError, match="matches 2 elements"):
        page.resolve_target({"selector": "a"})
    assert len(page.resolve_target({"selector": "a", "all": True})) == 2


def test_selector_matching_nothing_is_an_error():
    page = Page(SAMPLE)
    with pytest.raises(PageEditError, match="Nothing on the page matches"):
        page.resolve_target({"selector": ".does-not-exist"})


# ─── analysis ───
def test_analysis_inventories_the_whole_page():
    result = analyze_page(SAMPLE, "body { margin: 0; color: #111 }")
    summary = result["summary"]

    assert summary["element_count"] == len(result["elements"])
    assert summary["by_tag"]["a"] == 2
    assert "headline" in summary["ids"]
    assert "featured" in summary["classes"]
    assert [h["level"] for h in summary["headings"]] == [1, 2]
    assert summary["images"] == [
        {"index": summary["images"][0]["index"], "src": "/pro.png", "alt": "Pro plan"}
    ]
    assert [link["href"] for link in summary["links"]] == ["/docs", "/blog"]
    assert summary["forms"][0]["action"] == "/subscribe"
    assert {f["name"] for f in summary["forms"][0]["fields"]} == {"email", "plan"}
    assert summary["comment_count"] == 1
    assert summary["has_doctype"] is True
    assert "#333" in summary["colors_used"]
    assert "#111" in summary["colors_used"]
    assert summary["stylesheet"]["rule_count"] == 1


def test_analysis_reports_inline_styles_per_element():
    result = analyze_page(SAMPLE)
    price = next(e for e in result["elements"] if "price" in e["classes"])
    assert price["inline_styles"] == {"color": "#333", "font-size": "14px"}
    assert price["text"] == "$29/month"


def test_analysis_flags_real_structural_issues():
    html = '<html><body><img src="a.png"><a href="">x</a><h3>Deep</h3><p id="dup"></p><p id="dup"></p></body></html>'
    issues = {issue["type"] for issue in analyze_page(html)["issues"]}
    assert "image_missing_alt" in issues
    assert "missing_title" in issues
    assert "missing_lang" in issues
    assert "missing_viewport" in issues
    assert "heading_does_not_start_at_h1" in issues
    assert "duplicate_id" in issues


def test_clean_page_reports_no_issues():
    html = (
        '<html lang="en"><head><title>T</title>'
        '<meta name="viewport" content="width=device-width"></head>'
        '<body><h1>A</h1><h2>B</h2><img src="x.png" alt="x"><a href="/y">Y</a></body></html>'
    )
    assert analyze_page(html)["issues"] == []


# ─── editing: byte preservation ───
def test_set_text_changes_only_that_element():
    result = edit_page(
        SAMPLE,
        "",
        [
            {
                "op": "set_text",
                "target": {"selector": "#headline"},
                "value": "New pricing",
            }
        ],
    )
    assert '<h1 id="headline">New pricing</h1>' in result["html"]
    # Everything else is untouched, byte for byte.
    assert result["html"].replace("New pricing", "Simple pricing") == SAMPLE
    assert result["html_changed"] is True


def test_set_text_escapes_html_so_content_cannot_inject_markup():
    result = edit_page(
        "<p>x</p>",
        "",
        [
            {
                "op": "set_text",
                "target": {"selector": "p"},
                "value": "<script>alert(1)</script>",
            }
        ],
    )
    assert result["html"] == "<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>"


def test_set_html_inserts_real_markup():
    result = edit_page(
        "<div></div>",
        "",
        [{"op": "set_html", "target": {"selector": "div"}, "value": "<b>hi</b>"}],
    )
    assert result["html"] == "<div><b>hi</b></div>"


def test_set_style_merges_with_existing_inline_styles():
    result = edit_page(
        SAMPLE,
        "",
        [
            {
                "op": "set_style",
                "target": {"selector": ".price"},
                "property": "color",
                "value": "red",
            }
        ],
    )
    assert 'style="color: red; font-size: 14px"' in result["html"]


def test_set_style_accepts_multiple_properties_at_once():
    result = edit_page(
        '<p style="color: red">x</p>',
        "",
        [
            {
                "op": "set_style",
                "target": {"selector": "p"},
                "styles": {"font-size": "20px", "color": "blue"},
            }
        ],
    )
    assert result["html"] == '<p style="color: blue; font-size: 20px">x</p>'


def test_remove_style_drops_the_attribute_when_it_empties():
    result = edit_page(
        '<p style="color: red">x</p>',
        "",
        [{"op": "remove_style", "target": {"selector": "p"}, "property": "color"}],
    )
    assert result["html"] == "<p>x</p>"


def test_class_add_and_remove_preserve_other_attributes():
    result = edit_page(
        SAMPLE,
        "",
        [
            {
                "op": "add_class",
                "target": {"selector": "section.plan"},
                "value": "highlighted",
            },
            {"op": "remove_class", "target": {"selector": "button"}, "value": "cta"},
        ],
    )
    assert 'class="plan featured highlighted" data-plan="pro"' in result["html"]
    assert '<button type="submit">Buy now</button>' in result["html"]


def test_set_and_remove_attribute():
    result = edit_page(
        SAMPLE,
        "",
        [
            {
                "op": "set_attribute",
                "target": {"selector": "img"},
                "name": "alt",
                "value": "Pro tier",
            },
            {
                "op": "remove_attribute",
                "target": {"selector": "form"},
                "name": "method",
            },
        ],
    )
    assert '<img src="/pro.png" alt="Pro tier">' in result["html"]
    assert '<form action="/subscribe">' in result["html"]


def test_attribute_values_are_escaped():
    result = edit_page(
        "<img src='a.png'>",
        "",
        [
            {
                "op": "set_attribute",
                "target": {"selector": "img"},
                "name": "alt",
                "value": 'say "hi" & <b>',
            }
        ],
    )
    # `>` is intentionally left as-is: inside a quoted attribute value only
    # `&` and the quote character actually need escaping, and `<` is escaped
    # as extra defence. Escaping `>` too would just be noise in the output.
    assert result["html"] == '<img src="a.png" alt="say &quot;hi&quot; &amp; &lt;b>">'


def test_remove_element_removes_the_whole_subtree():
    result = edit_page(
        SAMPLE, "", [{"op": "remove_element", "target": {"selector": "nav"}}]
    )
    assert "<nav>" not in result["html"]
    assert "/docs" not in result["html"]
    assert '<h1 id="headline">Simple pricing</h1>' in result["html"]


def test_insert_html_at_each_position():
    base = "<div><p>mid</p></div>"
    assert (
        edit_page(
            base,
            "",
            [
                {
                    "op": "insert_html",
                    "target": {"selector": "p"},
                    "position": "before",
                    "value": "<i>b</i>",
                }
            ],
        )["html"]
        == "<div><i>b</i><p>mid</p></div>"
    )
    assert (
        edit_page(
            base,
            "",
            [
                {
                    "op": "insert_html",
                    "target": {"selector": "p"},
                    "position": "after",
                    "value": "<i>a</i>",
                }
            ],
        )["html"]
        == "<div><p>mid</p><i>a</i></div>"
    )
    assert (
        edit_page(
            base,
            "",
            [
                {
                    "op": "insert_html",
                    "target": {"selector": "div"},
                    "position": "prepend",
                    "value": "<i>p</i>",
                }
            ],
        )["html"]
        == "<div><i>p</i><p>mid</p></div>"
    )
    assert (
        edit_page(
            base,
            "",
            [
                {
                    "op": "insert_html",
                    "target": {"selector": "div"},
                    "position": "append",
                    "value": "<i>q</i>",
                }
            ],
        )["html"]
        == "<div><p>mid</p><i>q</i></div>"
    )


def test_replace_element_swaps_the_whole_element():
    result = edit_page(
        "<div><span class='x'>old</span></div>",
        "",
        [
            {
                "op": "replace_element",
                "target": {"selector": ".x"},
                "value": "<b>new</b>",
            }
        ],
    )
    assert result["html"] == "<div><b>new</b></div>"


def test_multiple_edits_in_one_call_all_land():
    result = edit_page(
        SAMPLE,
        "",
        [
            {"op": "set_text", "target": {"selector": "#headline"}, "value": "Plans"},
            {"op": "set_text", "target": {"selector": "h2"}, "value": "Professional"},
            {
                "op": "set_attribute",
                "target": {"selector": "button"},
                "name": "type",
                "value": "button",
            },
        ],
    )
    assert ">Plans<" in result["html"]
    assert ">Professional<" in result["html"]
    assert '<button class="cta" type="button">' in result["html"]
    assert len(result["applied"]) == 3


def test_edit_targeting_all_matches_changes_each_one():
    result = edit_page(
        SAMPLE,
        "",
        [
            {
                "op": "add_class",
                "target": {"selector": "a", "all": True},
                "value": "link",
            }
        ],
    )
    assert result["html"].count('class="link"') == 2
    assert result["applied"][0]["targets"] == [
        t for t in result["applied"][0]["targets"]
    ]
    assert len(result["applied"][0]["targets"]) == 2


def test_overlapping_edits_are_rejected_not_silently_clobbered():
    with pytest.raises(PageEditError, match="same part of the page"):
        edit_page(
            "<div><p>x</p></div>",
            "",
            [
                {"op": "remove_element", "target": {"selector": "div"}},
                {"op": "set_text", "target": {"selector": "p"}, "value": "y"},
            ],
        )


def test_targeting_by_index_is_exact():
    page = Page(SAMPLE)
    h2_index = page.select("h2")[0].index
    result = edit_page(
        SAMPLE, "", [{"op": "set_text", "target": {"index": h2_index}, "value": "Team"}]
    )
    assert "<h2>Team</h2>" in result["html"]


def test_unknown_op_lists_the_supported_ones():
    with pytest.raises(PageEditError, match="Unknown op"):
        edit_page("<p>x</p>", "", [{"op": "make_it_pop", "target": {"selector": "p"}}])


def test_setting_text_on_a_void_element_is_a_clear_error():
    with pytest.raises(PageEditError, match="no inner content"):
        edit_page(
            "<img src='a.png'>",
            "",
            [{"op": "set_text", "target": {"selector": "img"}, "value": "x"}],
        )


# ─── stylesheet editing ───
def test_set_css_declaration_updates_an_existing_rule():
    css, created = set_css_declaration(
        ".btn {\n  color: red;\n  padding: 4px;\n}\n", ".btn", "color", "blue"
    )
    assert created is False
    assert "color: blue" in css
    assert "padding: 4px" in css
    assert css.count("color:") == 1


def test_set_css_declaration_creates_a_missing_rule():
    css, created = set_css_declaration(
        "body { margin: 0; }\n", ".new", "display", "flex"
    )
    assert created is True
    assert ".new {" in css
    assert "display: flex;" in css
    assert "body { margin: 0; }" in css


def test_set_css_skips_at_rule_blocks_rather_than_editing_the_wrong_one():
    css = "@media (max-width: 600px) {\n  .btn { color: red; }\n}\n.btn { color: green; }\n"
    updated, created = set_css_declaration(css, ".btn", "color", "blue")
    assert created is False
    # The .btn inside @media is a different rule and must survive untouched;
    # only the top-level .btn rule changes.
    assert "@media (max-width: 600px) {\n  .btn { color: red; }\n}" in updated
    assert "color: blue" in updated
    assert "color: green" not in updated


def test_remove_css_declaration():
    css, found = remove_css_declaration(
        ".btn { color: red; padding: 4px; }", ".btn", "color"
    )
    assert found is True
    assert "color" not in css
    assert "padding: 4px" in css


def test_remove_css_declaration_reports_when_absent():
    css, found = remove_css_declaration(".btn { padding: 4px; }", ".btn", "color")
    assert found is False


def test_css_edit_ops_run_through_edit_page():
    result = edit_page(
        "<p class='x'>hi</p>",
        ".x { color: red; }",
        [
            {"op": "set_css", "selector": ".x", "property": "color", "value": "navy"},
        ],
    )
    assert "color: navy" in result["css"]
    assert result["css_changed"] is True
    assert result["html"] == "<p class='x'>hi</p>"  # html untouched, byte for byte
    assert result["html_changed"] is False


# ─── style attribute helpers ───
def test_style_attribute_round_trip():
    parsed = parse_style_attribute("color:red;font-size: 12px ;")
    assert parsed == {"color": "red", "font-size": "12px"}
    assert render_style_attribute(parsed) == "color: red; font-size: 12px"
