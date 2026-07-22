# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Express Backend Adapter
#  ai/codegen/backend/express.py — Model/routes generation (Mongoose +
#  Express) moved verbatim from the old codegen.py's "vue_express"
#  branches. No behavior change from the pre-adapter version.
# ═══════════════════════════════════════════════════════════════

from app.ai.codegen.manifests.package_json import build_package_json
from app.ai.codegen.types import BackendAdapter, FileResult, ModelCtx, RoutesCtx, WiringCtx
from app.ai.codegen_shared import GROQ_FILE_MAX_TOKENS, GeneratedFile, _pascal, _slug, generate_text_validated


async def generate_model(ctx: ModelCtx) -> FileResult:
    table_name = ctx.table.get("name", "Item")

    prompt = f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Write ONE complete, real Mongoose schema/model file for the "{table_name}" collection of this app.

App: {ctx.project_name}
{ctx.requirements_text}
Collection purpose: {ctx.table.get('purpose', '')}
Fields: {', '.join(ctx.table.get('key_fields', []))}

Requirements:
- Real field types and validation (required, unique, defaults) matching the fields above.
- Implement any validation, virtuals, or relationships (via ref/populate) implied by the key
  features / user stories above — not a bare field list.
- Use Mongoose: `const mongoose = require('mongoose');`, define with `new mongoose.Schema({{...}})`,
  export via `module.exports = mongoose.model('{_pascal(table_name)}', schema);`.
- No placeholders or TODOs — every field and method must be fully implemented.

Return ONLY the raw JavaScript code for this one file. No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(prompt, "javascript", GROQ_FILE_MAX_TOKENS)
    return GeneratedFile(
        path=f"backend/models/{_slug(table_name)}.js",
        language="javascript",
        content=content,
        description=f"Mongoose model for {table_name}",
    ), issue


async def _rest_routes(ctx: RoutesCtx) -> list[FileResult]:
    endpoints_text = "\n".join(
        f"- {e.get('method')} {e.get('path')}: {e.get('purpose')}" for e in ctx.endpoints
    )
    model_imports = "\n".join(
        f"- backend/models/{_slug(t.get('name', 'item'))}.js defines the {_pascal(t.get('name', 'Item'))} model"
        for t in ctx.tables
    )

    prompt = f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Write ONE complete, real Express routes file implementing every API endpoint below for this app.

App: {ctx.project_name}
{ctx.requirements_text}
Available models to import and use (via `require`):
{model_imports}

API endpoints to implement:
{endpoints_text}

Requirements:
- Each endpoint MUST do real reads/writes against the Mongoose models using async/await.
- Implement real validation and correct HTTP status codes for error cases (404 for missing
  records, 400/422 for bad input, etc.) — do not return hardcoded/fake JSON.
- Implement the actual behavior implied by the key features and user stories above.
- Use `const express = require('express'); const router = express.Router();`, export via
  `module.exports = router;`.
- No placeholders or TODOs — every endpoint must be fully implemented.

Return ONLY the raw JavaScript code for this one file. No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(prompt, "javascript", GROQ_FILE_MAX_TOKENS)
    return [(
        GeneratedFile(
            path="backend/routes/api.js",
            language="javascript",
            content=content,
            description="Express routes implementing all API endpoints against the real models",
        ),
        issue,
    )]


ROUTES_BUILDERS = {"rest": _rest_routes}


async def generate_routes(ctx: RoutesCtx) -> list[FileResult]:
    return await ROUTES_BUILDERS[ctx.api_style](ctx)


def _build_server_js(project_name: str) -> str:
    return f"""const express = require('express');
const cors = require('cors');
require('dotenv').config();
const mongoose = require('mongoose');
const apiRouter = require('./routes/api');

const app = express();
app.use(cors());
app.use(express.json());

app.use('/api', apiRouter);

app.get('/', (req, res) => {{
  res.json({{ message: '{project_name} API is running' }});
}});

const PORT = process.env.PORT || 5000;
const MONGODB_URI = process.env.MONGODB_URI || 'mongodb://localhost:27017/app';

mongoose
  .connect(MONGODB_URI)
  .then(() => {{
    app.listen(PORT, () => console.log(`Server running on port ${{PORT}}`));
  }})
  .catch((err) => {{
    console.error('MongoDB connection error:', err);
    process.exit(1);
  }});
"""


def manifest_files(ctx: WiringCtx) -> list[GeneratedFile]:
    from app.core.naming import slugify_app_name

    content = build_package_json(
        name=slugify_app_name(ctx.project_name),
        scripts={"start": "node server.js"},
        dependencies={
            "express": "^4.18.2",
            "mongoose": "^8.1.1",
            "cors": "^2.8.5",
            "dotenv": "^16.4.1",
        },
    )
    return [GeneratedFile(path="backend/package.json", language="json", content=content, description="Backend dependency manifest")]


def entry_point_files(ctx: WiringCtx) -> list[GeneratedFile]:
    return [GeneratedFile(path="backend/server.js", language="javascript", content=_build_server_js(ctx.project_name), description="Express entry point")]


def setup_commands(project_name: str) -> list[str]:
    return ["cd backend", "npm install", "node server.js"]


ADAPTER = BackendAdapter(
    key="express",
    label="Express",
    supported_languages=("javascript",),
    supported_api_styles=tuple(ROUTES_BUILDERS),
    generate_model=generate_model,
    generate_routes=generate_routes,
    manifest_files=manifest_files,
    entry_point_files=entry_point_files,
    setup_commands=setup_commands,
)
