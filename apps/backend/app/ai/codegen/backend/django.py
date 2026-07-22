# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Django Backend Adapter
#  ai/codegen/backend/django.py — Django + Django REST Framework.
#  urls.py is built deterministically (not AI-authored) from the same
#  structured `endpoints` list already available, using a fixed view-
#  naming convention dictated to the AI in the views prompt — this
#  avoids needing to parse the AI's output to find function names.
#
#  HONEST STATUS: settings.py/manage.py/wsgi.py/asgi.py below mirror
#  `django-admin startproject`'s real, long-stable boilerplate from
#  documented knowledge — no live Django install was available in this
#  environment to run the equivalent of the Angular CLI verification.
# ═══════════════════════════════════════════════════════════════

import re

from app.ai.codegen.manifests.requirements_txt import build_requirements_txt
from app.ai.codegen.types import BackendAdapter, FileResult, ModelCtx, RoutesCtx, WiringCtx
from app.ai.codegen_shared import GROQ_FILE_MAX_TOKENS, GeneratedFile, _pascal, _slug, generate_text_validated

_SETTINGS_PACKAGE = "config"


def _view_name(method: str, path: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", path.strip("/")).strip("_").lower() or "root"
    return f"{method.lower()}_{slug}"


def _django_path(path: str) -> str:
    """'/tasks/{id}' -> 'tasks/<str:id>/' (Django's path converter syntax)."""
    converted = re.sub(r"\{(\w+)\}", r"<str:\1>", path.strip("/"))
    return f"{converted}/" if converted else ""


async def generate_model(ctx: ModelCtx) -> FileResult:
    table_name = ctx.table.get("name", "Item")

    prompt = f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Write ONE complete, real Django model file for the "{table_name}" table of this app.

App: {ctx.project_name}
{ctx.requirements_text}
Table purpose: {ctx.table.get('purpose', '')}
Fields: {', '.join(ctx.table.get('key_fields', []))}

Requirements:
- Real field types and constraints (null, blank, unique, default) matching the fields above.
- Implement any validation, computed properties, or relationships implied by the key
  features / user stories above — not a bare field list.
- Use Django's ORM: `from django.db import models` and `class {_pascal(table_name)}(models.Model):`.
- No placeholders or TODOs — every field and method must be fully implemented.

Return ONLY the raw Python code for this one file. No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(prompt, "python", GROQ_FILE_MAX_TOKENS)
    return GeneratedFile(
        path=f"backend/api/models/{_slug(table_name)}.py",
        language="python",
        content=content,
        description=f"Django model for {table_name}",
    ), issue


async def _rest_routes(ctx: RoutesCtx) -> list[FileResult]:
    endpoints_text = "\n".join(
        f"- {e.get('method')} {e.get('path')}: {e.get('purpose')} "
        f"(implement this as a view function named `{_view_name(e.get('method', 'GET'), e.get('path', '/'))}`)"
        for e in ctx.endpoints
    )
    model_imports = "\n".join(
        f"- backend/api/models/{_slug(t.get('name', 'item'))}.py defines the {t.get('name')} model "
        f"(import via `from api.models.{_slug(t.get('name', 'item'))} import {_pascal(t.get('name', 'Item'))}`)"
        for t in ctx.tables
    )

    prompt = f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Write ONE complete, real Django REST Framework views file implementing every API endpoint below for this app.

App: {ctx.project_name}
{ctx.requirements_text}
Available models to import and use:
{model_imports}

API endpoints to implement (use the EXACT function name given for each — urls.py references
these exact names):
{endpoints_text}

Requirements:
- Use Django REST Framework function-based views: `from rest_framework.decorators import api_view`,
  `from rest_framework.response import Response`, `from rest_framework import status`.
- Each view function MUST be decorated `@api_view(['GET'])` (or the correct HTTP method) and do
  real reads/writes against the Django models above — do not return hardcoded/fake JSON.
- Any path parameter (e.g. from a path like "/tasks/{{id}}") arrives as an extra function argument
  with that exact name, e.g. `def get_tasks_id(request, id): ...`.
- Implement real validation and correct HTTP status codes for error cases (404 for missing
  records, 400/422 for bad input, etc.) using `status.HTTP_*` constants.
- Implement the actual behavior implied by the key features and user stories above.
- No placeholders or TODOs — every endpoint must be fully implemented.

Return ONLY the raw Python code for this one file. No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(prompt, "python", GROQ_FILE_MAX_TOKENS)
    return [(
        GeneratedFile(
            path="backend/api/views.py",
            language="python",
            content=content,
            description="DRF views implementing all API endpoints against the real models",
        ),
        issue,
    )]


ROUTES_BUILDERS = {"rest": _rest_routes}


async def generate_routes(ctx: RoutesCtx) -> list[FileResult]:
    return await ROUTES_BUILDERS[ctx.api_style](ctx)


def _build_api_urls_py(endpoints: list[dict]) -> str:
    entries = "\n".join(
        f"    path('{_django_path(e.get('path', '/'))}', views.{_view_name(e.get('method', 'GET'), e.get('path', '/'))}),"
        for e in endpoints
    ) or "    # no endpoints defined"
    return f"""from django.urls import path

from . import views

urlpatterns = [
{entries}
]
"""


def _build_models_init_py(model_files: list[GeneratedFile]) -> str:
    if not model_files:
        return ""
    lines = []
    for f in model_files:
        stem = f.path.split("/")[-1].removesuffix(".py")
        lines.append(f"from .{stem} import {_pascal(stem)}  # noqa: F401")
    return "\n".join(lines) + "\n"


_APPS_PY = """from django.apps import AppConfig


class ApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'api'
"""


def _settings_py(project_name: str) -> str:
    return f"""from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = 'django-insecure-dev-key-change-in-production'
DEBUG = True
ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
    'api',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
]

CORS_ALLOW_ALL_ORIGINS = True

ROOT_URLCONF = '{_SETTINGS_PACKAGE}.urls'

TEMPLATES = [
    {{
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {{'context_processors': []}},
    }},
]

WSGI_APPLICATION = '{_SETTINGS_PACKAGE}.wsgi.application'

DATABASES = {{
    'default': {{
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }}
}}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
STATIC_URL = 'static/'

# "{project_name}" — generated by VengaiCode
"""


def _root_urls_py() -> str:
    return """from django.urls import include, path

urlpatterns = [
    path('api/', include('api.urls')),
]
"""


def _manage_py() -> str:
    return f"""#!/usr/bin/env python
import os
import sys


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', '{_SETTINGS_PACKAGE}.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
"""


def _wsgi_py() -> str:
    return f"""import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', '{_SETTINGS_PACKAGE}.settings')

application = get_wsgi_application()
"""


def _asgi_py() -> str:
    return f"""import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', '{_SETTINGS_PACKAGE}.settings')

application = get_asgi_application()
"""


def manifest_files(ctx: WiringCtx) -> list[GeneratedFile]:
    content = build_requirements_txt([
        "django==5.0.2",
        "djangorestframework==3.14.0",
        "django-cors-headers==4.3.1",
    ])
    return [GeneratedFile(path="backend/requirements.txt", language="text", content=content, description="Backend Python dependencies")]


def entry_point_files(ctx: WiringCtx) -> list[GeneratedFile]:
    files = [
        GeneratedFile(path="backend/manage.py", language="python", content=_manage_py(), description="Django management entry point"),
        GeneratedFile(path=f"backend/{_SETTINGS_PACKAGE}/__init__.py", language="python", content="", description="Settings package marker"),
        GeneratedFile(path=f"backend/{_SETTINGS_PACKAGE}/settings.py", language="python", content=_settings_py(ctx.project_name), description="Django settings"),
        GeneratedFile(path=f"backend/{_SETTINGS_PACKAGE}/urls.py", language="python", content=_root_urls_py(), description="Root URL config"),
        GeneratedFile(path=f"backend/{_SETTINGS_PACKAGE}/wsgi.py", language="python", content=_wsgi_py(), description="WSGI entry point"),
        GeneratedFile(path=f"backend/{_SETTINGS_PACKAGE}/asgi.py", language="python", content=_asgi_py(), description="ASGI entry point"),
        GeneratedFile(path="backend/api/__init__.py", language="python", content="", description="API app package marker"),
        GeneratedFile(path="backend/api/apps.py", language="python", content=_APPS_PY, description="API app config"),
        GeneratedFile(path="backend/api/models/__init__.py", language="python", content=_build_models_init_py(ctx.model_files), description="Aggregates every generated model"),
    ]
    if ctx.endpoints:
        files.append(GeneratedFile(
            path="backend/api/urls.py",
            language="python",
            content=_build_api_urls_py(ctx.endpoints),
            description="URL routing, deterministically wired to the exact view names dictated to the AI",
        ))
    return files


def setup_commands(project_name: str) -> list[str]:
    return [
        "cd backend",
        "pip install -r requirements.txt",
        "python manage.py migrate",
        "python manage.py runserver",
    ]


ADAPTER = BackendAdapter(
    key="django",
    label="Django",
    supported_languages=("python",),
    supported_api_styles=tuple(ROUTES_BUILDERS),
    generate_model=generate_model,
    generate_routes=generate_routes,
    manifest_files=manifest_files,
    entry_point_files=entry_point_files,
    setup_commands=setup_commands,
)
