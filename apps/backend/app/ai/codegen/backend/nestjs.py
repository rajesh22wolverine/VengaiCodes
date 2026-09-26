# ═══════════════════════════════════════════════════════════════
#  VengaiCode — NestJS Backend Adapter
#  ai/codegen/backend/nestjs.py — TypeORM entities (sqlite, zero-config
#  like the FastAPI adapter) + a NestJS controller. First backend to
#  support gRPC: the .proto skeleton is built DETERMINISTICALLY from
#  the same structured `tables`/`endpoints` data (one `message` per
#  table, one `rpc` per endpoint) — protobuf has no pure-Python real-
#  parser to catch a hand-authored syntax error, so minimizing AI-
#  freehanded .proto text is worth the extra code here. Only the
#  service *implementation* body is one AI call, in the same call as
#  the .proto so method names/types can't drift between the two.
#
#  2026-09-26: migrations mode (the deterministic generator only) — one
#  feature module per table (codegen_nestjs writes them), versioned
#  TypeORM migrations run at startup instead of synchronize, a global
#  /api prefix, ValidationPipe and database-error filter, and
#  src/database.ts shared by the app and the TypeORM CLI.
# ═══════════════════════════════════════════════════════════════

import json

from app.ai import db_schema
from app.ai.codegen.manifests.package_json import build_package_json
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


async def generate_model(ctx: ModelCtx) -> FileResult:
    table_name = ctx.table.get("name", "Item")
    class_name = _pascal(table_name)

    prompt = f"""Write ONE complete, real TypeORM entity file for the "{table_name}" table of this app.

Table purpose: {ctx.table.get("purpose", "")}
{db_schema.describe_table_for_prompt(ctx.table, ctx.all_tables or [ctx.table])}

Requirements:
- Real column types, constraints (nullable, unique, default) matching the fields above.
- Implement any validation, computed properties, or relationships implied by the key
  features / user stories above — not a bare column list.
- Use TypeORM decorators: `import {{ Entity, PrimaryGeneratedColumn, Column }} from 'typeorm';`,
  `@Entity() export class {class_name} {{ @PrimaryGeneratedColumn() id: number; ... }}`.
- No placeholders or TODOs — every field must be fully implemented.

Return ONLY the raw TypeScript code for this one file. No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(
        prompt,
        "typescript",
        GROQ_FILE_MAX_TOKENS,
        user=ctx.user,
        db=ctx.db,
        context=ctx.shared_context(),
    )
    return GeneratedFile(
        path=f"backend/src/{_slug(table_name)}/{_slug(table_name)}.entity.ts",
        language="typescript",
        content=content,
        description=f"TypeORM entity for {table_name}",
    ), issue


async def _rest_routes(ctx: RoutesCtx) -> list[FileResult]:
    endpoints_text = "\n".join(
        f"- {e.get('method')} {e.get('path')}: {e.get('purpose')}"
        for e in ctx.endpoints
    )
    entity_imports = "\n".join(
        f"- backend/src/{_slug(t.get('name', 'item'))}/{_slug(t.get('name', 'item'))}.entity.ts defines the {_pascal(t.get('name', 'Item'))} entity"
        for t in ctx.tables
    )

    prompt = f"""Write ONE complete, real NestJS controller file implementing every API endpoint below for this app.

Available entities to import and use:
{entity_imports}

API endpoints to implement:
{endpoints_text}

Requirements:
- Class name: `ApiController` (exported) — this EXACT name is required, other generated files
  import it by this name.
- Each endpoint MUST do real reads/writes DIRECTLY against the TypeORM entities via
  `@InjectRepository(Entity) private repo: Repository<Entity>` injected in the controller's own
  constructor (`import {{ InjectRepository }} from '@nestjs/typeorm'; import {{ Repository }} from
  'typeorm';`) — do NOT create or reference a separate service/provider class or file, this
  controller must be fully self-contained.
- Use `@Controller('api')` and NestJS route decorators (`@Get`, `@Post`, `@Put`, `@Delete`,
  `@Param`, `@Body`) matching the endpoints above.
- Implement real validation and correct HTTP status codes/exceptions for error cases (use
  `NotFoundException`, `BadRequestException` from '@nestjs/common' — do not return hardcoded/fake
  JSON).
- Implement the actual behavior implied by the key features and user stories above.
- No placeholders or TODOs — every endpoint must be fully implemented.

Return ONLY the raw TypeScript code for this one file (imports + the @Controller class). No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(
        prompt,
        "typescript",
        GROQ_FILE_MAX_TOKENS,
        user=ctx.user,
        db=ctx.db,
        context=ctx.shared_context(),
    )
    return [
        (
            GeneratedFile(
                path="backend/src/api/api.controller.ts",
                language="typescript",
                content=content,
                description="NestJS controller implementing all API endpoints against the real entities",
            ),
            issue,
        )
    ]


