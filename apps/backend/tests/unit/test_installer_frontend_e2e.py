"""
End-to-end test of what the installer workflows do with a generated
frontend (build-windows-installer.yml, build-linux-installer.yml,
build-android-installer.yml) — for every frontend the no-AI generator
writes, not only React.

It runs the workflows' own steps with their own scripts (.github/scripts)
on their own templates (templates/): copy the template, inject the
generated files, merge package.json, set the build up for the frontend's
framework, apply the shell's settings, `npm install`, `npm run build`. What
comes out is the folder Tauri or Capacitor wraps. Wrapping it (cargo, the
Android SDK) is the same whatever built it, and isn't run here.

Then the built site is used in a browser the way the shell shows it:

- Tauri (desktop): served under the Content-Security-Policy from
  tauri.conf.json, with the backend at the address the sidecar listens on
  and the frontend's calls rewritten to it — so a policy that blocks the
  app's own requests, or a call the rewrite missed, fails here.
- Capacitor (Android): the app has no backend of its own in the APK, so
  this checks that it comes up — every screen in the navigation, the form
  drawn, the stylesheet applied.

tauri-windows isn't built separately: a test below holds the files its
frontend build reads to tauri-linux's.

Toolchains: `node` to build, `browser` to use the result (see
generated_frontend_e2e).
"""

import functools
import json
import pathlib
import shutil
import subprocess
import sys

import generated_backend_e2e as e2e
import generated_frontend_e2e as fe
import pytest
from test_deterministic_migrations_e2e import SHOP, FakeProject

from app.ai import codegen_deterministic as dc

REPO = pathlib.Path(__file__).resolve().parents[4]
SCRIPTS = REPO / ".github" / "scripts"
TEMPLATES = REPO / "templates"

# Where the packaged FastAPI sidecar listens (extract_backend_files.py), and
# so where the frontend's calls are rewritten to.
SIDECAR = "http://127.0.0.1:47812"


def _script(name: str, cwd: pathlib.Path, **env: str) -> str:
    return e2e.run(
        [sys.executable, str(SCRIPTS / name)], str(cwd), env={**fe.npm_env(), **env}
    )


def _project_files(data: dict, frontend: str | None) -> dict:
    """What GET /packaging/{id}/files answers the workflow with."""
    return {
        "project_name": "Shop's (Demo",
        "files": data["codegen"]["files"],
        "native_capabilities": data["native_capabilities"],
        "frontend_framework": frontend,
        "backend_framework": "fastapi",
    }


def _generated(frontend: str) -> dict:
    stack = {**e2e.stack("fastapi"), "frontend_framework": frontend}
    data = dc.build_deterministic_codegen_data(FakeProject(SHOP), stack)
    assert data["validation_warnings"] == []
    return data


def _prepare(shell: str, work: pathlib.Path, project_files: dict) -> pathlib.Path:
    """The workflow's steps up to (not including) `npm install`; returns
    build/."""
    build = work / "build"
    fe.clear_project(build)
    (work / "project_files.json").write_text(
        json.dumps(project_files), encoding="utf-8"
    )
    # "Copy the template into the build directory" (a local checkout may have
    # build output in the template; the runner's never does).
    shutil.copytree(
        TEMPLATES / shell,
        build,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("target", "node_modules", "dist"),
    )
    _script("inject_frontend_files.py", work)
    _script(
        "merge_package_json.py",
        build,
        TEMPLATE_PACKAGE_JSON_PATH=str(TEMPLATES / shell / "package.json"),
    )
    _script("prepare_frontend_build.py", build)
    if shell.startswith("tauri"):
        _script("update_tauri_config.py", build)
        _script("apply_tauri_native_capabilities.py", build)
        # install_backend_sidecar.py's part that touches the frontend (the
        # rest installs the compiled backend, which isn't built here).
        e2e.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.path.insert(0, sys.argv[1]); "
                "import install_backend_sidecar as sidecar; "
                "sidecar.rewrite_frontend_api_base(sys.argv[2])",
                str(SCRIPTS),
                SIDECAR,
            ],
            str(build),
        )
    else:
        _script("apply_native_capabilities.py", build)
        _script("update_capacitor_config.py", build)
    return build


@functools.cache
def _packaged(shell: str, frontend: str) -> tuple[dict, pathlib.Path, pathlib.Path]:
    """(the generated project, build/, the built site) — built once per
    shell and frontend."""
    data = _generated(frontend)
    work = pathlib.Path(e2e.cache_dir(f"installer-{shell}-{frontend}"))
    build = _prepare(shell, work, _project_files(data, frontend))
    site = fe.install_and_build(build)
    # Where the shell's config says the site is.
    assert site == build / "dist", site
    return data, build, site


FRONTENDS = dc.DETERMINISTIC_FRONTENDS


@pytest.mark.parametrize("frontend", FRONTENDS)
def test_desktop_installer_builds_the_frontend_and_it_works(frontend, tmp_path):
    fe.npm()
    data, build, site = _packaged("tauri-linux", frontend)
    scripts = fe.built_text(site, ".js")
    styles = fe.built_text(site, ".css")
    for table in ("customers", "orders", "order_items", "notes"):
        assert f"{SIDECAR}/api/{table}" in scripts, (
            f"{table} isn't called at the sidecar"
        )
    for utility in (".whitespace-pre-line", ".bg-black", ".border-collapse"):
        assert utility in styles, utility

    conf = json.loads((build / "src-tauri" / "tauri.conf.json").read_text("utf-8"))
    assert conf["build"]["distDir"] == "../dist"
    policy = conf["tauri"]["security"]["csp"]
    with fe.browser_page() as app:
        with fe.start_api(data, tmp_path, port=int(SIDECAR.rsplit(":", 1)[1])):
            with fe.Site(site, headers={"Content-Security-Policy": policy}) as web:
                fe.use_the_screens(app, web.url, frontend)


