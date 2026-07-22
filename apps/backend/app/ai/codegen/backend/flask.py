# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Flask Backend Adapter
#  ai/codegen/backend/flask.py — Flask + Flask-SQLAlchemy, an app-
#  factory structure (Flask's own documented convention) rather than a
#  single flat app.py, so the generated project matches how real Flask
#  apps are normally organized.
# ═══════════════════════════════════════════════════════════════

from app.ai.codegen.manifests.requirements_txt import build_requirements_txt
from app.ai.codegen.types import BackendAdapter, FileResult, ModelCtx, RoutesCtx, WiringCtx
from app.ai.codegen_shared import GROQ_FILE_MAX_TOKENS, GeneratedFile, _slug, generate_text_validated


async def generate_model(ctx: ModelCtx) -> FileResult:
    table_name = ctx.table.get("name", "Item")

    prompt = f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Write ONE complete, real Flask-SQLAlchemy model file for the "{table_name}" table of this app.

App: {ctx.project_name}
{ctx.requirements_text}
Table purpose: {ctx.table.get('purpose', '')}
Fields: {', '.join(ctx.table.get('key_fields', []))}

Requirements:
- Real column types, constraints (nullable, unique, defaults) matching the fields above.
- Implement any validation, computed properties, or relationships implied by the key
  features / user stories above — not a bare column list.
- Import the shared db instance with `from app.extensions import db` and subclass `db.Model`
  (Flask-SQLAlchemy style — `db.Column`, `db.Integer`, etc., NOT plain SQLAlchemy imports).
- No placeholders or TODOs — every field and method must be fully implemented.

Return ONLY the raw Python code for this one file. No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(prompt, "python", GROQ_FILE_MAX_TOKENS)
    return GeneratedFile(
        path=f"backend/app/models/{_slug(table_name)}.py",
        language="python",
        content=content,
        description=f"Flask-SQLAlchemy model for {table_name}",
    ), issue


async def _rest_routes(ctx: RoutesCtx) -> list[FileResult]:
    endpoints_text = "\n".join(
        f"- {e.get('method')} {e.get('path')}: {e.get('purpose')}" for e in ctx.endpoints
    )
    model_imports = "\n".join(
        f"- backend/app/models/{_slug(t.get('name', 'item'))}.py defines the {t.get('name')} model"
        for t in ctx.tables
    )

    prompt = f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Write ONE complete, real Flask Blueprint file implementing every API endpoint below for this app.

App: {ctx.project_name}
{ctx.requirements_text}
Available models to import and use:
{model_imports}

API endpoints to implement:
{endpoints_text}

Requirements:
- Each endpoint MUST do real reads/writes against the models via `db.session` (import both with
  `from app.extensions import db` and the relevant model classes).
- Implement real validation and correct HTTP status codes for error cases (404 for missing
  records, 400/422 for bad input, etc.) — do not return hardcoded/fake JSON. Use `flask.jsonify`.
- Implement the actual behavior implied by the key features and user stories above.
- Define `bp = Blueprint('api', __name__)` and attach every route to `bp`, e.g.
  `@bp.route('/tasks', methods=['GET'])`.
- No placeholders or TODOs — every endpoint must be fully implemented.

Return ONLY the raw Python code for this one file. No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(prompt, "python", GROQ_FILE_MAX_TOKENS)
    return [(
        GeneratedFile(
            path="backend/app/routes/api.py",
            language="python",
            content=content,
            description="Flask Blueprint implementing all API endpoints against the real models",
        ),
        issue,
    )]


ROUTES_BUILDERS = {"rest": _rest_routes}


async def generate_routes(ctx: RoutesCtx) -> list[FileResult]:
    return await ROUTES_BUILDERS[ctx.api_style](ctx)


_EXTENSIONS_PY = """from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
"""


def _model_import_name(file: GeneratedFile) -> str:
    return file.path.removeprefix("backend/").removesuffix(".py").replace("/", ".")


def _build_init_py(model_files: list[GeneratedFile]) -> str:
    model_imports = "\n".join(f"        import {_model_import_name(f)}  # noqa: F401 — registers the model with db.metadata" for f in model_files)
    return f"""from flask import Flask
from flask_cors import CORS

from app.extensions import db


def create_app() -> Flask:
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    CORS(app)
    db.init_app(app)

    with app.app_context():
{model_imports if model_imports else "        pass"}
        db.create_all()

        from app.routes.api import bp as api_bp
        app.register_blueprint(api_bp, url_prefix='/api')

    return app
"""


_RUN_PY = """from app import create_app

app = create_app()

if __name__ == '__main__':
    app.run(debug=True)
"""


def manifest_files(ctx: WiringCtx) -> list[GeneratedFile]:
    content = build_requirements_txt([
        "flask==3.0.2",
        "flask-sqlalchemy==3.1.1",
        "flask-cors==4.0.0",
    ])
    return [GeneratedFile(path="backend/requirements.txt", language="text", content=content, description="Backend Python dependencies")]


def entry_point_files(ctx: WiringCtx) -> list[GeneratedFile]:
    return [
        GeneratedFile(path="backend/app/extensions.py", language="python", content=_EXTENSIONS_PY, description="Shared Flask-SQLAlchemy db instance"),
        GeneratedFile(path="backend/app/__init__.py", language="python", content=_build_init_py(ctx.model_files), description="Flask app factory"),
        GeneratedFile(path="backend/run.py", language="python", content=_RUN_PY, description="Flask entry point"),
    ]


def setup_commands(project_name: str) -> list[str]:
    return ["cd backend", "pip install -r requirements.txt", "python run.py"]


ADAPTER = BackendAdapter(
    key="flask",
    label="Flask",
    supported_languages=("python",),
    supported_api_styles=tuple(ROUTES_BUILDERS),
    generate_model=generate_model,
    generate_routes=generate_routes,
    manifest_files=manifest_files,
    entry_point_files=entry_point_files,
    setup_commands=setup_commands,
)
