"""Pure-logic coverage for the Reverse App feature's real (non-AI) extraction:
tech fingerprinting, form-based data model inference, GitHub repo URL
parsing, and the real regex route/model extraction used against fetched
repo source. None of this hits the network — that's exercised by the
SSRF guard and the endpoint's stubbed-AI flow separately.
"""

import pytest
from fastapi import HTTPException

from app.api.v1.reverse_engineer import (
    GITHUB_REPO_RE,
    MODEL_PATTERNS,
    ROUTE_PATTERNS,
    _detect_stack_from_manifest,
    _infer_data_model,
    _validate_public_url,
    build_reverse_engineering_directive,
    fingerprint_tech_stack,
)


# ─── SSRF guard ───
def test_validate_public_url_blocks_private_and_internal_targets():
    for bad in [
        "http://localhost/",
        "http://127.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",  # AWS metadata
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "ftp://example.com/",
    ]:
        with pytest.raises(HTTPException):
            _validate_public_url(bad)


def test_validate_public_url_allows_a_real_public_host():
    _validate_public_url("https://example.com/")  # must not raise


# ─── Tech fingerprinting ───
def test_fingerprint_detects_nextjs_from_html_markers():
    html = '<html><body><script>window.__NEXT_DATA__ = {}</script></body></html>'
    found = fingerprint_tech_stack(html, {}, [])
    names = {t["name"] for t in found}
    assert "Next.js" in names


def test_fingerprint_detects_wordpress_from_paths():
    html = '<link href="/wp-content/themes/mytheme/style.css">'
    found = fingerprint_tech_stack(html, {}, [])
    assert any(t["name"] == "WordPress" for t in found)


def test_fingerprint_detects_django_from_cookie_name():
    found = fingerprint_tech_stack("", {}, ["csrftoken", "sessionid"])
    assert any(t["name"] == "Django" for t in found)


def test_fingerprint_detects_backend_from_headers():
    found = fingerprint_tech_stack("", {"server": "nginx/1.24.0", "x-powered-by": "Express"}, [])
    names = {t["name"] for t in found}
    assert "nginx" in names
    assert "Express" in names


def test_fingerprint_returns_nothing_for_a_blank_page():
    assert fingerprint_tech_stack("<html></html>", {}, []) == []


# ─── Data model inference from real <form> fields ───
def test_infer_data_model_labels_password_forms_as_auth():
    forms = [{"action": "/login", "method": "POST", "fields": [{"name": "email"}, {"name": "password"}]}]
    entities = _infer_data_model(forms)
    assert len(entities) == 1
    assert entities[0]["kind"] == "auth"
    assert entities[0]["name"] == "user_auth"


def test_infer_data_model_skips_bare_search_boxes():
    forms = [{"action": "/search", "method": "GET", "fields": [{"name": "q"}]}]
    assert _infer_data_model(forms) == []


def test_infer_data_model_names_entity_from_action_path():
    forms = [
        {
            "action": "/products/new",
            "method": "POST",
            "fields": [{"name": "title"}, {"name": "price"}, {"name": "description"}],
        }
    ]
    entities = _infer_data_model(forms)
    assert entities[0]["name"] == "new"
    assert entities[0]["fields"] == ["title", "price", "description"]


def test_infer_data_model_ignores_forms_with_no_named_fields():
    forms = [{"action": "/x", "method": "POST", "fields": [{"name": ""}]}]
    assert _infer_data_model(forms) == []


# ─── GitHub repo URL parsing ───
@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://github.com/facebook/react", ("facebook", "react")),
        ("https://github.com/facebook/react.git", ("facebook", "react")),
        ("https://github.com/facebook/react/", ("facebook", "react")),
        ("http://github.com/owner-name/repo.name", ("owner-name", "repo.name")),
    ],
)
def test_github_repo_regex_matches_valid_urls(url, expected):
    m = GITHUB_REPO_RE.match(url)
    assert m is not None
    assert (m.group(1), m.group(2)) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://gitlab.com/owner/repo",
        "https://github.com/owner",
        "https://github.com/owner/repo/tree/main",
        "not a url",
    ],
)
def test_github_repo_regex_rejects_non_repo_urls(url):
    assert GITHUB_REPO_RE.match(url) is None


# ─── Manifest-based stack detection ───
def test_detect_stack_from_package_json_dependencies():
    content = '{"dependencies": {"react": "^18.0.0", "express": "^4.0.0"}}'
    found = _detect_stack_from_manifest("package.json", content)
    names = {f["name"] for f in found}
    assert names == {"React", "Express"}


def test_detect_stack_from_requirements_txt():
    found = _detect_stack_from_manifest("requirements.txt", "fastapi==0.104.0\nuvicorn==0.24.0\n")
    assert any(f["name"] == "FastAPI" for f in found)


def test_detect_stack_from_malformed_package_json_returns_empty():
    assert _detect_stack_from_manifest("package.json", "{not json") == []


# ─── Real regex route/model extraction against real source snippets ───
def test_route_patterns_extract_fastapi_routes():
    source = '@app.get("/users/{id}")\ndef get_user(id: int):\n    ...\n\n@router.post("/users")\ndef create_user():\n    ...\n'
    matches = []
    for framework, pattern in ROUTE_PATTERNS:
        for m in pattern.finditer(source):
            matches.append((framework, m.group(1).upper(), m.group(2)))
    assert ("FastAPI/Flask", "GET", "/users/{id}") in matches
    assert ("FastAPI/Flask", "POST", "/users") in matches


def test_route_patterns_extract_express_routes():
    source = "app.get('/api/products', handler);\nrouter.delete('/api/products/:id', handler);"
    matches = []
    for framework, pattern in ROUTE_PATTERNS:
        for m in pattern.finditer(source):
            matches.append((framework, m.group(1).upper(), m.group(2)))
    assert ("Express/Node", "GET", "/api/products") in matches
    assert ("Express/Node", "DELETE", "/api/products/:id") in matches


def test_model_patterns_extract_sqlalchemy_model():
    source = "class User(Base):\n    __tablename__ = 'users'\n    id = Column(Integer, primary_key=True)\n"
    matches = []
    for orm, pattern in MODEL_PATTERNS:
        for m in pattern.finditer(source):
            matches.append((orm, m.group(1)))
    assert ("SQLAlchemy", "User") in matches


def test_model_patterns_extract_django_model():
    source = "class Product(models.Model):\n    name = models.CharField(max_length=100)\n"
    matches = []
    for orm, pattern in MODEL_PATTERNS:
        for m in pattern.finditer(source):
            matches.append((orm, m.group(1)))
    assert ("Django ORM", "Product") in matches


def test_model_patterns_extract_prisma_model():
    source = "model Order {\n  id Int @id\n  total Float\n}\n"
    matches = []
    for orm, pattern in MODEL_PATTERNS:
        for m in pattern.finditer(source):
            matches.append((orm, m.group(1)))
    assert ("Prisma", "Order") in matches


# ─── Grounding directive fed into requirements.py / architecture.py ───
def test_reverse_engineering_directive_empty_when_no_data():
    assert build_reverse_engineering_directive(None) == ""
    assert build_reverse_engineering_directive({}) == ""


def test_reverse_engineering_directive_surfaces_real_facts():
    reverse_data = {
        "tech_stack": [{"name": "Django", "category": "backend_framework", "evidence": "cookie"}],
        "data_model": [{"name": "product", "kind": "record"}],
        "api_endpoints": [{"method": "GET", "path": "/api/products"}],
    }
    directive = build_reverse_engineering_directive(reverse_data)
    assert "Django" in directive
    assert "product" in directive
    assert "GET /api/products" in directive