@pytest.mark.parametrize("frontend", FRONTENDS)
def test_android_installer_builds_the_frontend_and_it_comes_up(frontend):
    fe.npm()
    _, build, site = _packaged("capacitor-android", frontend)
    styles = fe.built_text(site, ".css")
    for utility in (".whitespace-pre-line", ".bg-black", ".border-collapse"):
        assert utility in styles, utility
    capacitor = json.loads((build / "capacitor.config.json").read_text("utf-8"))
    assert capacitor["webDir"] == "dist"
    with fe.browser_page() as app:
        with fe.Site(site) as web:
            fe.see_the_shell(app, web.url, frontend)


# ───────────────────────────────────────────────
#  No toolchain needed below
# ───────────────────────────────────────────────
def _normalised(path: pathlib.Path) -> str:
    return "\n".join(path.read_text("utf-8").split())


@pytest.mark.parametrize(
    "name",
    [
        "vite.config.ts",
        "tailwind.config.js",
        "postcss.config.js",
        "package.json",
        "index.html",
    ],
)
def test_the_windows_template_builds_its_frontend_like_the_linux_one(name):
    """So the Tauri build above stands for both desktop workflows."""
    windows = TEMPLATES / "tauri-windows" / name
    assert _normalised(windows) == _normalised(TEMPLATES / "tauri-linux" / name)


def test_both_desktop_templates_let_the_window_call_the_sidecar():
    for shell in ("tauri-linux", "tauri-windows"):
        conf = json.loads(
            (TEMPLATES / shell / "src-tauri" / "tauri.conf.json").read_text("utf-8")
        )
        connect = next(
            part
            for part in conf["tauri"]["security"]["csp"].split(";")
            if part.strip().startswith("connect-src")
        )
        # The rewrite points the frontend at 127.0.0.1, which "localhost" in
        # a policy doesn't cover.
        assert "http://127.0.0.1:*" in connect.split(), (shell, connect)


@pytest.mark.parametrize("shell", ["tauri-linux", "capacitor-android"])
@pytest.mark.parametrize("frontend", FRONTENDS)
def test_the_build_is_set_up_for_each_framework(shell, frontend, tmp_path):
    """The steps before `npm install`, which need no toolchain — and with no
    "frontend_framework" in the answer (an older backend), so the framework
    is read from the files."""
    build = _prepare(shell, tmp_path, _project_files(_generated(frontend), None))
    package = json.loads((build / "package.json").read_text("utf-8"))
    packages = {**package["dependencies"], **package.get("devDependencies", {})}
    shell_package = (
        "@tauri-apps/api" if shell.startswith("tauri") else "@capacitor/core"
    )
    assert shell_package in packages

    if frontend == "angular":
        assert package["scripts"]["build"] == "ng build --configuration production"
        assert "type" not in package, "an Angular project is a CommonJS package"
        assert packages["typescript"] == "~5.5.2", "the release Angular 18 accepts"
        assert not (build / "vite.config.ts").exists()
        workspace = json.loads((build / "angular.json").read_text("utf-8"))
        (app,) = workspace["projects"].values()
        options = app["architect"]["build"]
        assert options["options"]["outputPath"] == {"base": "dist", "browser": ""}
        styles = options["configurations"]["production"]["optimization"]["styles"]
        assert styles["inlineCritical"] is False
        return

    config = (build / "vite.config.ts").read_text("utf-8")
    plugin = {
        "react": "plugins: [react()],",
        "vue": "plugins: [vue()],",
        "svelte": "plugins: [svelte()],",
        "html_css_js": "plugins: [],",
    }[frontend]
    assert plugin in config
    assert ("plugin-react" in config) == (frontend == "react")
    needed = {
        "react": "@vitejs/plugin-react",
        "vue": "@vitejs/plugin-vue",
        "svelte": "@sveltejs/vite-plugin-svelte",
        "html_css_js": "vite",
    }[frontend]
    assert needed in packages
    # The template's settings for its shell are still there.
    assert 'outDir: "dist"' in config
    assert ("strictPort: true" in config) == shell.startswith("tauri")


def test_a_frontend_the_workflow_cannot_wrap_is_refused_with_a_sentence(tmp_path):
    data = _generated("react")
    for answer, sentence in (
        (
            {**_project_files(data, "flutter")},
            'this workflow wraps a web frontend, and the project\'s is "flutter"',
        ),
        (
            {**_project_files(data, None), "files": []},
            "can't tell which framework the generated frontend uses",
        ),
    ):
        work = tmp_path / str(len(sentence))
        build = work / "build"
        build.mkdir(parents=True)
        (work / "project_files.json").write_text(json.dumps(answer), encoding="utf-8")
        shutil.copytree(TEMPLATES / "tauri-linux" / "src", build / "src")
        for name in ("package.json", "vite.config.ts", "index.html"):
            shutil.copy(TEMPLATES / "tauri-linux" / name, build / name)
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "prepare_frontend_build.py")],
            cwd=build,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 1 and sentence in proc.stdout, proc.stdout
