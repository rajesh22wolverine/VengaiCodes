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
#
#  2026-09-21: added a real "graphql" api_style using Graphene-Django
#  (graphene-django, mounted via graphene_django.views.GraphQLView at
#  /graphql — no trailing slash, see _root_urls_py()'s own comment for
#  why — both confirmed against the graphene-django project's own
#  current README while writing this, not guessed). GraphQL replaces
#  the REST urls.py/views.py entirely rather than sitting alongside it —
#  api_style is mutually exclusive, same as every other backend.
#  _is_graphql() detects which style was actually generated from the
#  routes file's own path since WiringCtx carries no api_style field by
#  design (see its docstring).
#
#  2026-09-26: migrations mode (the deterministic generator only) —
#  settings read DATABASE_URL, DRF answers JSON only and routes database
#  constraint errors through api/errors.py, and the models package
#  registers the `like` lookup the table rules use. Also: uvicorn is now
#  in requirements.txt in both modes — the desktop sidecar runner serves
#  config.asgi with it, and without it every packaged Django app died at
#  launch ("No module named 'uvicorn'").
# ═══════════════════════════════════════════════════════════════

import json
import re

from app.ai import db_schema
from app.ai.codegen.manifests.requirements_txt import build_requirements_txt
from app.ai.codegen.types import (
    BackendAdapter,
    FileResult,
    ModelCtx,
    RoutesCtx,
    WiringCtx,
)
from app.ai.codegen_shared import (
    GROQ_FILE_MAX_TOKENS,
    GeneratedFile,
    _pascal,
    _slug,
    generate_text_validated,
)

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

    prompt = f"""Write ONE complete, real Django model file for the "{table_name}" table of this app.

Table purpose: {ctx.table.get("purpose", "")}
{db_schema.describe_table_for_prompt(ctx.table, ctx.all_tables or [ctx.table])}

Requirements:
- Real field types and constraints (null, blank, unique, default) matching the fields above.
- Implement any validation, computed properties, or relationships implied by the key
  features / user stories above — not a bare field list.
- Use Django's ORM: `from django.db import models` and `class {_pascal(table_name)}(models.Model):`.
- No placeholders or TODOs — every field and method must be fully implemented.

Return ONLY the raw Python code for this one file. No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(
        prompt,
        "python",
        GROQ_FILE_MAX_TOKENS,
        user=ctx.user,
        db=ctx.db,
        context=ctx.shared_context(),
    )
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

    prompt = f"""Write ONE complete, real Django REST Framework views file implementing every API endpoint below for this app.

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

    content, issue = await generate_text_validated(
        prompt,
        "python",
        GROQ_FILE_MAX_TOKENS,
        user=ctx.user,
        db=ctx.db,
        context=ctx.shared_context(),
    )
    return [
        (
            GeneratedFile(
                path="backend/api/views.py",
                language="python",
                content=content,
                description="DRF views implementing all API endpoints against the real models",
            ),
            issue,
        )
    ]


