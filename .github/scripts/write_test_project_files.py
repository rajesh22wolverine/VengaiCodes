"""Write a project's generated code + test files to a plain working directory
so each framework's real test runner can run against them directly (no
installer template needed here — this isn't building an installable app,
just a runnable checkout).

Run from the repo root (where project_test_files.json was fetched to).

Also prepares any test-runner config the generated project doesn't ship with
by default, keyed off `selected_recipe_keys` (from api/v1/testing.py, via
app.ai.testing_recipes) rather than guessing from a free-text framework
label:
  - Jest needs a minimal babel.config.cjs + jest.config.cjs since the
    generated project is Vite-based and has no Jest transform pipeline by
    default.
  - Angular's Karma runner needs a karma.conf.js (a ChromeHeadless launcher
    with --no-sandbox, required in GitHub Actions' root-user containers,
    plus a JUnit reporter so merge_test_results.py can read its output the
    same way it reads Spring Boot/Laravel/Gradle's JUnit-XML).
  - Every other recipe (Vitest, pytest, RSpec, PHPUnit, JUnit/Maven,
    dotnet test, cargo test, go test, flutter test, Gradle unit tests)
    needs no extra CI-time file — the codegen adapter's own project
    manifest already has what its native tool needs.
"""
import json
import os

with open("project_test_files.json", "r", encoding="utf-8") as f:
    data = json.load(f)

codegen_files = data.get("codegen_files", [])
test_files = data.get("test_files", [])
recipe_keys = data.get("selected_recipe_keys", {}) or {}

all_files = codegen_files + test_files
written = 0
for file_entry in all_files:
    path = file_entry.get("path", "")
    content = file_entry.get("content", "")
    if not path:
        continue
    target_path = os.path.join("project", path)
    os.makedirs(os.path.dirname(target_path) or ".", exist_ok=True)
    with open(target_path, "w", encoding="utf-8") as out:
        out.write(content)
    written += 1

has_backend = any(f.get("path", "").startswith("backend/") for f in all_files)
has_frontend = any(f.get("path", "").startswith("frontend/") for f in all_files)

backend_recipe = recipe_keys.get("backend", "pytest")
frontend_recipe = recipe_keys.get("frontend", "jest_rtl")

if has_frontend and frontend_recipe in ("jest_rtl", "jest_nestjs"):
    os.makedirs("project/frontend", exist_ok=True)
    with open("project/frontend/babel.config.cjs", "w", encoding="utf-8") as f:
        f.write(
            'module.exports = {\n'
            '  presets: ["@babel/preset-env", ["@babel/preset-react", { runtime: "automatic" }]],\n'
            '};\n'
        )
    with open("project/frontend/jest.config.cjs", "w", encoding="utf-8") as f:
        f.write(
            'module.exports = {\n'
            '  testEnvironment: "jsdom",\n'
            '  setupFilesAfterEnv: ["@testing-library/jest-dom"],\n'
            '};\n'
        )

if has_frontend and frontend_recipe == "karma_jasmine":
    os.makedirs("project/frontend", exist_ok=True)
    with open("project/frontend/karma.conf.js", "w", encoding="utf-8") as f:
        f.write(
            "module.exports = function (config) {\n"
            "  config.set({\n"
            "    basePath: '',\n"
            "    frameworks: ['jasmine', '@angular-devkit/build-angular'],\n"
            "    plugins: [\n"
            "      require('karma-jasmine'),\n"
            "      require('karma-chrome-launcher'),\n"
            "      require('karma-junit-reporter'),\n"
            "      require('@angular-devkit/build-angular/plugins/karma'),\n"
            "    ],\n"
            "    client: { jasmine: {}, clearContext: false },\n"
            "    reporters: ['progress', 'junit'],\n"
            "    junitReporter: {\n"
            "      outputDir: '../../',\n"
            "      outputFile: 'frontend-results.xml',\n"
            "      useBrowserName: false,\n"
            "    },\n"
            "    browsers: ['ChromeHeadlessNoSandbox'],\n"
            "    customLaunchers: {\n"
            "      ChromeHeadlessNoSandbox: {\n"
            "        base: 'ChromeHeadless',\n"
            "        flags: ['--no-sandbox', '--disable-gpu'],\n"
            "      },\n"
            "    },\n"
            "    singleRun: true,\n"
            "    restartOnFileChange: false,\n"
            "  });\n"
            "};\n"
        )

print(
    f"Wrote {written} files into project/ "
    f"(backend={has_backend}/{backend_recipe}, frontend={has_frontend}/{frontend_recipe})"
)

github_output = os.environ.get("GITHUB_OUTPUT")
if github_output:
    with open(github_output, "a", encoding="utf-8") as gh_out:
        gh_out.write(f"has_backend={'true' if has_backend else 'false'}\n")
        gh_out.write(f"has_frontend={'true' if has_frontend else 'false'}\n")
        gh_out.write(f"backend_recipe={backend_recipe}\n")
        gh_out.write(f"frontend_recipe={frontend_recipe}\n")
