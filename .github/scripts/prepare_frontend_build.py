"""Set the injected frontend up to build with its own framework's tools.

Run from the `build/` working directory, after inject_frontend_files.py and
merge_package_json.py, and before anything else edits package.json or
installs it.

The template in build/ is a React + Vite project, and injection keeps the
template's build configs rather than the generated project's (see
PROTECTED_FILES in inject_frontend_files.py). On its own that builds a
React frontend and nothing else: a Vue or Svelte project needs its own Vite
plugin, a plain HTML/JS one needs none, and an Angular project isn't built
by Vite at all. This makes build/ match the frontend that was injected:

  react        nothing to change.
  vue, svelte  the template's vite.config.ts loads that framework's plugin
               instead of React's; its other settings (Tauri's dev port,
               the output folder) stay.
  html_css_js  the same config with no plugin.
  angular      the generated project's own package.json and Tailwind
               config come back — the Angular CLI builds it, with the
               TypeScript release Angular asks for — plus the template's
               Tauri / Capacitor packages. `npm run build` becomes a
               production `ng build` writing to dist/, where the
               template's tauri.conf.json / capacitor.config.json look.

Then it checks that the file the build starts from exists, so a project
that can't build fails here, with a sentence, instead of inside a bundler.

The framework is project_files.json's "frontend_framework"; a response
without one (an older backend) is read from the files themselves.
"""
import json
import os
import re
import sys

PROJECT_FILES_PATH = "../project_files.json"
PACKAGE_JSON_PATH = "package.json"
VITE_CONFIG_PATH = "vite.config.ts"
ANGULAR_JSON_PATH = "angular.json"

# The two lines of the template's vite.config.ts that are about React.
REACT_IMPORT = 'import react from "@vitejs/plugin-react";\n'
REACT_PLUGINS = "plugins: [react()],"

# framework -> (import line, plugins line, packages it needs — at these
# versions when the generated package.json doesn't name its own).
VITE_PLUGINS = {
    "vue": (
        'import vue from "@vitejs/plugin-vue";\n',
        "plugins: [vue()],",
        {"dependencies": {"vue": "^3.4.15"}, "devDependencies": {"@vitejs/plugin-vue": "^5.0.3"}},
    ),
    "svelte": (
        'import { svelte } from "@sveltejs/vite-plugin-svelte";\n',
        "plugins: [svelte()],",
        {"devDependencies": {"svelte": "^4.2.9", "@sveltejs/vite-plugin-svelte": "^3.0.2"}},
    ),
    "html_css_js": ("", "plugins: [],", {}),
}
WEB_FRAMEWORKS = ("react", *VITE_PLUGINS, "angular")

# The template's own packages an Angular project still needs: the shell
# that wraps the built site.
SHELL_PACKAGE_PREFIXES = ("@tauri-apps/", "@capacitor/")


def fail(message: str) -> None:
    print(f"ERROR: {message}")
    sys.exit(1)


def read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_text(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)


def write_json(path: str, data: dict) -> None:
    write_text(path, json.dumps(data, indent=2) + "\n")


def generated_frontend(project: dict) -> dict[str, str]:
    """The generated frontend/ files: path inside build/ -> content."""
    return {
        entry["path"][len("frontend/") :]: entry.get("content", "")
        for entry in project.get("files", [])
        if entry.get("path", "").startswith("frontend/")
    }


def detect_framework(project: dict) -> str:
    named = (project.get("frontend_framework") or "").strip()
    if named:
        if named not in WEB_FRAMEWORKS:
            fail(
                f'this workflow wraps a web frontend, and the project\'s is "{named}" '
                f"(it builds: {', '.join(WEB_FRAMEWORKS)})."
            )
        return named
    paths = set(generated_frontend(project))
    if "angular.json" in paths:
        return "angular"
    if any(path.endswith(".svelte") for path in paths):
        return "svelte"
    if any(path.endswith(".vue") for path in paths):
        return "vue"
    if paths & {"src/main.jsx", "src/main.tsx"}:
        return "react"
    if "src/main.js" in paths:
        return "html_css_js"
    fail(
        "can't tell which framework the generated frontend uses: it has no angular.json, "
        "no .vue or .svelte files and no src/main.jsx, src/main.tsx or src/main.js."
    )