async def _graphql_routes(ctx: RoutesCtx) -> list[FileResult]:
    model_imports = "\n".join(
        f"- backend/api/models/{_slug(t.get('name', 'item'))}.py defines the {t.get('name')} model "
        f"(import via `from api.models.{_slug(t.get('name', 'item'))} import {_pascal(t.get('name', 'Item'))}`)"
        for t in ctx.tables
    )
    operations_text = "\n".join(
        f"- (originally {e.get('method')} {e.get('path')}): {e.get('purpose')}"
        for e in ctx.endpoints
    )

    prompt = f"""Write ONE complete, real Graphene-Django GraphQL schema file for this app, covering every capability below.

Available models to import and use:
{model_imports}

Capabilities to expose as GraphQL fields (each was originally described as a REST endpoint — turn
each GET-shaped one into a Query field, and each POST/PUT/PATCH/DELETE-shaped one into a Mutation
field, choosing clear, idiomatic GraphQL field/argument names from its purpose):
{operations_text}

Requirements:
- `import graphene` and `from graphene_django import DjangoObjectType`.
- Define one real `class XType(DjangoObjectType):` per model above, with `class Meta: model = X`
  (the real Django model class), for every model listed.
- Define `class Query(graphene.ObjectType):` with one field + `resolve_x(self, info, **kwargs)`
  method per read capability, doing a real Django ORM query (`X.objects...`) — never hardcoded/
  fake data. ONLY if at least one write capability exists, also define
  `class Mutation(graphene.ObjectType):` composing one `graphene.Mutation` subclass per write
  capability (each with its own nested `class Arguments:`, a `mutate(self, info, **kwargs)`
  classmethod doing a real Django ORM write, and returning the mutation instance).
- Raise `Exception("...")` with a clear message for not-found/invalid-input cases.
- Implement the actual behavior implied by the key features and user stories above.
- End the file with `schema = graphene.Schema(query=Query, mutation=Mutation)` if you defined a
  Mutation class, otherwise `schema = graphene.Schema(query=Query)`.
- No placeholders or TODOs — every field/resolver must be fully implemented.

Return ONLY the raw Python code for this one file. No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(
        prompt,
        "python",
        GROQ_FILE_MAX_TOKENS,
        user=ctx.user,
        db=ctx.db,
        context=ctx.shared_context(),
    )
    return [
        (
            GeneratedFile(
                path=_GRAPHQL_SCHEMA_PATH,
                language="python",
                content=content,
                description="Graphene-Django GraphQL schema implementing every capability against the real models",
            ),
            issue,
        )
    ]


ROUTES_BUILDERS = {"rest": _rest_routes, "graphql": _graphql_routes}


async def generate_routes(ctx: RoutesCtx) -> list[FileResult]:
    return await ROUTES_BUILDERS[ctx.api_style](ctx)


_GRAPHQL_SCHEMA_PATH = "backend/api/schema.py"


def _is_graphql(ctx: WiringCtx) -> bool:
    return any(f.path == _GRAPHQL_SCHEMA_PATH for f in ctx.routes_files)


def _build_api_urls_py(endpoints: list[dict]) -> str:
    entries = (
        "\n".join(
            f"    path('{_django_path(e.get('path', '/'))}', views.{_view_name(e.get('method', 'GET'), e.get('path', '/'))}),"
            for e in endpoints
        )
        or "    # no endpoints defined"
    )
    return f"""from django.urls import path

from . import views

urlpatterns = [
{entries}
]
"""


def _build_models_init_py(
    model_files: list[GeneratedFile], lookups: bool = False
) -> str:
    if not model_files:
        return ""
    lines = (
        [
            "from api import lookups  # noqa: F401 — registers the `like` lookup the rules use"
        ]
        if lookups
        else []
    )
    for f in model_files:
        stem = f.path.split("/")[-1].removesuffix(".py")
        lines.append(f"from .{stem} import {_pascal(stem)}  # noqa: F401")
    return "\n".join(lines) + "\n"


_APPS_PY = """from django.apps import AppConfig


class ApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'api'
"""


def _settings_py(project_name: str, graphql: bool) -> str:
    installed_apps = [
        "'django.contrib.contenttypes'",
        "'django.contrib.staticfiles'",
        "'corsheaders'",
    ]
    installed_apps += ["'graphene_django'"] if graphql else ["'rest_framework'"]
    installed_apps.append("'api'")
    installed_apps_block = ",\n    ".join(installed_apps)
    graphene_setting = (
        "\nGRAPHENE = {\n    'SCHEMA': 'api.schema.schema',\n}\n" if graphql else ""
    )

    return f"""from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = 'django-insecure-dev-key-change-in-production'
DEBUG = True
ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    {installed_apps_block},
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
]

CORS_ALLOW_ALL_ORIGINS = True

ROOT_URLCONF = '{_SETTINGS_PACKAGE}.urls'
{graphene_setting}

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


# Migrations mode (deterministic generator only).
def _settings_py_migrations(project_name: str) -> str:
    return f"""import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

# Set DJANGO_SECRET_KEY (and DJANGO_DEBUG=0) anywhere this isn't a laptop.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "django-insecure-dev-key-change-in-production")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "corsheaders",
    "rest_framework",
    "api",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
]

CORS_ALLOW_ALL_ORIGINS = True

ROOT_URLCONF = "{_SETTINGS_PACKAGE}.urls"
WSGI_APPLICATION = "{_SETTINGS_PACKAGE}.wsgi.application"

# SQLite (backend/db.sqlite3) unless DATABASE_URL is set, e.g.
# postgres://user:pass@host:5432/db (after pip install "psycopg[binary]").
if os.environ.get("DATABASE_URL"):
    DATABASES = {{"default": dj_database_url.parse(os.environ["DATABASE_URL"])}}
else:
    DATABASES = {{
        "default": {{
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }}
    }}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "UTC"

REST_FRAMEWORK = {{
    # A JSON API with no sign-in yet: no session/basic auth, so no
    # django.contrib.auth tables are needed.
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    # Decimals as numbers, like the other generated backends.
    "COERCE_DECIMAL_TO_STRING": False,
    "EXCEPTION_HANDLER": "api.errors.exception_handler",
}}

# "{project_name}" — generated by VengaiCode
"""


