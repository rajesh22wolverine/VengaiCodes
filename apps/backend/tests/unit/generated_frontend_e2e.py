"""
What the tests that build a generated frontend and use it in a browser
share (not a test module itself — see test_frontend_build_e2e.py and
test_installer_frontend_e2e.py).

Nothing is mocked: the frontend is installed with npm and built with its
own bundler, the backend is the generated FastAPI app serving a real SQLite
file, the built site is served over HTTP, and a real browser (Chromium,
through Playwright) clicks through the screens — the list, a create, the
server's refusals shown to the user, foreign keys as choices, a delete and
what it cascades to.

Toolchains, as in generated_backend_e2e: `node` (npm) to build, `browser`
(the playwright package and its Chromium: `pip install -r
requirements-dev.txt`, then `python -m playwright install chromium`) to
use the result. Without one the test is skipped — unless
VENGAI_REQUIRE_TOOLCHAINS lists it, which the backend CI job does.
"""

import contextlib
import http.server
import os
import pathlib
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request

import generated_backend_e2e as e2e
import pytest

# What `npm install` leaves in a project, kept from one run to the next.
INSTALLED = ("node_modules", "package-lock.json")

# How each frontend's navigation names the screen of a table called e.g.
# "Customers": the component's name, or the table's.
NAV_NAMES = {
    "react": "{}Screen",
    "vue": "{}Screen",
    "svelte": "{}Screen",
    "angular": "{}",
    "html_css_js": "{}",
}


def npm() -> str:
    return e2e.toolchain("node", "npm")


def npm_env() -> dict:
    # The Angular CLI asks about usage data the first time it runs.
    return {**os.environ, "NG_CLI_ANALYTICS": "false"}


def clear_project(folder: pathlib.Path) -> None:
    """Empties a project folder of everything but what npm installed."""
    if folder.exists():
        for entry in folder.iterdir():
            if entry.name in INSTALLED:
                continue
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()
    folder.mkdir(parents=True, exist_ok=True)


def write_files(data: dict, prefix: str, folder: pathlib.Path) -> None:
    """Writes the generated files under `prefix` (e.g. "frontend/") into
    `folder`."""
    for f in data["codegen"]["files"]:
        if f["path"].startswith(prefix):
            target = folder / f["path"][len(prefix) :]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(f["content"].encode("utf-8"))


def install_and_build(folder: pathlib.Path) -> pathlib.Path:
    """`npm install`, `npm run build`; returns the folder a web server would
    serve — where the built index.html is (Vite: dist/, the Angular CLI:
    dist/<project>/browser/)."""
    e2e.run([npm(), "install", "--no-audit", "--no-fund"], str(folder), 900, npm_env())
    e2e.run([npm(), "run", "build"], str(folder), 900, npm_env())
    pages = sorted((folder / "dist").rglob("index.html"), key=lambda p: len(p.parts))
    assert pages, "the build wrote no index.html"
    return pages[0].parent


def built_text(site: pathlib.Path, suffix: str) -> str:
    return "".join(p.read_text(encoding="utf-8") for p in site.rglob(f"*{suffix}"))


# ───────────────────────────────────────────────
#  The generated backend, and the built site, as servers
# ───────────────────────────────────────────────
def start_api(data: dict, tmp_path, port: int | None = None) -> e2e.Server:
    """The generated FastAPI backend, serving on a free port (or `port`)
    with a new database (its migrations create and seed it as it starts).
    Use as a context manager; `.port` is where it listens."""
    backend = tmp_path / "backend"
    write_files(data, "backend/", backend)
    site_packages = [p for p in sys.path if p.rstrip("\\/").endswith("site-packages")]
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(backend), *site_packages]),
        "PYTHONIOENCODING": "utf-8",
    }
    env.pop("DATABASE_URL", None)
    serve = (
        "import uvicorn; from main import app; "
        "uvicorn.run(app, host='127.0.0.1', port={port}, log_level='warning')"
    )
    return e2e.Server(
        [sys.executable, "-c", serve],
        env,
        str(tmp_path / "api.log"),
        str(backend),
        port,
    )


_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".map": "application/json",
    ".woff2": "font/woff2",
}


