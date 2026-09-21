# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Express Backend Adapter
#  ai/codegen/backend/express.py — Model/routes generation (Mongoose +
#  Express) moved verbatim from the old codegen.py's "vue_express"
#  branches. No behavior change from the pre-adapter version.
#
#  2026-09-21: added a real "graphql" api_style using Apollo Server v5.
#  Apollo removed its bundled @apollo/server/express4 middleware in v5 —
#  the current officially documented Express integration is the separate
#  @as-integrations/express4 package (confirmed via Apollo's own
#  migration docs and that package's README while writing this, not
#  guessed). graphql is pinned to the 16.x line, not latest — @apollo/
#  server 5's peerDependencies require ^16.11.0, and pulling graphql@17
#  here would violate that. server.js needs an async start() wrapper
#  (not top-level await) since this is a CommonJS project (`require`,
#  matching the REST variant), same reason mongoose.connect() below is
#  chained with .then()/.catch() rather than awaited at module scope.
#  _is_graphql() detects which style was actually generated from the
#  routes file's own path since WiringCtx carries no api_style field by
#  design (see its docstring).
# ═══════════════════════════════════════════════════════════════

from app.ai.codegen.manifests.package_json import build_package_json
from app.ai.codegen.types import BackendAdapter, FileResult, ModelCtx, RoutesCtx, WiringCtx
from app.ai.codegen_shared import GROQ_FILE_MAX_TOKENS, GeneratedFile, _pascal, _slug, generate_text_validated


async def generate_model(ctx: ModelCtx) -> FileResult:
    table_name = ctx.table.get("name", "Item")

    prompt = f"""Write ONE complete, real Mongoose schema/model file for the "{table_name}" collection of this app.

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

    content, issue = await generate_text_validated(
        prompt, "javascript", GROQ_FILE_MAX_TOKENS,
        user=ctx.user, db=ctx.db, context=ctx.shared_context(),
    )
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

    prompt = f"""Write ONE complete, real Express routes file implementing every API endpoint below for this app.

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

    content, issue = await generate_text_validated(
        prompt, "javascript", GROQ_FILE_MAX_TOKENS,
        user=ctx.user, db=ctx.db, context=ctx.shared_context(),
    )
    return [(
        GeneratedFile(
            path="backend/routes/api.js",
            language="javascript",
            content=content,
            description="Express routes implementing all API endpoints against the real models",
        ),
        issue,
    )]


