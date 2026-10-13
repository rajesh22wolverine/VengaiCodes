"""
End-to-end test of the deterministic (no-AI) frontends — nothing is mocked.
Each generated frontend is written to a folder, its packages are installed
with the real npm and it is built with its real bundler (`npm run build`:
Vite compiling every screen), which is what the installer workflows do with
it before wrapping it in a desktop or mobile app.

A syntax check can't see what this does: a config file the bundler refuses
to load, a component the framework's compiler rejects, a stylesheet nothing
imports. The Svelte adapter had the first and the last of those until this
test existed.

The project lives in generated_backend_e2e.cache_dir, so the installed
packages are reused from one run to the next.

Needs `npm` on PATH (and the network, for the packages). Without it these
tests are skipped — unless VENGAI_REQUIRE_TOOLCHAINS lists "node", which the
backend CI job sets so a missing toolchain can't pass as a skip.
"""

import pathlib
import shutil

import generated_backend_e2e as e2e
import pytest
from test_deterministic_migrations_e2e import SHOP, FakeProject

from app.ai import codegen_deterministic as dc

# What `npm install` leaves in the project, kept between runs.
INSTALLED = ("node_modules", "package-lock.json")


def _write_frontend(data: dict, root: pathlib.Path) -> str:
    """Replaces root/frontend with this generation's files — all of it but
    what npm installed there."""
    frontend = root / "frontend"
    if frontend.exists():
        for entry in frontend.iterdir():
            if entry.name in INSTALLED:
                continue
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()
    for f in data["codegen"]["files"]:
        if f["path"].startswith("frontend/"):
            target = root / f["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(f["content"].encode("utf-8"))
    return str(frontend)


@pytest.mark.parametrize("frontend", dc.DETERMINISTIC_FRONTENDS)
def test_generated_frontend_installs_and_builds(frontend):
    npm = e2e.toolchain("node", "npm")
    stack = {**e2e.stack("fastapi"), "frontend_framework": frontend}
    data = dc.build_deterministic_codegen_data(FakeProject(SHOP), stack)
    assert data["validation_warnings"] == []
    root = pathlib.Path(e2e.cache_dir(f"frontend-{frontend}"))
    folder = _write_frontend(data, root)

    e2e.run([npm, "install", "--no-audit", "--no-fund"], folder, timeout=900)
    e2e.run([npm, "run", "build"], folder, timeout=600)

    dist = root / "frontend" / "dist"
    assert (dist / "index.html").is_file()
    scripts = "".join(p.read_text(encoding="utf-8") for p in dist.rglob("*.js"))
    styles = "".join(p.read_text(encoding="utf-8") for p in dist.rglob("*.css"))
    # Every table's screen is in the bundle …
    for table in ("customers", "coupons", "orders", "order_items", "notes"):
        assert f"/api/{table}" in scripts, table
    # … and so is the stylesheet, with the classes the screens use.
    for utility in (".whitespace-pre-line", ".bg-black", ".border-collapse"):
        assert utility in styles, utility
