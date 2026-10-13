"""
End-to-end test of the deterministic (no-AI) frontends — nothing is mocked.
Each generated frontend is written to a folder, its packages are installed
with the real npm and it is built with its real bundler (`npm run build`:
Vite, or the Angular CLI, compiling every screen). Then the built site is
served, with the generated backend behind it, and used in a real browser
(generated_frontend_e2e.use_the_screens).

A syntax check can't see what the build does: a config file the bundler
refuses to load, a component the framework's compiler rejects, a stylesheet
nothing imports. The Svelte adapter had the first and the last of those
until this test existed. And a build can't see what the browser does: a
screen that never draws its rows, a form that sends the wrong thing.

The project lives in generated_backend_e2e.cache_dir, so the installed
packages are reused from one run to the next.

Needs `npm` on PATH (and the network, for the packages) to build, and
Playwright's Chromium to use the result. Without one, that test is skipped
— unless VENGAI_REQUIRE_TOOLCHAINS lists "node" / "browser", which the
backend CI job sets so a missing toolchain can't pass as a skip.
"""

import functools
import pathlib

import generated_backend_e2e as e2e
import generated_frontend_e2e as fe
import pytest
from test_deterministic_migrations_e2e import SHOP, FakeProject

from app.ai import codegen_deterministic as dc


@functools.cache
def _built(frontend: str) -> tuple[dict, pathlib.Path]:
    """(the generated project, the folder its build wrote the site to) —
    built once, for both tests below."""
    stack = {**e2e.stack("fastapi"), "frontend_framework": frontend}
    data = dc.build_deterministic_codegen_data(FakeProject(SHOP), stack)
    assert data["validation_warnings"] == []
    folder = pathlib.Path(e2e.cache_dir(f"frontend-{frontend}")) / "frontend"
    fe.clear_project(folder)
    fe.write_files(data, "frontend/", folder)
    return data, fe.install_and_build(folder)


@pytest.mark.parametrize("frontend", dc.DETERMINISTIC_FRONTENDS)
def test_generated_frontend_installs_and_builds(frontend):
    fe.npm()
    _, site = _built(frontend)
    scripts = fe.built_text(site, ".js")
    styles = fe.built_text(site, ".css")
    # Every table's screen is in the bundle …
    for table in ("customers", "coupons", "orders", "order_items", "notes"):
        assert f"/api/{table}" in scripts, table
    # … and so is the stylesheet, with the classes the screens use.
    for utility in (".whitespace-pre-line", ".bg-black", ".border-collapse"):
        assert utility in styles, utility


@pytest.mark.parametrize("frontend", dc.DETERMINISTIC_FRONTENDS)
def test_generated_frontend_works_in_a_browser(frontend, tmp_path):
    fe.npm()
    with fe.browser_page() as app:
        data, site = _built(frontend)
        # One origin for the site and its API, as behind a dev server's proxy.
        with fe.start_api(data, tmp_path) as api:
            with fe.Site(site, api=f"http://127.0.0.1:{api.port}") as web:
                fe.use_the_screens(app, web.url, frontend)