def _proto_message_for_table(table: dict) -> str:
    fields = table.get("key_fields", []) or []
    field_lines = "\n".join(f"  string {f} = {i + 2};" for i, f in enumerate(fields))
    return f"message {_pascal(table.get('name', 'Item'))} {{\n  string id = 1;\n{field_lines}\n}}"


def _proto_rpc_for_endpoint(e: dict) -> tuple[str, str]:
    """Returns (rpc line, request/response message pair) for one endpoint."""
    method_name = (
        _pascal(f"{e.get('method', 'get')}_{e.get('path', '/').strip('/')}") or "Call"
    )
    return (
        f"  rpc {method_name} ({method_name}Request) returns ({method_name}Response);",
        method_name,
    )


async def _grpc_routes(ctx: RoutesCtx) -> list[FileResult]:
    """
    Returns [.proto file, service-impl stub] from ONE AI call — gRPC
    needs exact signature parity between the two, a much tighter
    coupling than REST/GraphQL's looser file relationships, so
    generating both together (with the .proto skeleton handed in
    pre-built) avoids the AI inventing mismatched method names.
    """
    messages = (
        "\n\n".join(_proto_message_for_table(t) for t in ctx.tables)
        or "message Empty {}"
    )
    rpc_lines = []
    request_response_messages = []
    for e in ctx.endpoints:
        rpc_line, method_name = _proto_rpc_for_endpoint(e)
        rpc_lines.append(rpc_line)
        request_response_messages.append(
            f"message {method_name}Request {{\n  string payload = 1;\n}}"
        )
        request_response_messages.append(
            f"message {method_name}Response {{\n  string result = 1;\n}}"
        )

    proto_skeleton = f"""syntax = "proto3";

package api;

service ApiService {{
{chr(10).join(rpc_lines)}
}}

{messages}

{chr(10).join(request_response_messages)}
"""

    endpoints_text = "\n".join(
        f"- {e.get('method')} {e.get('path')}: {e.get('purpose')}"
        for e in ctx.endpoints
    )

    prompt = f"""A .proto file (below) has ALREADY been generated deterministically for this app's gRPC service — do not change its message/rpc names. Write the NestJS gRPC service IMPLEMENTATION file that implements every rpc method declared in it.

Already-generated .proto contract (implement EXACTLY these rpc method names, request/response types):
{proto_skeleton}

The endpoints these rpc methods correspond to:
{endpoints_text}

Requirements:
- Use `@GrpcMethod('ApiService', 'MethodName')` decorators from '@nestjs/microservices' — one
  per rpc method in the .proto above, with the EXACT method name from the .proto.
- Implement the actual behavior implied by the key features and user stories above (real
  data handling, not a stub that just echoes the request).
- No placeholders or TODOs — every rpc method must be fully implemented.

Return ONLY the raw TypeScript code for this one file (imports + a service class with one
@GrpcMethod per rpc). No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(
        prompt,
        "typescript",
        GROQ_FILE_MAX_TOKENS,
        user=ctx.user,
        db=ctx.db,
        context=ctx.shared_context(),
    )
    return [
        (
            GeneratedFile(
                path="backend/src/api/api.proto",
                language="text",
                content=proto_skeleton,
                description="gRPC service contract (deterministic)",
            ),
            None,
        ),
        (
            GeneratedFile(
                path="backend/src/api/api.grpc.service.ts",
                language="typescript",
                content=content,
                description="gRPC service implementation",
            ),
            issue,
        ),
    ]


ROUTES_BUILDERS = {"rest": _rest_routes, "grpc": _grpc_routes}


async def generate_routes(ctx: RoutesCtx) -> list[FileResult]:
    return await ROUTES_BUILDERS[ctx.api_style](ctx)


def _entity_import_name(file: GeneratedFile) -> str:
    stem = file.path.split("/")[-1].removesuffix(".entity.ts")
    return _pascal(stem)


def _build_app_module_ts(model_files: list[GeneratedFile]) -> str:
    entity_names = [_entity_import_name(f) for f in model_files]
    imports = "\n".join(
        f"import {{ {name} }} from './{f.path.split('/')[-2]}/{f.path.split('/')[-1].removesuffix('.ts')}';"
        for name, f in zip(entity_names, model_files)
    )
    entities_array = ", ".join(entity_names)

    return f"""import {{ Module }} from '@nestjs/common';
import {{ TypeOrmModule }} from '@nestjs/typeorm';
import {{ ApiController }} from './api/api.controller';
{imports}