def _root_urls_py_migrations(project_name: str) -> str:
    message = json.dumps(f"{project_name} API is running")
    return f"""from django.http import JsonResponse
from django.urls import include, path


def root(request):
    return JsonResponse({{"message": {message}}})


urlpatterns = [
    path("", root),
    path("api/", include("api.urls")),
]
"""


def _root_urls_py(graphql: bool) -> str:
    if graphql:
        # No trailing slash: every frontend adapter's GRAPHQL_CALLING_
        # CONVENTION prompt (codegen_shared.py) uniformly tells the AI
        # to POST to "/graphql" across every backend, and
        # install_backend_sidecar.py's frontend URL rewrite for the
        # Windows/Linux desktop sidecar matches that same literal path.
        # A trailing-slash route here would 404 on that exact request,
        # and Django's own APPEND_SLASH redirect doesn't save it: a 301
        # redirect on a POST is converted to a bodiless GET by the Fetch
        # spec, silently dropping the GraphQL query. Matching the
        # convention here is simpler than special-casing every caller.
        return """from django.urls import path
from graphene_django.views import GraphQLView

urlpatterns = [
    path('graphql', GraphQLView.as_view(graphiql=True)),
]
"""
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


def manifest_files(ctx: WiringCtx, migrations: bool = False) -> list[GeneratedFile]:
    graphql = _is_graphql(ctx)
    packages = [
        "django==5.0.2",
        "django-cors-headers==4.3.1",
        # The desktop app's backend sidecar serves config.asgi with uvicorn.
        "uvicorn==0.27.1",
    ]
    if graphql:
        # Version confirmed live on PyPI at the time this was written.
        packages.append("graphene-django==3.2.3")
    else:
        packages.append("djangorestframework==3.14.0")
    if migrations:
        packages.append("dj-database-url==2.1.0")
    content = build_requirements_txt(packages)
    return [
        GeneratedFile(
            path="backend/requirements.txt",
            language="text",
            content=content,
            description="Backend Python dependencies",
        )
    ]


def entry_point_files(ctx: WiringCtx, migrations: bool = False) -> list[GeneratedFile]:
    graphql = _is_graphql(ctx)
    files = [
        GeneratedFile(
            path="backend/manage.py",
            language="python",
            content=_manage_py(),
            description="Django management entry point",
        ),
        GeneratedFile(
            path=f"backend/{_SETTINGS_PACKAGE}/__init__.py",
            language="python",
            content="",
            description="Settings package marker",
        ),
        GeneratedFile(
            path=f"backend/{_SETTINGS_PACKAGE}/settings.py",
            language="python",
            content=(
                _settings_py_migrations(ctx.project_name)
                if migrations
                else _settings_py(ctx.project_name, graphql)
            ),
            description="Django settings",
        ),
        GeneratedFile(
            path=f"backend/{_SETTINGS_PACKAGE}/urls.py",
            language="python",
            content=(
                _root_urls_py_migrations(ctx.project_name)
                if migrations
                else _root_urls_py(graphql)
            ),
            description="Root URL config",
        ),
        GeneratedFile(
            path=f"backend/{_SETTINGS_PACKAGE}/wsgi.py",
            language="python",
            content=_wsgi_py(),
            description="WSGI entry point",
        ),
        GeneratedFile(
            path=f"backend/{_SETTINGS_PACKAGE}/asgi.py",
            language="python",
            content=_asgi_py(),
            description="ASGI entry point",
        ),
        GeneratedFile(
            path="backend/api/__init__.py",
            language="python",
            content="",
            description="API app package marker",
        ),
        GeneratedFile(
            path="backend/api/apps.py",
            language="python",
            content=_APPS_PY,
            description="API app config",
        ),
        GeneratedFile(
            path="backend/api/models/__init__.py",
            language="python",
            content=_build_models_init_py(ctx.model_files, lookups=migrations),
            description="Aggregates every generated model",
        ),
    ]
    # REST needs a deterministic urls.py wiring each view to its exact
    # dictated name; GraphQL doesn't — graphene_django.schema.py's single
    # /graphql endpoint IS the routing, no per-capability URL entries.
    # (The deterministic generator writes its own api/urls.py.)
    if ctx.endpoints and not graphql and not migrations:
        files.append(
            GeneratedFile(
                path="backend/api/urls.py",
                language="python",
                content=_build_api_urls_py(ctx.endpoints),
                description="URL routing, deterministically wired to the exact view names dictated to the AI",
            )
        )
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