async def _graphql_routes(ctx: RoutesCtx) -> list[FileResult]:
    model_imports = "\n".join(
        f"- backend/models/{_slug(t.get('name', 'item'))}.js defines the {_pascal(t.get('name', 'Item'))} model"
        for t in ctx.tables
    )
    operations_text = "\n".join(
        f"- (originally {e.get('method')} {e.get('path')}): {e.get('purpose')}"
        for e in ctx.endpoints
    )

    prompt = f"""Write ONE complete, real Apollo Server GraphQL schema file for this app, covering every capability below.

Available models to import and use (via `require`):
{model_imports}

Capabilities to expose as GraphQL fields (each was originally described as a REST endpoint — turn
each GET-shaped one into a Query field, and each POST/PUT/PATCH/DELETE-shaped one into a Mutation
field, choosing clear, idiomatic GraphQL field/argument names from its purpose):
{operations_text}

Requirements:
- Define the full SDL as a plain template-literal string named `typeDefs` — real `type`/`input`
  definitions matching each model's real fields, a `type Query {{ ... }}`, and (ONLY if at least
  one write capability exists) a `type Mutation {{ ... }}`.
- Define a plain `resolvers` object: `{{ Query: {{ ...async methods... }}, Mutation: {{ ... }} }}`
  (omit the `Mutation` key entirely if you declared no Mutation type in typeDefs). Each resolver
  has the shape `async (parent, args) => {{ ... }}`.
- Each resolver MUST do a real read/write against the Mongoose models using async/await — never
  return hardcoded/fake data. `throw new Error('...')` with a clear message for not-found/invalid
  cases (Apollo turns this into a real GraphQL error for the client).
- Implement the actual behavior implied by the key features and user stories above.
- End the file with `module.exports = {{ typeDefs, resolvers }};`.
- No placeholders or TODOs — every field/resolver must be fully implemented.

Return ONLY the raw JavaScript code for this one file. No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(
        prompt, "javascript", GROQ_FILE_MAX_TOKENS,
        user=ctx.user, db=ctx.db, context=ctx.shared_context(),
    )
    return [(
        GeneratedFile(
            path=_GRAPHQL_SCHEMA_PATH,
            language="javascript",
            content=content,
            description="Apollo Server GraphQL schema implementing every capability against the real models",
        ),
        issue,
    )]


ROUTES_BUILDERS = {"rest": _rest_routes, "graphql": _graphql_routes}


async def generate_routes(ctx: RoutesCtx) -> list[FileResult]:
    return await ROUTES_BUILDERS[ctx.api_style](ctx)


_GRAPHQL_SCHEMA_PATH = "backend/routes/schema.js"


def _is_graphql(ctx: WiringCtx) -> bool:
    return any(f.path == _GRAPHQL_SCHEMA_PATH for f in ctx.routes_files)


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


def _build_server_js_graphql(project_name: str) -> str:
    # No top-level await — this is a CommonJS file (`require`), so
    # server startup is wrapped in an async function instead. Mirrors
    # @as-integrations/express4's own documented example, adapted from
    # its ESM/TypeScript form to this project's CommonJS convention.
    return f"""const express = require('express');
const cors = require('cors');
require('dotenv').config();
const mongoose = require('mongoose');
const {{ ApolloServer }} = require('@apollo/server');
const {{ expressMiddleware }} = require('@as-integrations/express4');
const {{ typeDefs, resolvers }} = require('./routes/schema');

const app = express();
const PORT = process.env.PORT || 5000;
const MONGODB_URI = process.env.MONGODB_URI || 'mongodb://localhost:27017/app';

const apolloServer = new ApolloServer({{ typeDefs, resolvers }});

app.get('/', (req, res) => {{
  res.json({{ message: '{project_name} API is running' }});
}});

async function start() {{
  await apolloServer.start();

  app.use('/graphql', cors(), express.json(), expressMiddleware(apolloServer));

  await mongoose.connect(MONGODB_URI);
  app.listen(PORT, () => console.log(`Server running on port ${{PORT}}`));
}}

start().catch((err) => {{
  console.error('Failed to start server:', err);
  process.exit(1);
}});
"""


def manifest_files(ctx: WiringCtx) -> list[GeneratedFile]:
    from app.core.naming import slugify_app_name

    dependencies = {
        "express": "^4.18.2",
        "mongoose": "^8.1.1",
        "cors": "^2.8.5",
        "dotenv": "^16.4.1",
    }
    if _is_graphql(ctx):
        # Versions confirmed live on npm at the time this was written.
        # graphql is pinned to the 16.x line deliberately — @apollo/
        # server 5's peerDependencies require ^16.11.0; the current
        # 17.x major would violate that.
        dependencies["@apollo/server"] = "^5.5.1"
        dependencies["graphql"] = "^16.14.2"
        dependencies["@as-integrations/express4"] = "^1.1.2"
    content = build_package_json(
        name=slugify_app_name(ctx.project_name),
        scripts={"start": "node server.js"},
        dependencies=dependencies,
    )
    return [GeneratedFile(path="backend/package.json", language="json", content=content, description="Backend dependency manifest")]


def entry_point_files(ctx: WiringCtx) -> list[GeneratedFile]:
    builder = _build_server_js_graphql if _is_graphql(ctx) else _build_server_js
    return [GeneratedFile(path="backend/server.js", language="javascript", content=builder(ctx.project_name), description="Express entry point")]


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