@Module({{
  imports: [
    TypeOrmModule.forRoot({{
      type: 'sqlite',
      database: 'app.db',
      entities: [{entities_array}],
      synchronize: true,
    }}),
    TypeOrmModule.forFeature([{entities_array}]),
  ],
  controllers: [ApiController],
}})
export class AppModule {{}}
"""


_MAIN_TS = """import { NestFactory } from '@nestjs/core';
import { AppModule } from './app.module';

async function bootstrap() {
  const app = await NestFactory.create(AppModule);
  app.enableCors();
  await app.listen(3000);
}
bootstrap();
"""

_TSCONFIG_JSON = """{
  "compilerOptions": {
    "module": "commonjs",
    "target": "ES2021",
    "experimentalDecorators": true,
    "emitDecoratorMetadata": true,
    "esModuleInterop": true,
    "sourceMap": true,
    "outDir": "./dist",
    "strict": false,
    "skipLibCheck": true
  }
}
"""


_TSCONFIG_JSON_MIGRATIONS = """{
  "compilerOptions": {
    "module": "commonjs",
    "target": "ES2021",
    "experimentalDecorators": true,
    "emitDecoratorMetadata": true,
    "esModuleInterop": true,
    "sourceMap": true,
    "outDir": "./dist",
    "rootDir": "./src",
    "strict": false,
    "skipLibCheck": true
  },
  "include": ["src"]
}
"""

# One place for the database settings: the app (AppModule) and the TypeORM
# CLI (src/data-source.ts) both read it, so they can't point at two databases.
_DATABASE_TS = """import { join } from 'path';
import { DataSourceOptions } from 'typeorm';

// SQLite, in the folder the server runs from (set DATABASE_PATH to move it).
export const databaseOptions: DataSourceOptions = {
  type: 'sqlite',
  database: process.env.DATABASE_PATH || 'app.db',
  entities: [join(__dirname, '**', '*.entity.{ts,js}')],
  // The versioned migrations own the schema (never synchronize): pending
  // ones run every time the app starts, so an existing database is
  // upgraded in place, rows kept, whenever the tables change.
  migrations: [join(__dirname, 'migrations', '*.{ts,js}')],
  migrationsRun: true,
  synchronize: false,
};
"""

_DATA_SOURCE_TS = """// For the TypeORM CLI (npm run migration:show / migration:run / schema:check).
import 'reflect-metadata';
import { DataSource } from 'typeorm';
import { databaseOptions } from './database';

export default new DataSource(databaseOptions);
"""


def _main_ts_migrations(project_name: str) -> str:
    message = json.dumps(f"{project_name} API is running")
    return f"""import 'reflect-metadata';
import {{ ValidationPipe }} from '@nestjs/common';
import {{ NestFactory }} from '@nestjs/core';
import {{ AppModule }} from './app.module';
import {{ DatabaseErrorFilter }} from './common/database-errors';

async function bootstrap() {{
  const app = await NestFactory.create(AppModule);
  app.enableCors();
  // Every route under /api — the paths the generated screens call.
  app.setGlobalPrefix('api');
  // Unknown fields are dropped; a wrong type or a missing required field is a 400.
  app.useGlobalPipes(new ValidationPipe({{ whitelist: true, transform: true }}));
  app.useGlobalFilters(new DatabaseErrorFilter());
  app.getHttpAdapter().get('/', (_request, response) => response.json({{ message: {message} }}));
  await app.listen(Number(process.env.PORT) || 3000);
}}
bootstrap();
"""


def _feature_modules(model_files: list[GeneratedFile]) -> list[tuple[str, str]]:
    """(module class, import path) per entity file src/<slug>/<slug>.entity.ts."""
    out = []
    for f in model_files:
        stem = f.path.split("/")[-1].removesuffix(".entity.ts")
        out.append((f"{_pascal(stem)}Module", f"./{stem}/{stem}.module"))
    return out


def _app_module_ts_migrations(model_files: list[GeneratedFile]) -> str:
    modules = _feature_modules(model_files)
    imports = "\n".join(f"import {{ {name} }} from '{path}';" for name, path in modules)
    names = "".join(f"    {name},\n" for name, _ in modules)
    return f"""import {{ Module }} from '@nestjs/common';
import {{ TypeOrmModule }} from '@nestjs/typeorm';
import {{ databaseOptions }} from './database';
{imports}