class Site:
    """A built frontend served from one origin, the way a browser gets it.

    With `api`, requests for /api/... are passed on to that address — what
    a dev server's proxy, or a reverse proxy in front of both, does. Without
    it the page has to reach its backend by itself. `headers` are sent with
    every file (a Content-Security-Policy, say)."""

    def __init__(self, root: pathlib.Path, api: str | None = None, headers=None):
        site = self
        self.root = root
        self.api = api
        self.headers = dict(headers or {})

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):  # quiet
                pass

            def _forward(self):
                length = int(self.headers.get("Content-Length") or 0)
                request = urllib.request.Request(
                    site.api + self.path,
                    data=self.rfile.read(length) if length else None,
                    method=self.command,
                    headers={
                        "Content-Type": self.headers.get("Content-Type")
                        or "application/json"
                    },
                )
                try:
                    with urllib.request.urlopen(request, timeout=30) as response:
                        status, body, kind = (
                            response.status,
                            response.read(),
                            response.headers.get("Content-Type"),
                        )
                except urllib.error.HTTPError as err:
                    status, body, kind = (
                        err.code,
                        err.read(),
                        err.headers.get("Content-Type"),
                    )
                self.send_response(status)
                if kind:
                    self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _file(self):
                relative = self.path.split("?")[0].lstrip("/") or "index.html"
                path = (site.root / relative).resolve()
                if site.root.resolve() not in path.parents or not path.is_file():
                    self.send_error(404)
                    return
                body = path.read_bytes()
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    _CONTENT_TYPES.get(path.suffix, "application/octet-stream"),
                )
                self.send_header("Content-Length", str(len(body)))
                for name, value in site.headers.items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(body)

            def _handle(self):
                if site.api and self.path.startswith("/api/"):
                    self._forward()
                elif self.command == "GET":
                    self._file()
                else:
                    self.send_error(404)

            do_GET = do_POST = do_PUT = do_DELETE = _handle

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def __enter__(self):
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()


# ───────────────────────────────────────────────
#  The browser
# ───────────────────────────────────────────────
def _missing_browser(why: str):
    if "browser" in os.environ.get("VENGAI_REQUIRE_TOOLCHAINS", "").split(","):
        pytest.fail(f"VENGAI_REQUIRE_TOOLCHAINS lists browser, but {why}")
    pytest.skip(f"needs a browser: {why}")


class Page:
    """A browser page on the app, with what the checks keep needing: the
    errors the page itself reported, and waiting until the app's requests
    have been answered instead of for a fixed time."""

    def __init__(self, page):
        self.page = page
        self.errors: list[str] = []
        self._pending = 0
        self._last = time.time()
        page.on("pageerror", lambda err: self.errors.append(f"pageerror: {err}"))
        page.on("console", self._console)
        page.on("request", lambda request: self._track(request, 1))
        page.on("requestfinished", lambda request: self._track(request, -1))
        page.on("requestfailed", lambda request: self._track(request, -1))

    def _console(self, message) -> None:
        # The browser's own note about a refused request (a 409, a 422) isn't
        # the app's error; anything else on the error channel is.
        if message.type == "error" and not message.text.startswith(
            "Failed to load resource"
        ):
            self.errors.append(f"console: {message.text}")

    def _track(self, request, change: int) -> None:
        if "/api/" in request.url:
            self._pending += change
            self._last = time.time()

    def settle(self) -> None:
        """Until the app's API calls are answered and it has drawn the result."""
        self.page.wait_for_timeout(100)
        deadline = time.time() + 20
        while self._pending > 0 or time.time() - self._last < 0.3:
            assert time.time() < deadline, "the app's requests never finished"
            self.page.wait_for_timeout(50)
        self.page.wait_for_timeout(100)

    def open_screen(self, name: str, field: str | None = None) -> None:
        self.page.get_by_role("button", name=name, exact=True).click()
        if field:
            self.page.wait_for_selector(f"#field-{field}")
        self.settle()

    def add(self) -> None:
        self.page.get_by_role("button", name="Add", exact=True).click()
        self.settle()

    def rows(self) -> str:
        return self.page.locator("tbody").inner_text()

    def row_count(self) -> int:
        return self.page.locator("tbody tr").count()

    def alert(self) -> str:
        alert = self.page.get_by_role("alert")
        return alert.inner_text() if alert.count() else ""


@contextlib.contextmanager
def browser_page():
    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError:
        _missing_browser("the playwright package isn't installed")
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Error as err:
            _missing_browser(
                f"Chromium didn't start (python -m playwright install chromium): {err}"
            )
        try:
            yield Page(browser.new_page())
        finally:
            browser.close()


