"""Extract a FastAPI project's backend/ files into backend_src/, and write
the sidecar entry point PyInstaller will freeze into a standalone binary.

Run from the repo root (same cwd as project_files.json), gated by the
workflow's "backend_framework == fastapi" check (see build-windows-
installer.yml / build-linux-installer.yml) — only FastAPI is wired up so
far. Flask and Django projects still lose their backend entirely at
packaging time; see the comment on ROUTES_BUILDERS-adjacent framework
adapters in apps/backend/app/ai/codegen/backend/ for why each needs its
own bundling approach (different entry-point convention, different dev
server) rather than sharing this one.

The generated backend/main.py only DEFINES a FastAPI `app` object — the
dev workflow is `uvicorn main:app --reload` (see fastapi.py's
setup_commands()), never `python main.py`, so there is no
`if __name__ == "__main__"` block to freeze directly. _sidecar_run.py
below IS that entry point: it imports the generated `app` and actually
serves it. SIDECAR_PORT here must match the port the Rust sidecar-spawn
code and the packaged frontend's fetch base URL agree on — see
templates/tauri-*/src-tauri/src/main.rs and inject_frontend_files.py's
API base URL rewrite.
"""
import json
import os

PROJECT_FILES_PATH = "project_files.json"
BACKEND_SRC_DIR = "backend_src"
SIDECAR_PORT = 47812

_SIDECAR_RUNNER = f"""# Written by extract_backend_files.py at packaging time — NOT part of
# the AI-generated project, and never sent to the AI. main.py only
# defines the FastAPI `app` object; this is what actually serves it once
# frozen by PyInstaller.
import uvicorn
from main import app

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port={SIDECAR_PORT})
"""

with open(PROJECT_FILES_PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

files = data.get("files", [])
written = 0

for file_entry in files:
    path = file_entry.get("path", "")
    content = file_entry.get("content", "")

    if not path.startswith("backend/"):
        continue

    relative_path = path[len("backend/"):]
    target_path = os.path.join(BACKEND_SRC_DIR, relative_path)
    os.makedirs(os.path.dirname(target_path) or ".", exist_ok=True)

    with open(target_path, "w", encoding="utf-8") as out:
        out.write(content)
    written += 1

if written == 0:
    print("No backend/ files found in project_files.json — nothing to bundle")
    raise SystemExit(1)

runner_path = os.path.join(BACKEND_SRC_DIR, "_sidecar_run.py")
with open(runner_path, "w", encoding="utf-8") as f:
    f.write(_SIDECAR_RUNNER)

print(f"Extracted {written} backend file(s) into {BACKEND_SRC_DIR}/, wrote _sidecar_run.py (port {SIDECAR_PORT})")