@Module({{
  imports: [
    TypeOrmModule.forRoot(databaseOptions),
{names}  ],
}})
export class AppModule {{}}
"""


def manifest_files(ctx: WiringCtx, migrations: bool = False) -> list[GeneratedFile]:
    from app.core.naming import slugify_app_name

    if migrations:
        cli = "typeorm-ts-node-commonjs"
        content = build_package_json(
            name=slugify_app_name(ctx.project_name),
            scripts={
                "start": "ts-node src/main.ts",
                "build": "tsc",
                "start:prod": "node dist/main.js",
                "migration:show": f"{cli} migration:show -d src/data-source.ts",
                "migration:run": f"{cli} migration:run -d src/data-source.ts",
                "migration:revert": f"{cli} migration:revert -d src/data-source.ts",
                "schema:check": f"{cli} schema:log -d src/data-source.ts",
            },
            dependencies={
                "@nestjs/common": "^10.3.0",
                "@nestjs/core": "^10.3.0",
                "@nestjs/platform-express": "^10.3.0",
                "@nestjs/typeorm": "^10.0.1",
                "typeorm": "^0.3.20",
                "sqlite3": "^5.1.7",
                "reflect-metadata": "^0.2.1",
                "rxjs": "^7.8.1",
                "class-validator": "^0.14.1",
                "class-transformer": "^0.5.1",
            },
            dev_dependencies={
                "typescript": "^5.3.3",
                "ts-node": "^10.9.2",
                "@types/node": "^20.11.16",
            },
        )
        return [
            GeneratedFile(
                path="backend/package.json",
                language="json",
                content=content,
                description="Backend dependency manifest",
            ),
            GeneratedFile(
                path="backend/tsconfig.json",
                language="json",
                content=_TSCONFIG_JSON_MIGRATIONS,
                description="TypeScript config (decorator metadata required by NestJS DI)",
            ),
        ]

    content = build_package_json(
        name=slugify_app_name(ctx.project_name),
        scripts={"start": "ts-node src/main.ts", "build": "tsc"},
        dependencies={
            "@nestjs/common": "^10.3.0",
            "@nestjs/core": "^10.3.0",
            "@nestjs/platform-express": "^10.3.0",
            "@nestjs/typeorm": "^10.0.1",
            "@nestjs/microservices": "^10.3.0",
            "typeorm": "^0.3.20",
            "sqlite3": "^5.1.7",
            "reflect-metadata": "^0.2.1",
            "rxjs": "^7.8.1",
            "@grpc/grpc-js": "^1.10.1",
            "@grpc/proto-loader": "^0.7.10",
        },
        dev_dependencies={
            "typescript": "^5.3.3",
            "ts-node": "^10.9.2",
            "@types/node": "^20.11.16",
        },
    )
    return [
        GeneratedFile(
            path="backend/package.json",
            language="json",
            content=content,
            description="Backend dependency manifest",
        ),
        GeneratedFile(
            path="backend/tsconfig.json",
            language="json",
            content=_TSCONFIG_JSON,
            description="TypeScript config (decorator metadata required by NestJS DI)",
        ),
    ]


def entry_point_files(ctx: WiringCtx, migrations: bool = False) -> list[GeneratedFile]:
    if migrations:
        return [
            GeneratedFile(
                path="backend/src/main.ts",
                language="typescript",
                content=_main_ts_migrations(ctx.project_name),
                description="NestJS entry point",
            ),
            GeneratedFile(
                path="backend/src/app.module.ts",
                language="typescript",
                content=_app_module_ts_migrations(ctx.model_files),
                description="Root NestJS module — the database and every feature module",
            ),
            GeneratedFile(
                path="backend/src/database.ts",
                language="typescript",
                content=_DATABASE_TS,
                description="Database settings shared by the app and the TypeORM CLI",
            ),
            GeneratedFile(
                path="backend/src/data-source.ts",
                language="typescript",
                content=_DATA_SOURCE_TS,
                description="TypeORM CLI data source",
            ),
        ]
    return [
        GeneratedFile(
            path="backend/src/main.ts",
            language="typescript",
            content=_MAIN_TS,
            description="NestJS entry point",
        ),
        GeneratedFile(
            path="backend/src/app.module.ts",
            language="typescript",
            content=_build_app_module_ts(ctx.model_files),
            description="Root NestJS module — wires every entity + the controller",
        ),
    ]


def setup_commands(project_name: str) -> list[str]:
    return ["cd backend", "npm install", "npm start"]


ADAPTER = BackendAdapter(
    key="nestjs",
    label="NestJS",
    # Only "typescript" — this adapter always emits TypeScript regardless
    # of ctx.language, so claiming "javascript" too would let
    # stack_matrix._compute_buildable_now() mark a language variant this
    # adapter never actually produces as buildable (the same trap the
    # adapter-language-check exists to prevent).
    supported_languages=("typescript",),
    supported_api_styles=tuple(ROUTES_BUILDERS),
    generate_model=generate_model,
    generate_routes=generate_routes,
    manifest_files=manifest_files,
    entry_point_files=entry_point_files,
    setup_commands=setup_commands,
)