def use_vite_plugin(framework: str) -> None:
    import_line, plugins_line, packages = VITE_PLUGINS[framework]
    with open(VITE_CONFIG_PATH, "r", encoding="utf-8") as f:
        config = f.read().replace("\r\n", "\n")
    if REACT_IMPORT not in config or REACT_PLUGINS not in config:
        fail(
            f"{VITE_CONFIG_PATH} isn't the template's any more (no React plugin lines to "
            "replace) — update prepare_frontend_build.py with it."
        )
    config = config.replace(REACT_IMPORT, import_line).replace(REACT_PLUGINS, plugins_line)
    write_text(VITE_CONFIG_PATH, config)

    package = read_json(PACKAGE_JSON_PATH)
    for section, needed in packages.items():
        have = package.setdefault(section, {})
        for name, version in needed.items():
            # A project may list a runtime package under either section.
            if name not in package.get("dependencies", {}) and name not in package.get(
                "devDependencies", {}
            ):
                have[name] = version
    write_json(PACKAGE_JSON_PATH, package)
    print(f"{VITE_CONFIG_PATH}: {plugins_line}")


def check_vite_entry() -> None:
    if not os.path.isfile("index.html"):
        fail("the generated frontend has no index.html.")
    with open("index.html", "r", encoding="utf-8") as f:
        page = f.read()
    entries = re.findall(r'<script[^>]*\bsrc="([^"]+)"', page)
    local = [entry for entry in entries if not re.match(r"^[a-z]+:|^//", entry)]
    if not local:
        fail("index.html loads no script of its own, so there is nothing to build.")
    for entry in local:
        if not os.path.isfile(entry.lstrip("/")):
            fail(f"index.html loads {entry}, which the generated frontend doesn't have.")
    print(f"Entry point: {', '.join(local)}")


def prepare_angular(project: dict) -> None:
    generated = generated_frontend(project)
    for needed in ("package.json", ANGULAR_JSON_PATH, "src/main.ts", "src/index.html"):
        if needed not in generated:
            fail(f"the generated Angular frontend has no {needed}.")

    # package.json: the project's own, plus the shell's packages from the
    # template (merge_package_json.py has already put those in build/'s).
    merged = read_json(PACKAGE_JSON_PATH)
    package = json.loads(generated["package.json"])
    for section in ("dependencies", "devDependencies"):
        for name, version in merged.get(section, {}).items():
            if name.startswith(SHELL_PACKAGE_PREFIXES):
                package.setdefault(section, {})[name] = version
    package["name"] = merged.get("name") or package.get("name")
    package["version"] = merged.get("version") or package.get("version")
    scripts = package.setdefault("scripts", {})
    scripts["build"] = "ng build --configuration production"
    if "tauri" in merged.get("scripts", {}):
        scripts["tauri"] = merged["scripts"]["tauri"]
    write_json(PACKAGE_JSON_PATH, package)

    # The configs injection kept from the template are React + Vite ones.
    for name in ("tailwind.config.js", "postcss.config.js"):
        if name in generated:
            write_text(name, generated[name])
    for leftover in (VITE_CONFIG_PATH, "index.html"):
        if leftover not in generated and os.path.exists(leftover):
            os.remove(leftover)

    workspace = read_json(ANGULAR_JSON_PATH)
    for name, app in workspace.get("projects", {}).items():
        build = app.get("architect", {}).get("build")
        if not build:
            fail(f'angular.json\'s project "{name}" has no build target.')
        # Straight into dist/, not dist/<project>/browser/.
        build.setdefault("options", {})["outputPath"] = {"base": "dist", "browser": ""}
        production = build.setdefault("configurations", {}).setdefault("production", {})
        # No critical-CSS inlining: it loads the stylesheet through an inline
        # onload handler, which the packaged window's Content-Security-Policy
        # (script-src 'self') never runs — the app would come up unstyled.
        # And no font inlining, which fetches from the network at build time.
        production["optimization"] = {
            "scripts": True,
            "styles": {"minify": True, "inlineCritical": False},
            "fonts": False,
        }
    write_json(ANGULAR_JSON_PATH, workspace)
    print(f"package.json: {scripts['build']}; {ANGULAR_JSON_PATH}: output to dist/")


def main() -> None:
    project = read_json(PROJECT_FILES_PATH)
    framework = detect_framework(project)
    print(f"Frontend framework: {framework}")
    if framework == "angular":
        prepare_angular(project)
    else:
        if framework != "react":
            use_vite_plugin(framework)
        check_vite_entry()


if __name__ == "__main__":
    main()
