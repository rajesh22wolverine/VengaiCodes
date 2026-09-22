# ═══════════════════════════════════════════════════════════════
#  VengaiCode — "Reverse App" API Routes
#  api/v1/reverse_engineer.py — Turns an EXISTING app into real,
#  non-AI-invented technical facts, then a synthesized raw_idea string
#  in the same shape CreateTab's free-text box already produces so
#  nothing downstream (wizard, requirements, architecture, codegen)
#  needs to change to consume it.
#
#  Four source modes:
#    - url: crawls the real site (httpx, same-origin, depth/time/page
#      capped), fingerprints its actual tech stack from HTML/header/
#      cookie signatures (the same technique tools like Wappalyzer use —
#      real pattern matches against real bytes, not an AI guess), infers
#      a data model from real <form> field names, and downloads real
#      JS/CSS asset files as code_snippets.
#    - repo: points at a public GitHub repo. Walks its real file tree
#      via the GitHub API, detects the real tech stack from manifest
#      files (package.json/requirements.txt/etc.), and regex-extracts
#      real route declarations and real ORM model declarations from
#      fetched source files — genuine matched source, not fabricated.
#    - screenshots: reuses orchestrator.generate_vision() (the same
#      Groq vision call already used for the UI/UX phase's design-to-
#      code feature) once per image.
#    - description: passed straight through — nothing to extract.
#
#  All four modes still end with one AI synthesis call that turns the
#  gathered material into a first-person raw_idea paragraph for the
#  wizard, but ALSO return the raw structured facts (`reverse_engineering`)
#  so the frontend can echo them straight into POST /projects and ground
#  the Requirements/Architecture phases in real extracted facts instead
#  of re-guessing from prose (see build_reverse_engineering_directive,
#  imported by requirements.py and architecture.py).
#
#  SECURITY: source_type="url"/"repo" fetch user-supplied network
#  locations from this backend's own network — a real SSRF surface
#  (OWASP-relevant) if left unguarded. _validate_public_url() resolves
#  the hostname and rejects private/loopback/link-local/reserved/
#  multicast IP ranges before EVERY request (including every page
#  discovered while crawling, and every asset URL) — redirects are
#  never followed, and every response is size-capped before parsing.
#  Repo mode only ever talks to the fixed literal hosts api.github.com
#  and raw.githubusercontent.com, with owner/repo restricted to a
#  strict allowlist regex, so it carries no SSRF surface of its own.
# ═══════════════════════════════════════════════════════════════

import base64
import html.parser
import ipaddress
import json
import logging
import re
import socket
import time
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.orchestrator import AIError, generate_text, generate_vision
from app.api.v1.auth import get_current_active_user
from app.core.database import get_db
from app.models.user import User

logger = logging.getLogger("vengaicode.reverse_engineer")
router = APIRouter()

ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}
MAX_SCREENSHOTS = 5
MAX_SCREENSHOT_BYTES = 8 * 1024 * 1024
MAX_URL_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_URL_TEXT_CHARS = 4000
MAX_MATERIAL_CHARS_IN_PROMPT = 6000

MAX_CRAWL_PAGES = 8
MAX_CRAWL_DEPTH = 2
CRAWL_TIME_BUDGET_SECONDS = 25.0
MAX_ASSET_FILES = 4
MAX_ASSET_BYTES = 20_000
ASSET_SNIPPET_CHARS = 3000

MAX_REPO_FILES_FETCHED = 14
MAX_REPO_FILE_BYTES = 15_000
MAX_REPO_SNIPPETS = 10
REPO_SNIPPET_CHARS = 4000


