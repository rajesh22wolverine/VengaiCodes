"""Write a project's generated code + test files to a plain working directory
so pytest/Jest/Vitest can run against them directly (no installer template
needed here — this isn't building an installable app, just a runnable checkout).

Run from the repo root (where project_test_files.json was fetched to).

Also prepares frontend test-runner config: if the user's selected frontend
framework is Jest, the generated project's Vite setup has no Jest transform
pipeline by default, so this writes a minimal babel.config.cjs + jest.config.cjs
into project/frontend so `npx jest` can parse JSX/ESM. Vitest needs no such
config — it reads the project's own vite.config.js and is invoked with
--environment=jsdom on the command line instead.
"""
import json
import os

with open("project_test_files.json", "r", encoding="utf-8") as f:
    data = json.load(f)

codegen_files = data.get("codegen_files", [])
test_files = data.get("test_files", [])
tech_stack = data.get("tech_stack", {})
selected_frameworks = data.get("selected_frameworks", {})

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

frontend_framework = (selected_frameworks.get("frontend") or "").lower()
frontend_engine = "jest" if "jest" in frontend_framework else "vitest"

if has_frontend and frontend_engine == "jest":
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

print(
    f"Wrote {written} files into project/ "
    f"(backend={has_backend}, frontend={has_frontend}, frontend_engine={frontend_engine})"
)

github_output = os.environ.get("GITHUB_OUTPUT")
if github_output:
    with open(github_output, "a", encoding="utf-8") as gh_out:
        gh_out.write(f"has_backend={'true' if has_backend else 'false'}\n")
        gh_out.write(f"has_frontend={'true' if has_frontend else 'false'}\n")
        gh_out.write(f"frontend_engine={frontend_engine}\n")
