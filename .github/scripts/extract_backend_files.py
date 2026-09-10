"""Extract a project's backend/ files into backend_src/, and — for
frameworks whose entry point doesn't already serve requests on its own —
write the sidecar runner PyInstaller/cargo/go will actually execute.

Run from the repo root (same cwd as project_files.json), gated by the
workflow's backend_framework check (see build-windows-installer.yml /
build-linux-installer.yml). Wired up so far: fastapi, flask, django
(bundled via PyInstaller), actix, axum (compiled directly — main.rs
already IS a real server), gin (compiled directly — main.go already IS a
real server). Node backends (express, nestjs) and the remaining
JVM/.NET/Ruby/PHP backends still lose their backend entirely at
packaging time — each needs its own runtime-bundling story this hasn't
been built for yet.

SIDECAR_PORT is fastapi/flask's own choice (their generated code has no
fixed port of its own — Flask's app.run(debug=True) defaults to 5000,
which _sidecar_run.py overrides). actix/axum/gin are different: their
generated main.rs/main.go already hardcodes 127.0.0.1:8080 with no
override mechanism, so install_backend_sidecar.py's frontend URL rewrite
must target THAT port for those three, not this one — see SIDECAR_PORTS
there.
"""
import json
import os

PROJECT_FILES_PATH = "project_files.json"
BACKEND_SRC_DIR = "backend_src"
SIDECAR_PORT = 47812

_FASTAPI_RUNNER = f"""# Written by extract_backend_files.py at packaging time — NOT part of
# the AI-generated project, and never sent to the AI. main.py only
# defines the FastAPI `app` object; this is what actually serves it once
# frozen by PyInstaller.
import uvicorn
from main import app

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port={SIDECAR_PORT})
"""

# Flask's own backend/run.py already has `if __name__ == '__main__':
# app.run(debug=True)` (see codegen/backend/flask.py) — debug=True enables
# the Werkzeug reloader, which double-spawns the process (harmless for a
# dev server, but the second copy fails to rebind the same port when
# frozen as a sidecar, and debug=True's traceback pages are not something
# to ship). This wrapper reuses the SAME create_app() factory Flask's own
# run.py calls, just without the reloader and on the fixed sidecar port.
_FLASK_RUNNER = f"""# Written by extract_backend_files.py at packaging time — NOT part of
# the AI-generated project. Reuses run.py's own create_app(), just
# without the Werkzeug reloader (which double-spawns and breaks a frozen
# single-process sidecar) and on the fixed sidecar port.
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port={SIDECAR_PORT}, debug=False, use_reloader=False)
"""

# Django's BASE_DIR is `Path(__file__).resolve().parent.parent` (see
# codegen/backend/django.py's settings.py) — inside a PyInstaller onefile
# binary, __file__ resolves into the temp extraction folder that gets
# wiped and recreated on every launch, so db.sqlite3 would silently reset
# every time the app opens. os.getcwd() is used to relocate it to a
# stable path instead — the Rust sidecar spawn code (see
# templates/*/src-tauri/src/main.rs) pins the sidecar's working directory
# to the app's own data dir before spawning ANY framework's sidecar, so
# this is the same fix FastAPI/Actix/Axum/Gin already get for free from
# their own CWD-relative "./app.db" paths, applied explicitly here since
# Django's path is __file__-relative instead of CWD-relative. Settings
# is mutated after django.setup() but before any request opens a
# connection. Also runs migrate on every
# startup — cheap and a no-op once the schema exists, and there is no
# other point at which a packaged app could run it.
_DJANGO_RUNNER = f"""# Written by extract_backend_files.py at packaging time — NOT part of
# the AI-generated project. config.asgi already builds the real ASGI
# `application` — this just relocates the SQLite file out of the
# PyInstaller temp extraction dir (which is wiped every launch) and runs
# migrations before serving.
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.conf import settings as django_settings

data_dir = os.getcwd()
django_settings.DATABASES["default"]["NAME"] = os.path.join(data_dir, "db.sqlite3")

from django.core.management import execute_from_command_line

execute_from_command_line(["manage.py", "migrate", "--noinput"])

import uvicorn
from config.asgi import application

if __name__ == "__main__":
    uvicorn.run(application, host="127.0.0.1", port={SIDECAR_PORT})
"""

# Only frameworks whose own entry point doesn't already serve requests
# need a written runner — actix/axum/main.rs and gin/main.go already call
# HttpServer::run()/r.Run() themselves.
_RUNNERS = {
    "fastapi": _FASTAPI_RUNNER,
    "flask": _FLASK_RUNNER,
    "django": _DJANGO_RUNNER,
}

with open(PROJECT_FILES_PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

framework = data.get("backend_framework")
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

runner = _RUNNERS.get(framework)
if runner:
    runner_path = os.path.join(BACKEND_SRC_DIR, "_sidecar_run.py")
    with open(runner_path, "w", encoding="utf-8") as f:
        f.write(runner)
    print(f"Extracted {written} backend file(s) into {BACKEND_SRC_DIR}/, wrote _sidecar_run.py for {framework} (port {SIDECAR_PORT})")
else:
    print(f"Extracted {written} backend file(s) into {BACKEND_SRC_DIR}/ ({framework} serves itself — no runner needed)")