def see_the_shell(app: Page, url: str, frontend: str) -> None:
    """The app comes up: every table has a screen in the navigation, the
    first one is drawn with its form, and the stylesheet is applied."""
    nav = NAV_NAMES[frontend].format
    app.page.goto(url)
    app.page.wait_for_selector("nav button")
    names = app.page.locator("nav button").all_inner_texts()
    assert len(names) == 7, names
    app.open_screen(nav("Customers"), "email")
    active = app.page.get_by_role("button", name=nav("Customers"), exact=True)
    background = active.evaluate("el => getComputedStyle(el).backgroundColor")
    assert background == "rgb(0, 0, 0)", f"Tailwind isn't applied: {background}"
    assert app.page.locator("h1").inner_text() == "customers"
    assert app.page.locator("#field-email").evaluate(
        "el => el.required && el.maxLength === 255"
    ), "the required field isn't marked"
    assert app.page.locator("#field-is_active").is_checked(), "checkbox default"


def use_the_screens(app: Page, url: str, frontend: str) -> None:
    """Uses the SHOP schema's screens (test_deterministic_migrations_e2e)
    against a backend with a new database."""
    nav = NAV_NAMES[frontend].format
    page = app.page
    see_the_shell(app, url, frontend)

    # ── Customers: the seed rows, a create, refusals ──
    page.wait_for_selector("tbody tr")
    text = app.rows()
    assert "a@x.io" in text and "b@x.io" in text, f"seed rows: {text}"
    assert "✓" in text and "—" in text and '{"tier":"basic"}' in text, text

    page.fill("#field-email", "c@x.io")
    page.fill("#field-name", "Cy")
    page.fill("#field-profile", '{"a": [1, 2]}')
    app.add()
    text = app.rows()
    assert app.row_count() == 3 and "c@x.io" in text and '{"a":[1,2]}' in text, (
        f"a created row appears: {app.alert()} {text}"
    )
    assert page.input_value("#field-email") == "", "the form is emptied after a create"
    assert page.input_value("#field-profile") == ""

    page.fill("#field-email", "c@x.io")
    app.add()
    assert "already has this email" in app.alert(), app.alert()
    page.fill("#field-email", "no-at-sign")
    app.add()
    assert "email has at" in app.alert(), app.alert()
    page.fill("#field-email", "d@x.io")
    page.fill("#field-profile", "{bad")
    app.add()
    assert "profile must be valid JSON" in app.alert(), app.alert()
    assert app.row_count() == 3, "bad JSON is caught before anything is sent"

    # ── Orders: foreign keys as choices, inputs typed by their field ──
    app.open_screen(nav("Orders"), "total")
    types = page.evaluate(
        "() => ['total', 'status', 'placed_at', 'ship_date']"
        ".map((key) => document.getElementById(`field-${key}`).type).join(',')"
    )
    assert types == "number,text,datetime-local,date", types
    page.wait_for_function(
        "() => document.querySelectorAll('#field-customer_id option').length > 1"
    )
    customers = [
        option.strip()
        for option in page.locator("#field-customer_id option").all_inner_texts()
    ]
    coupons = [
        option.strip()
        for option in page.locator("#field-coupon_id option").all_inner_texts()
    ]
    assert customers == ["Choose…", "a@x.io", "b@x.io", "c@x.io"], customers
    assert coupons == ["— none —", "WELCOME"], coupons
    page.select_option("#field-customer_id", label="c@x.io")
    page.select_option("#field-coupon_id", label="WELCOME")
    page.fill("#field-total", "12.50")
    page.fill("#field-ship_date", "2026-10-01")
    page.fill("#field-placed_at", "2026-10-01T10:30")
    app.add()
    text = app.rows()
    assert app.row_count() == 1 and not app.alert(), f"{app.alert()} {text}"
    assert "c@x.io" in text and "WELCOME" in text, f"foreign keys as labels: {text}"
    assert "12.5" in text and "draft" in text and "2026-10-01" in text, text
    page.select_option("#field-customer_id", label="a@x.io")
    page.fill("#field-total", "-1")
    app.add()
    assert "total non negative" in app.alert(), app.alert()

    # ── Delete, and what the database does with it ──
    app.open_screen(nav("Customers"), "email")
    page.wait_for_selector("tbody tr")
    page.locator("tbody tr", has_text="c@x.io").get_by_role(
        "button", name="Delete"
    ).click()
    app.settle()
    text = app.rows()
    assert app.row_count() == 2 and "c@x.io" not in text, f"delete: {text}"
    app.open_screen(nav("Orders"), "total")
    assert app.row_count() == 0, "the customer's orders went with it (cascade)"

    # ── A table whose name isn't an identifier ("Notes :)") ──
    app.open_screen(nav("Notes"), "due")
    page.fill("#field-due", "2026-02-03")
    page.fill("#field-title", "Hello")
    app.add()
    text = app.rows()
    assert "Hello" in text and "2026-02-03" in text, f"{app.alert()} {text}"

    assert app.errors == [], app.errors