def parse_ai_json(text: str) -> dict:
    """Extract and parse JSON from AI response, handling markdown code fences.
    Kept local rather than imported from requirements.py to avoid a circular
    import (requirements.py imports build_reverse_engineering_directive from
    this module) — requirements.py/architecture.py each keep their own copy
    of this same trivial helper for the same reason."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    cleaned = cleaned.strip()
    return json.loads(cleaned)


# ─── Schemas ───
class ReverseAnalyzeResponse(BaseModel):
    success: bool = True
    raw_idea: str
    suggested_name: str
    source_summary: str
    reverse_engineering: dict
    # Real extracted facts — echo this straight back into
    # POST /projects's reverse_engineering_data field.


# ─── SSRF guard (shared by url mode's crawl and every asset it fetches) ───
def _validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only http:// and https:// URLs are supported.")
    if not parsed.hostname:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That doesn't look like a valid URL.")

    try:
        addrinfo = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Could not resolve that URL's hostname.")

    for _family, _type, _proto, _canonname, sockaddr in addrinfo:
        ip = ipaddress.ip_address(sockaddr[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "That URL points at a private or internal address, which isn't allowed.",
            )


async def _fetch_raw(url: str) -> tuple[int, dict, bytes]:
    """GET a pre-validated URL, capped and never following redirects.
    Returns (0, {}, b"") on any network error so callers can just skip
    a page rather than aborting the whole crawl/repo scan."""
    try:
        async with httpx.AsyncClient(
            timeout=10.0,
            follow_redirects=False,
            headers={"User-Agent": "Mozilla/5.0 (compatible; VengaiCodeBot/1.0; +https://vengaicode.com)"},
        ) as client:
            async with client.stream("GET", url) as response:
                if response.status_code >= 300:
                    return response.status_code, dict(response.headers), b""
                chunks = []
                total = 0
                async for chunk in response.aiter_bytes():
                    chunks.append(chunk)
                    total += len(chunk)
                    if total >= MAX_URL_RESPONSE_BYTES:
                        break
                return response.status_code, dict(response.headers), b"".join(chunks)
    except httpx.HTTPError:
        return 0, {}, b""


# ─── Tech fingerprinting — real signature matching, not AI guessing ───
# The same kind of evidence-based detection tools like Wappalyzer use:
# known, publicly-documented markers left behind by each technology.
_HTML_SIGNATURES: list[tuple[str, str, list[str]]] = [
    ("Next.js", "meta_framework", [r"__NEXT_DATA__", r"/_next/static/"]),
    ("Nuxt.js", "meta_framework", [r"__NUXT__", r"/_nuxt/"]),
    ("SvelteKit", "meta_framework", [r"/_app/immutable/"]),
    ("React", "frontend_framework", [r"react-dom(\.production)?(\.min)?\.js", r"data-reactroot"]),
    ("Vue.js", "frontend_framework", [r"vue(\.global)?(\.runtime)?(\.min)?\.js", r"data-v-[0-9a-f]{6,10}="]),
    ("Angular", "frontend_framework", [r"ng-version="]),
    ("jQuery", "frontend_library", [r"jquery(-[\d.]+)?(\.min)?\.js"]),
    ("Bootstrap", "css_framework", [r"bootstrap(\.min)?\.css", r"bootstrap(\.bundle)?(\.min)?\.js"]),
    ("WordPress", "cms", [r"/wp-content/", r"/wp-includes/", r'generator["\']\s*content=["\']WordPress']),
    ("Shopify", "ecommerce_platform", [r"cdn\.shopify\.com", r"Shopify\.theme"]),
    ("Wix", "website_builder", [r"static\.wixstatic\.com"]),
    ("Squarespace", "website_builder", [r"static1\.squarespace\.com"]),
    ("Webflow", "website_builder", [r"assets-global\.website-files\.com", r'content=["\']Webflow']),
]

_HEADER_SIGNATURES: list[tuple[str, str, str]] = [
    ("nginx", "web_server", "nginx"),
    ("Cloudflare", "cdn", "cloudflare"),
    ("Vercel", "hosting", "vercel"),
    ("Netlify", "hosting", "netlify"),
    ("Express", "backend_runtime", "express"),
    ("Werkzeug (Flask dev server)", "backend_runtime", "werkzeug"),
    ("Gunicorn (Python)", "backend_runtime", "gunicorn"),
    ("ASP.NET Core (Kestrel)", "backend_runtime", "kestrel"),
    ("PHP", "backend_runtime", r"php/[\d.]"),
]

_COOKIE_SIGNATURES: list[tuple[str, str, str]] = [
    # "sessionid" alone is deliberately excluded — Django's default name for
    # it, but too generic a cookie name on its own to be a reliable signal
    # (plenty of non-Django backends use it too). csrftoken is distinctive.
    ("Django", "backend_framework", "csrftoken"),
    ("Laravel", "backend_framework", "laravel_session"),
    ("PHP", "backend_runtime", "phpsessid"),
    ("Java (Servlet)", "backend_runtime", "jsessionid"),
    ("Express/Node", "backend_runtime", "connect.sid"),
    ("ASP.NET Core", "backend_framework", ".aspnetcore."),
]


def fingerprint_tech_stack(html_evidence: str, headers: dict, cookie_names: list[str]) -> list[dict]:
    found: dict[str, dict] = {}

    for name, category, patterns in _HTML_SIGNATURES:
        for pattern in patterns:
            if re.search(pattern, html_evidence, re.I):
                found[name] = {"name": name, "category": category, "evidence": f'matched "{pattern}" in page source'}
                break

    header_blob = " ".join(f"{k}:{v}" for k, v in headers.items())
    for name, category, pattern in _HEADER_SIGNATURES:
        if re.search(pattern, header_blob, re.I):
            found.setdefault(name, {"name": name, "category": category, "evidence": "matched in response headers"})

    lowered_cookies = [c.lower() for c in cookie_names]
    for name, category, needle in _COOKIE_SIGNATURES:
        if any(needle in c for c in lowered_cookies):
            found.setdefault(name, {"name": name, "category": category, "evidence": "matched cookie name set by the server"})

    return list(found.values())


# ─── URL mode: crawl + extract ───
class _PageExtractor(html.parser.HTMLParser):
    """Pulls title/visible text/links/scripts/stylesheets/forms/meta-generator
    out of one HTML page — stdlib-only, same rationale as the earlier
    single-page extractor this replaces: this is a rough real-facts sketch,
    not a structured DOM diff."""

    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.title = ""
        self.text_parts: list[str] = []
        self.links: set[str] = set()
        self.scripts: list[str] = []
        self.stylesheets: list[str] = []
        self.forms: list[dict] = []
        self.meta_generator = ""
        self._in_title = False
        self._skip_depth = 0
        self._current_form: dict | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        attrs_d = dict(attrs)
        if tag == "title":
            self._in_title = True
        if tag in ("script", "style", "noscript", "svg", "head"):
            self._skip_depth += 1
        if tag == "meta" and (attrs_d.get("name") or "").lower() == "generator":
            self.meta_generator = attrs_d.get("content") or ""
        if tag == "a" and attrs_d.get("href"):
            try:
                href = urljoin(self.base_url, attrs_d["href"]).split("#")[0]
                self.links.add(href)
            except ValueError:
                pass
        if tag == "script" and attrs_d.get("src"):
            self.scripts.append(urljoin(self.base_url, attrs_d["src"]))
        if tag == "link" and (attrs_d.get("rel") or "").lower() == "stylesheet" and attrs_d.get("href"):
            self.stylesheets.append(urljoin(self.base_url, attrs_d["href"]))
        if tag == "form":
            self._current_form = {
                "action": urljoin(self.base_url, attrs_d.get("action") or self.base_url),
                "method": (attrs_d.get("method") or "get").upper(),
                "fields": [],
            }
        if tag in ("input", "select", "textarea") and self._current_form is not None:
            name = attrs_d.get("name")
            if name:
                self._current_form["fields"].append(
                    {"name": name, "type": attrs_d.get("type") or ("text" if tag == "input" else tag)}
                )

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag in ("script", "style", "noscript", "svg", "head") and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag == "form" and self._current_form is not None:
            self.forms.append(self._current_form)
            self._current_form = None

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
            return
        if self._skip_depth:
            return
        stripped = data.strip()
        if stripped:
            self.text_parts.append(stripped)


def _infer_data_model(forms: list[dict]) -> list[dict]:
    """Groups real <form> field names into entity guesses — grounded in
    what the page actually asks for, not invented. A form with a password
    field is auth; a 1-2 field form named q/query/search is a search box
    (skipped, not a real entity); anything else becomes a named entity
    guessed from its action path."""
    entities: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for form in forms:
        # Dedupe (radio/checkbox groups repeat one name per option) and drop
        # dunder-prefixed names -- real-world false positive caught live on
        # fastapi.tiangolo.com's MkDocs theme, whose light/dark toggle is a
        # <form> of three radios all named "__palette": UI chrome, not data.
        seen_names: set[str] = set()
        field_names = []
        for f in form.get("fields", []):
            name = f.get("name")
            if not name or name.startswith("__") or name in seen_names:
                continue
            seen_names.add(name)
            field_names.append(name)
        if not field_names:
            continue
        lowered = [n.lower() for n in field_names]

        if any(n in ("password", "pwd", "pass", "passwd") for n in lowered):
            kind = "auth"
        elif len(field_names) <= 2 and any(n in ("q", "query", "search", "s") for n in lowered):
            continue
        else:
            kind = "record"

        action_path = urlparse(form.get("action", "")).path.strip("/")
        segments = [s for s in action_path.split("/") if s and not s.isdigit()]
        name_guess = (segments[-1] if segments else "entry").replace("-", "_").replace(".", "_")
        if kind == "auth":
            name_guess = "user_auth"

        key = (name_guess, kind)
        if key in seen:
            continue
        seen.add(key)
        entities.append({"name": name_guess, "kind": kind, "fields": field_names, "source_form_action": form.get("action")})

    return entities[:15]


async def _download_asset_snippets(urls: list[str]) -> list[dict]:
    snippets = []
    for asset_url in urls[:MAX_ASSET_FILES]:
        try:
            _validate_public_url(asset_url)
        except HTTPException:
            continue
        status_code, _headers, body = await _fetch_raw(asset_url)
        if status_code != 200 or not body:
            continue
        text = body[:MAX_ASSET_BYTES].decode("utf-8", errors="replace")
        language = "css" if asset_url.split("?")[0].endswith(".css") else "javascript"
        snippets.append({"source": asset_url, "language": language, "content": text[:ASSET_SNIPPET_CHARS]})
    return snippets


async def _crawl_site(seed_url: str) -> dict:
    """Same-origin BFS crawl, bounded by page count, depth, and a wall-clock
    budget. Every discovered link is re-validated through _validate_public_url
    before being fetched — a malicious page could otherwise link to an
    internal address and have the crawler follow it there."""
    _validate_public_url(seed_url)
    origin_host = urlparse(seed_url).hostname

    visited: set[str] = set()
    queue: list[tuple[str, int]] = [(seed_url, 0)]
    pages: list[dict] = []
    all_forms: list[dict] = []
    raw_html_evidence = ""
    headers_evidence: dict = {}
    cookies_evidence: list[str] = []
    script_urls: list[str] = []
    style_urls: list[str] = []

    start = time.monotonic()
    while queue and len(pages) < MAX_CRAWL_PAGES:
        if time.monotonic() - start > CRAWL_TIME_BUDGET_SECONDS:
            break
        url, depth = queue.pop(0)
        norm = url.split("#")[0].rstrip("/")
        if norm in visited:
            continue
        visited.add(norm)

        try:
            _validate_public_url(url)
        except HTTPException:
            continue

        status_code, headers, body = await _fetch_raw(url)
        if status_code == 0 or status_code >= 300:
            continue
        content_type = headers.get("content-type", "")
        if "html" not in content_type:
            continue

        if not pages:
            headers_evidence = headers
            set_cookie = headers.get("set-cookie", "")
            if set_cookie:
                cookies_evidence.append(set_cookie.split("=")[0].strip())

        html_text = body.decode("utf-8", errors="replace")
        raw_html_evidence += html_text[:20_000]

        extractor = _PageExtractor(url)
        extractor.feed(html_text)

        for form in extractor.forms:
            all_forms.append({**form, "page_url": url})
        for s in extractor.scripts:
            if s not in script_urls:
                script_urls.append(s)
        for s in extractor.stylesheets:
            if s not in style_urls:
                style_urls.append(s)

        pages.append(
            {
                "url": url,
                "title": extractor.title.strip(),
                "text_excerpt": " ".join(extractor.text_parts)[:600],
                "form_count": len(extractor.forms),
                "link_count": len(extractor.links),
            }
        )

        if depth < MAX_CRAWL_DEPTH:
            for link in extractor.links:
                link_parsed = urlparse(link)
                if link_parsed.hostname != origin_host or link_parsed.scheme not in ("http", "https"):
                    continue
                norm_link = link.split("#")[0].rstrip("/")
                if norm_link not in visited:
                    queue.append((link, depth + 1))

    if not pages:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Couldn't fetch any readable pages from that URL.")

    tech_stack = fingerprint_tech_stack(raw_html_evidence, headers_evidence, cookies_evidence)
    data_model = _infer_data_model(all_forms)
    code_snippets = await _download_asset_snippets(script_urls + style_urls)

    return {
        "mode": "url",
        "pages_crawled": len(pages),
        "pages": pages,
        "tech_stack": tech_stack,
        "data_model": data_model,
        "code_snippets": code_snippets,
    }


def _material_from_site_analysis(site: dict) -> str:
    lines = [f"Pages crawled ({site['pages_crawled']}):"]
    for p in site["pages"][:8]:
        lines.append(f"- {p['title'] or p['url']}: {p['text_excerpt'][:200]}")
    if site["tech_stack"]:
        lines.append("\nDetected technology: " + ", ".join(t["name"] for t in site["tech_stack"]))
    if site["data_model"]:
        lines.append("\nData entities observed (from real page forms): " + ", ".join(e["name"] for e in site["data_model"]))
    return "\n".join(lines)


# ─── Repo mode: real source-code analysis via the GitHub API ───
GITHUB_REPO_RE = re.compile(r"^https?://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")

MANIFEST_FILENAMES = {
    "package.json", "requirements.txt", "pyproject.toml", "Pipfile",
    "go.mod", "Cargo.toml", "pom.xml", "build.gradle", "Gemfile", "composer.json",
}

_PACKAGE_JSON_MAP = {
    "react": "React", "next": "Next.js", "vue": "Vue.js", "nuxt": "Nuxt.js",
    "@angular/core": "Angular", "svelte": "Svelte", "express": "Express",
    "fastify": "Fastify", "@nestjs/core": "NestJS", "koa": "Koa",
    # Shell/wrapper frameworks — a "shell app" that just wraps a website or
    # API behind a native window is built with one of these. Detecting them
    # tells you HOW the wrapper itself was built, distinct from whatever
    # site/API it wraps (which url mode would separately analyze if you
    # know the URL it loads).
    "electron": "Electron", "electron-builder": "Electron",
    "@tauri-apps/api": "Tauri", "@tauri-apps/cli": "Tauri",
    "react-native": "React Native", "react-native-webview": "React Native WebView",
    "expo": "Expo", "@capacitor/core": "Capacitor", "cordova-lib": "Apache Cordova",
}

# Config files whose mere presence in a repo's file tree is itself real
# evidence of a shell/wrapper framework — no need to fetch their content.
_SHELL_CONFIG_FILE_SIGNATURES: list[tuple[str, str]] = [
    ("tauri.conf.json", "Tauri"),
    ("capacitor.config.json", "Capacitor"),
    ("capacitor.config.ts", "Capacitor"),
    ("electron-builder.yml", "Electron"),
    ("electron-builder.json", "Electron"),
    ("forge.config.js", "Electron (Forge)"),
]


def _detect_shell_framework_from_tree(paths: list[str]) -> list[dict]:
    found = []
    basenames = {p.rsplit("/", 1)[-1] for p in paths}
    for filename, name in _SHELL_CONFIG_FILE_SIGNATURES:
        if filename in basenames:
            found.append({"name": name, "category": "shell_framework", "evidence": f"found {filename} in the repo"})
    return found

_MANIFEST_TEXT_PATTERNS: dict[str, list[tuple[re.Pattern, str]]] = {
    "requirements.txt": [
        (re.compile(r"(?im)^fastapi"), "FastAPI"), (re.compile(r"(?im)^flask"), "Flask"),
        (re.compile(r"(?im)^django"), "Django"), (re.compile(r"(?im)^celery"), "Celery"),
    ],
    "pyproject.toml": [
        (re.compile(r"fastapi"), "FastAPI"), (re.compile(r"\bflask\b"), "Flask"), (re.compile(r"\bdjango\b"), "Django"),
    ],
    "Cargo.toml": [(re.compile(r"actix-web"), "Actix Web"), (re.compile(r"\baxum\b"), "Axum")],
    "Gemfile": [(re.compile(r"gem\s+['\"]rails['\"]"), "Ruby on Rails")],
    "pom.xml": [(re.compile(r"spring-boot"), "Spring Boot")],
    "build.gradle": [(re.compile(r"spring-boot"), "Spring Boot")],
    "composer.json": [(re.compile(r"laravel/framework"), "Laravel")],
    "go.mod": [(re.compile(r"gin-gonic/gin"), "Gin"), (re.compile(r"labstack/echo"), "Echo")],
}

ROUTE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("Express/Node", re.compile(r"(?:app|router)\.(get|post|put|delete|patch)\(\s*[\"']([^\"']+)[\"']", re.I)),
    ("FastAPI/Flask", re.compile(r"@\w+\.(get|post|put|delete|patch)\(\s*[\"']([^\"']+)[\"']", re.I)),
    ("Django", re.compile(r"\bpath\(\s*[\"']([^\"']*)[\"']")),
    ("Rails", re.compile(r"^\s*(get|post|put|patch|delete)\s+[\"']([^\"']+)[\"']", re.M | re.I)),
    ("Spring", re.compile(r"@(Get|Post|Put|Delete|Patch)Mapping\(\s*(?:value\s*=\s*)?[\"']([^\"']+)[\"']")),
    ("Laravel", re.compile(r"Route::(get|post|put|delete|patch)\(\s*[\"']([^\"']+)[\"']", re.I)),
]

MODEL_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("SQLAlchemy", re.compile(r"class\s+(\w+)\([^)]*Base[^)]*\)")),
    ("Django ORM", re.compile(r"class\s+(\w+)\(models\.Model\)")),
    ("Prisma", re.compile(r"model\s+(\w+)\s*\{")),
    ("TypeORM", re.compile(r"@Entity\(\)[^\n]*\n(?:export\s+)?class\s+(\w+)")),
    ("Mongoose", re.compile(r"const\s+(\w+)Schema\s*=\s*new\s+mongoose\.Schema")),
]

_INTERESTING_FILE_RE = re.compile(r"(route|router|url|view|controller|model|schema|entity|api)", re.I)
_INTERESTING_EXTENSIONS = {"py", "js", "ts", "jsx", "tsx", "rb", "java", "go", "rs", "php", "prisma"}

# The web-backend keyword filter above finds nothing in a shell/wrapper app
# (Electron/Tauri/Capacitor/...) — its real "core code" lives in differently
# named files: the main-process entry point, preload script, window/menu/
# tray setup, and whatever config points it at the site/API it wraps. Caught
# live testing against a real shell app (sindresorhus/caprine, an Electron
# wrapper around messenger.com): _INTERESTING_FILE_RE matched nothing in its
# real source tree (index.ts, menu.ts, tray.ts, browser.ts, config.ts, ...),
# so 0 code_snippets came back for exactly the "how was this shell built"
# case this feature is supposed to answer. Only applied when a shell
# framework was actually detected (via _detect_shell_framework_from_tree /
# _detect_stack_from_manifest) — a general web-backend repo's "index.ts" or
# "config.ts" is rarely its architecturally interesting file, so this stays
# off for every repo that isn't already confirmed to be a shell app.
_SHELL_CORE_FILE_STEMS = {
    "main", "index", "preload", "window", "menu", "tray", "app",
    "browser", "config", "notifications", "notification",
}
_SHELL_ENTRY_POINT_STEMS = {"main", "index", "preload"}


def _is_shell_core_file(path: str) -> bool:
    basename = path.rsplit("/", 1)[-1]
    stem = basename.split(".", 1)[0].lower().split("-")[0]
    return stem in _SHELL_CORE_FILE_STEMS


def _dedupe_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


_SHELL_PACKAGE_NAMES = set(
    pkg for pkg, name in _PACKAGE_JSON_MAP.items()
    if name in {"Electron", "Tauri", "React Native", "React Native WebView", "Expo", "Capacitor", "Apache Cordova"}
)


def _package_json_has_shell_dependency(content: str) -> bool:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return False
    deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
    return any(name in deps for name in _SHELL_PACKAGE_NAMES)


async def _github_api_get(path: str):
    url = f"https://api.github.com/{path}"
    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            # Unlike url mode's crawl (an arbitrary, user-controlled target —
            # SSRF-sensitive, redirects refused), this always hits the fixed
            # literal host api.github.com. A redirect here can only ever be
            # GitHub's own "repo was renamed" 301 to another api.github.com
            # path, never an attacker-controlled host, so following it is
            # safe — and refusing it silently returned a {"message": "Moved
            # Permanently"} stub in place of real data for any renamed repo
            # (caught live against electron/electron-quick-start).
            follow_redirects=True,
            headers={"User-Agent": "VengaiCodeBot/1.0", "Accept": "application/vnd.github+json"},
        ) as client:
            resp = await client.get(url)
    except httpx.HTTPError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Couldn't reach GitHub: {e}")

    if resp.status_code == 403:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "GitHub's API rate limit was hit — please try again in a bit, or use the URL/screenshots mode instead.",
        )
    if resp.status_code == 404:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That GitHub repo wasn't found, or it's private.")
    if resp.status_code >= 400:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"GitHub returned HTTP {resp.status_code}.")
    return resp.json()


def _detect_stack_from_manifest(filename: str, content: str) -> list[dict]:
    found = []
    if filename == "package.json":
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return []
        deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        for pkg, name in _PACKAGE_JSON_MAP.items():
            if pkg in deps:
                found.append({"name": name, "category": "framework", "evidence": f'package.json dependency "{pkg}"'})
    else:
        for pattern, name in _MANIFEST_TEXT_PATTERNS.get(filename, []):
            if pattern.search(content):
                found.append({"name": name, "category": "framework", "evidence": f"matched in {filename}"})
    return found


def _dedupe(items: list[dict], keyfn) -> list[dict]:
    seen = set()
    out = []
    for item in items:
        k = keyfn(item)
        if k in seen:
            continue
        seen.add(k)
        out.append(item)
    return out


MAX_COMMITS_FETCHED = 20


async def _fetch_commit_history(owner: str, repo: str, branch: str) -> list[dict]:
    """The closest thing to real "steps followed to build it" this feature
    can honestly offer: a repo's own real commit history, not an inferred
    guess. Deliberately scoped to the most recent MAX_COMMITS_FETCHED commits
    (GitHub's API returns newest-first; walking all the way back to a
    project's first commit on a large repo would mean many more paginated
    requests against a 60/hr unauthenticated rate limit) — labeled as such
    in the returned dict rather than implied to be the full project history."""
    try:
        data = await _github_api_get(f"repos/{owner}/{repo}/commits?sha={branch}&per_page={MAX_COMMITS_FETCHED}")
    except HTTPException:
        return []
    if not isinstance(data, list):
        return []

    commits = []
    for item in data:
        commit = item.get("commit") or {}
        author = commit.get("author") or {}
        message = (commit.get("message") or "").split("\n", 1)[0][:200]
        commits.append(
            {
                "sha": (item.get("sha") or "")[:7],
                "message": message,
                "author": author.get("name", "unknown"),
                "date": author.get("date", ""),
            }
        )
    commits.reverse()  # API gives newest-first; present chronologically (oldest first)
    return commits


async def _analyze_repo(repo_url: str) -> dict:
    match = GITHUB_REPO_RE.match(repo_url.strip())
    if not match:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Please paste a public GitHub repo URL, like https://github.com/owner/repo.")
    owner, repo = match.group(1), match.group(2)

    meta = await _github_api_get(f"repos/{owner}/{repo}")
    branch = meta.get("default_branch") or "main"
    language = meta.get("language")

    tree_data = await _github_api_get(f"repos/{owner}/{repo}/git/trees/{branch}?recursive=1")
    entries = [e for e in tree_data.get("tree", []) if e.get("type") == "blob" and e.get("path")]
    if not entries:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That repo's file tree looks empty.")

    paths = [e["path"] for e in entries]
    shell_tech = _detect_shell_framework_from_tree(paths)
    commit_history = await _fetch_commit_history(owner, repo, branch)

    # A checked-in config file (tauri.conf.json etc.) isn't the only real
    # shell signal — Electron apps like sindresorhus/caprine declare it as
    # a plain package.json dependency instead. Check that up front (one
    # cheap extra fetch) so it's known before deciding which "interesting"
    # files to pull below; the main fetch loop re-reads package.json
    # normally afterward.
    is_shell_app = bool(shell_tech)
    if not is_shell_app and "package.json" in paths:
        pkg_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/package.json"
        try:
            _validate_public_url(pkg_url)
            status_code, _headers, body = await _fetch_raw(pkg_url)
            if status_code == 200 and body:
                is_shell_app = _package_json_has_shell_dependency(body[:MAX_REPO_FILE_BYTES].decode("utf-8", errors="replace"))
        except HTTPException:
            pass

    manifest_paths = [p for p in paths if p.rsplit("/", 1)[-1] in MANIFEST_FILENAMES and p.count("/") <= 1][:6]

    shell_core_paths: list[str] = []
    if is_shell_app:
        shell_core_paths = [
            p
            for p in paths
            if p not in manifest_paths
            and "." in p
            and p.rsplit(".", 1)[-1] in _INTERESTING_EXTENSIONS
            and _is_shell_core_file(p)
        ]
        shell_core_paths.sort(key=lambda p: 0 if p.rsplit("/", 1)[-1].split(".")[0].lower() in _SHELL_ENTRY_POINT_STEMS else 1)

    interesting_paths = [
        p
        for p in paths
        if p not in manifest_paths
        and _INTERESTING_FILE_RE.search(p)
        and "." in p
        and p.rsplit(".", 1)[-1] in _INTERESTING_EXTENSIONS
    ]
    combined_interesting = _dedupe_strings(shell_core_paths + interesting_paths)[:MAX_REPO_FILES_FETCHED]
    fetch_paths = (manifest_paths + combined_interesting)[:MAX_REPO_FILES_FETCHED]

    tech_stack: list[dict] = list(shell_tech)
    routes: list[dict] = []
    db_models: list[dict] = []
    code_snippets: list[dict] = []

    for path in fetch_paths:
        raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
        try:
            _validate_public_url(raw_url)
        except HTTPException:
            continue
        status_code, _headers, body = await _fetch_raw(raw_url)
        if status_code != 200 or not body:
            continue
        text = body[:MAX_REPO_FILE_BYTES].decode("utf-8", errors="replace")
        filename = path.rsplit("/", 1)[-1]

        if filename in MANIFEST_FILENAMES:
            tech_stack.extend(_detect_stack_from_manifest(filename, text))
            continue

        for framework_name, pattern in ROUTE_PATTERNS:
            for m in pattern.finditer(text):
                method = m.group(1).upper() if m.re.groups >= 2 else "GET"
                route_path = m.group(m.re.groups)
                routes.append({"framework": framework_name, "method": method, "path": route_path, "file": path})

        for orm_name, pattern in MODEL_PATTERNS:
            for m in pattern.finditer(text):
                db_models.append({"orm": orm_name, "name": m.group(1), "file": path})

        if len(code_snippets) < MAX_REPO_SNIPPETS:
            code_snippets.append({"source": path, "language": filename.rsplit(".", 1)[-1], "content": text[:REPO_SNIPPET_CHARS]})

    tech_stack = _dedupe(tech_stack, lambda t: t["name"])
    routes = _dedupe(routes, lambda r: (r["method"], r["path"]))[:25]
    db_models = _dedupe(db_models, lambda m_: m_["name"])[:20]

    if language and not any(t["name"].lower() == language.lower() for t in tech_stack):
        tech_stack.insert(0, {"name": language, "category": "language", "evidence": "GitHub-reported primary language"})

    return {
        "mode": "repo",
        "repo": f"{owner}/{repo}",
        "files_scanned": len(fetch_paths),
        "tech_stack": tech_stack,
        "api_endpoints": routes,
        "data_model": db_models,
        "code_snippets": code_snippets,
        "commit_history": commit_history,
        "commit_history_note": f"most recent {len(commit_history)} commits on {branch}, not the repo's full history",
    }


def _material_from_repo_analysis(repo_analysis: dict) -> str:
    lines = [f"Repo: {repo_analysis['repo']} ({repo_analysis['files_scanned']} source files scanned)"]
    if repo_analysis["tech_stack"]:
        lines.append("Detected technology: " + ", ".join(t["name"] for t in repo_analysis["tech_stack"]))
    if repo_analysis["api_endpoints"]:
        sample = ", ".join(f"{e['method']} {e['path']}" for e in repo_analysis["api_endpoints"][:12])
        lines.append(f"Real API endpoints found: {sample}")
    if repo_analysis["data_model"]:
        lines.append("Real data models found: " + ", ".join(m["name"] for m in repo_analysis["data_model"][:12]))
    commits = repo_analysis.get("commit_history") or []
    if commits:
        span = f"{commits[0]['date'][:10]} to {commits[-1]['date'][:10]}" if commits[0].get("date") and commits[-1].get("date") else ""
        lines.append(f"Recent real build history ({len(commits)} commits{', ' + span if span else ''}):")
        for c in commits[-5:]:
            lines.append(f"  - {c['message']}")
    return "\n".join(lines)


# ─── Screenshots mode ───
async def _analyze_screenshots(files: list[UploadFile]) -> tuple[str, dict]:
    if len(files) > MAX_SCREENSHOTS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Please upload at most {MAX_SCREENSHOTS} screenshots.")

    descriptions = []
    screens = []
    for index, file in enumerate(files):
        if file.content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"'{file.filename}' isn't a supported image type (PNG, JPEG, or WebP only).",
            )
        content = await file.read()
        if len(content) > MAX_SCREENSHOT_BYTES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"'{file.filename}' is too large (8 MB max).")

        image_b64 = base64.b64encode(content).decode("ascii")
        try:
            result = await generate_vision(
                "Describe this app screen in concrete detail: what screen/page is this, what "
                "real UI elements and content does it show, and what capability or user action "
                "does it represent? Be specific about what you actually see, not generic.",
                image_b64,
                file.content_type,
            )
        except AIError as e:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))

        descriptions.append(f"Screenshot {index + 1} ({file.filename}): {result['text']}")
        screens.append({"filename": file.filename, "description": result["text"][:600]})

    material = "\n\n".join(descriptions)
    reverse_engineering = {"mode": "screenshots", "screens_analyzed": len(files), "screens": screens}
    return material, reverse_engineering


# ─── Synthesis ───
_SYNTHESIS_PROMPT = """You are Baby Tiger \U0001f42f, VengaiCode's AI assistant. A user wants to build an app inspired by an EXISTING app/website they've pointed you at. Below is real material gathered about that existing app — read it and write a description of an app AS IF the user were describing their own original app idea in their own words (the way they'd type it into an idea box), suitable for VengaiCode's own requirements-gathering wizard to ask follow-up questions about.

Source: {source_kind}

Gathered material:
{material}

Requirements:
- Ground every claim in the real material above — do not invent features or details it doesn't support.
- Do not mention that this was reverse-engineered from another app, a screenshot, a URL, or a repo — phrase it as a first-person app idea.
- "raw_idea" should be a detailed paragraph (4-8 sentences): what the app does, who it's for, its core features and screens, and what makes it distinctive.
- "suggested_name" is a short, real app name (2-4 words, no punctuation/quotes).

Respond with ONLY this JSON object, no markdown, no extra text:
{{"suggested_name": "...", "raw_idea": "..."}}"""


def build_reverse_engineering_directive(reverse_data: dict | None) -> str:
    """Used by requirements.py's build_frd_prompt and architecture.py's
    build_architecture_prompt to ground those AI calls in REAL facts
    extracted by this module, instead of letting the AI re-guess a
    plausible-sounding feature list/tech stack from prose alone."""
    if not reverse_data:
        return ""

    parts = [
        "\nThis project was started from VengaiCode's Reverse App feature — real technical facts were "
        "extracted from an existing app/site/repo the user pointed at. Ground your output in these REAL "
        "facts and do not contradict them:\n"
    ]
    tech = reverse_data.get("tech_stack") or []
    if tech:
        parts.append("Detected technology: " + ", ".join(t["name"] for t in tech[:10]))
    pages = reverse_data.get("pages") or []
    if pages:
        parts.append("Real pages/screens found: " + ", ".join((p.get("title") or p.get("url", ""))[:60] for p in pages[:10] if (p.get("title") or p.get("url"))))
    data_model = reverse_data.get("data_model") or []
    if data_model:
        parts.append("Real data entities/models found: " + ", ".join(e.get("name", "") for e in data_model[:10]))
    endpoints = reverse_data.get("api_endpoints") or []
    if endpoints:
        parts.append("Real API endpoints found: " + ", ".join(f"{e.get('method', '')} {e.get('path', '')}".strip() for e in endpoints[:10]))
    if reverse_data.get("repo"):
        parts.append(f"Source repo scanned: {reverse_data['repo']}")
    commits = reverse_data.get("commit_history") or []
    if commits:
        parts.append(
            f"Real recent build history ({reverse_data.get('commit_history_note', f'{len(commits)} commits')}): "
            + "; ".join(c["message"] for c in commits[-5:] if c.get("message"))
        )

    return "\n".join(parts) + "\n" if len(parts) > 1 else ""


@router.post(
    "/analyze",
    response_model=ReverseAnalyzeResponse,
    summary="Reverse-engineer an existing app/website/repo and synthesize a VengaiCode project idea from it",
)
async def analyze(
    source_type: str = Form(...),
    url: str | None = Form(None),
    repo_url: str | None = Form(None),
    description: str | None = Form(None),
    files: list[UploadFile] = File(default=[]),
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    reverse_engineering: dict

    if source_type == "url":
        if not url or not url.strip():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Please provide a URL.")
        reverse_engineering = await _crawl_site(url.strip())
        material = _material_from_site_analysis(reverse_engineering)
        source_kind = f"a website ({url.strip()}) — {reverse_engineering['pages_crawled']} real pages were crawled"
    elif source_type == "repo":
        if not repo_url or not repo_url.strip():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Please provide a GitHub repo URL.")
        reverse_engineering = await _analyze_repo(repo_url.strip())
        material = _material_from_repo_analysis(reverse_engineering)
        source_kind = f"a GitHub repository ({reverse_engineering['repo']}) — its real source code was scanned"
    elif source_type == "screenshots":
        if not files:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Please upload at least one screenshot.")
        material, reverse_engineering = await _analyze_screenshots(files)
        source_kind = "screenshots of an existing app"
    elif source_type == "description":
        if not description or not description.strip():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Please describe the app you want to clone.")
        material = description.strip()
        source_kind = "a text description of an existing app, written by the user"
        reverse_engineering = {"mode": "description"}
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "source_type must be 'url', 'repo', 'screenshots', or 'description'.")

    prompt = _SYNTHESIS_PROMPT.format(source_kind=source_kind, material=material[:MAX_MATERIAL_CHARS_IN_PROMPT])

    try:
        ai_result = await generate_text(prompt, user=user, db=db)
    except AIError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))

    try:
        parsed = parse_ai_json(ai_result["text"])
        raw_idea = str(parsed["raw_idea"]).strip()
        suggested_name = str(parsed["suggested_name"]).strip()
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as e:
        logger.error(f"Failed to parse reverse-engineer synthesis response: {e}")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Baby Tiger had trouble turning that into an app idea. Please try again! \U0001f42f",
        )

    if not raw_idea:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Baby Tiger couldn't come up with an idea from that. Please try again!")

    return ReverseAnalyzeResponse(
        raw_idea=raw_idea,
        suggested_name=suggested_name or "My App",
        source_summary=material[:300],
        reverse_engineering=reverse_engineering,
    )
