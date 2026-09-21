# ═══════════════════════════════════════════════════════════════
#  VengaiCode — ASP.NET Core Backend Adapter
#  ai/codegen/backend/aspnet_core.py — EF Core (SQLite) + a Controllers-
#  based Web API. AppDbContext.cs is pure boilerplate mechanically
#  derived from the generated entities (one DbSet<T> per table), so
#  it's built deterministically rather than costing another AI call —
#  same reasoning as Spring Boot's repository interfaces.
#
#  2026-09-21: added a real "grpc" api_style using Grpc.AspNetCore —
#  Microsoft's own official package (confirmed current 2.84.0 on
#  NuGet's own API while writing this, not guessed). Same deterministic-
#  proto + AI-service-implementation split as nestjs.py/spring_boot.py's
#  gRPC support: the .proto is generated from the same structured
#  tables/endpoints data (never AI-freehanded), and Grpc.Tools compiles
#  it into a real C# service base class at `dotnet build` time via the
#  `<Protobuf Include=.../>` MSBuild item below — the same "AI writes a
#  declarative contract, the toolchain generates code from it at the
#  user's own build time" shape ASP.NET Core's own EF Core migrations
#  and Angular's own tsc compilation already rely on elsewhere in this
#  pipeline, not something new for this file to invent.
#
#  HONEST STATUS: no .NET SDK is available in this environment to
#  `dotnet build` this for real (unlike Spring Boot's gRPC support,
#  which WAS actually compiled with `mvn compile` and produced real
#  generated stub classes) — this mirrors the .proto/service-impl
#  pattern as closely as possible, verified against Grpc.AspNetCore's
#  own current documented usage instead.
# ═══════════════════════════════════════════════════════════════

from app.ai.codegen.types import BackendAdapter, FileResult, ModelCtx, RoutesCtx, WiringCtx
from app.ai.codegen_shared import GROQ_FILE_MAX_TOKENS, GeneratedFile, _pascal, generate_text_validated

_NAMESPACE = "GeneratedApp"


async def generate_model(ctx: ModelCtx) -> FileResult:
    table_name = ctx.table.get("name", "Item")
    class_name = _pascal(table_name)

    prompt = f"""Write ONE complete, real EF Core entity class for the "{table_name}" table of this app.

Table purpose: {ctx.table.get('purpose', '')}
Fields: {', '.join(ctx.table.get('key_fields', []))}

Requirements:
- Namespace: `namespace {_NAMESPACE}.Models;`
- Class name: {class_name}, with `public int Id {{ get; set; }}` plus real properties (with
  correct C# types and nullability) matching the fields above, using auto-properties
  (`public string Title {{ get; set; }}`).
- Implement any validation or computed properties implied by the key features / user stories
  above — not a bare property list. Use data annotations (`[Required]`, `[MaxLength(...)]` from
  `System.ComponentModel.DataAnnotations`) where they add real value.
- No placeholders or TODOs — every property must be fully implemented.

Return ONLY the raw C# code for this one file. No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(
        prompt, "csharp", GROQ_FILE_MAX_TOKENS,
        user=ctx.user, db=ctx.db, context=ctx.shared_context(),
    )
    return GeneratedFile(
        path=f"backend/Models/{class_name}.cs",
        language="csharp",
        content=content,
        description=f"EF Core entity for {table_name}",
    ), issue


async def _rest_routes(ctx: RoutesCtx) -> list[FileResult]:
    endpoints_text = "\n".join(
        f"- {e.get('method')} {e.get('path')}: {e.get('purpose')}" for e in ctx.endpoints
    )
    entities_text = ", ".join(_pascal(t.get("name", "Item")) for t in ctx.tables)

    prompt = f"""Write ONE complete, real ASP.NET Core API controller implementing every API endpoint below for this app.

A shared `AppDbContext` (namespace `{_NAMESPACE}.Data`) is already available with a
`DbSet<T>` property for each of these entities (namespace `{_NAMESPACE}.Models`): {entities_text}

API endpoints to implement:
{endpoints_text}

Requirements:
- Namespace: `namespace {_NAMESPACE}.Controllers;`
- Class name: `ApiController` (exported) — this EXACT name is required, other generated files
  reference it. Annotate `[ApiController] [Route("api")] public class ApiController : ControllerBase`,
  inject `AppDbContext` via the constructor (`private readonly AppDbContext _db;`).
- Each endpoint MUST do real reads/writes against `_db` (use async EF Core methods:
  `ToListAsync`, `FindAsync`, `SaveChangesAsync`) — do not return hardcoded/fake JSON. Return
  `Ok(...)`, `NotFound()`, `BadRequest(...)` etc. with correct HTTP status codes.
- Implement the actual behavior implied by the key features and user stories above.
- This file must be fully self-contained: do not reference any other controller/service class
  not defined in this file or listed above.
- No placeholders or TODOs — every endpoint must be fully implemented.

Return ONLY the raw C# code for this one file. No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(
        prompt, "csharp", GROQ_FILE_MAX_TOKENS,
        user=ctx.user, db=ctx.db, context=ctx.shared_context(),
    )
    return [(
        GeneratedFile(
            path="backend/Controllers/ApiController.cs",
            language="csharp",
            content=content,
            description="ASP.NET Core controller implementing all API endpoints against the real DbContext",
        ),
        issue,
    )]


def _proto_message_for_table(table: dict) -> str:
    fields = table.get("key_fields", []) or []
    field_lines = "\n".join(f"  string {f} = {i + 2};" for i, f in enumerate(fields))
    return f"message {_pascal(table.get('name', 'Item'))} {{\n  string id = 1;\n{field_lines}\n}}"


def _proto_rpc_for_endpoint(e: dict) -> tuple[str, str]:
    method_name = _pascal(f"{e.get('method', 'get')}_{e.get('path', '/').strip('/')}") or "Call"
    return f"  rpc {method_name} ({method_name}Request) returns ({method_name}Response);", method_name


async def _grpc_routes(ctx: RoutesCtx) -> list[FileResult]:
    """Mirrors nestjs.py's/spring_boot.py's _grpc_routes(): the .proto is
    built deterministically and handed to the AI as a fixed contract, so
    the service implementation can't drift from it."""
    messages = "\n\n".join(_proto_message_for_table(t) for t in ctx.tables) or "message Empty {}"
    rpc_lines = []
    request_response_messages = []
    for e in ctx.endpoints:
        rpc_line, method_name = _proto_rpc_for_endpoint(e)
        rpc_lines.append(rpc_line)
        request_response_messages.append(f"message {method_name}Request {{\n  string payload = 1;\n}}")
        request_response_messages.append(f"message {method_name}Response {{\n  string result = 1;\n}}")

    proto_skeleton = f"""syntax = "proto3";

option csharp_namespace = "{_NAMESPACE}.Grpc";

package api;

service ApiService {{
{chr(10).join(rpc_lines)}
}}

{messages}

{chr(10).join(request_response_messages)}
"""

    endpoints_text = "\n".join(
        f"- {e.get('method')} {e.get('path')}: {e.get('purpose')}" for e in ctx.endpoints
    )
    entities_text = ", ".join(_pascal(t.get("name", "Item")) for t in ctx.tables)

    prompt = f"""A .proto file (below) has ALREADY been generated deterministically for this app's gRPC service — do not change its message/rpc names. Write the ASP.NET Core gRPC service IMPLEMENTATION class that implements every rpc method declared in it.

Already-generated .proto contract (implement EXACTLY these rpc method names, request/response
types — Grpc.Tools compiles this into a real `{_NAMESPACE}.Grpc.ApiService.ApiServiceBase` class
at build time, in the same `{_NAMESPACE}.Grpc` namespace as the generated request/response
message classes):
{proto_skeleton}

A shared `AppDbContext` (namespace `{_NAMESPACE}.Data`) is already available with a `DbSet<T>`
property for each of these entities (namespace `{_NAMESPACE}.Models`): {entities_text}

The endpoints these rpc methods correspond to:
{endpoints_text}

Requirements:
- Namespace: `namespace {_NAMESPACE};`. `using Grpc.Core; using {_NAMESPACE}.Data; using
  {_NAMESPACE}.Grpc; using Microsoft.EntityFrameworkCore;`.
- Class name: `ApiGrpcService : ApiService.ApiServiceBase`, inject `AppDbContext` via the
  constructor (`private readonly AppDbContext _db;`).
- Override EVERY rpc method from the .proto above with its EXACT name, signature
  `public override async Task<XResponse> MethodName(XRequest request, ServerCallContext context)`.
- Each method MUST do a real read/write against `_db` (async EF Core methods: `ToListAsync`,
  `FindAsync`, `SaveChangesAsync`) — do not return hardcoded/fake data. Build the real response
  message via `new XResponse {{ Result = ... }}`. For real error cases, `throw new
  RpcException(new Status(StatusCode.NotFound, "..."));` instead of returning a default response.
- Implement the actual behavior implied by the key features and user stories above.
- This file must be fully self-contained: do not reference any other service/controller class
  not defined in this file or listed above.
- No placeholders or TODOs — every rpc method must be fully implemented.

Return ONLY the raw C# code for this one file. No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(
        prompt, "csharp", GROQ_FILE_MAX_TOKENS,
        user=ctx.user, db=ctx.db, context=ctx.shared_context(),
    )
    return [
        (
            GeneratedFile(
                path="backend/Protos/api.proto",
                language="text",
                content=proto_skeleton,
                description="gRPC service contract (deterministic)",
            ),
            None,
        ),
        (
            GeneratedFile(
                path="backend/Services/ApiGrpcService.cs",
                language="csharp",
                content=content,
                description="gRPC service implementation against the real DbContext",
            ),
            issue,
        ),
    ]


ROUTES_BUILDERS = {"rest": _rest_routes, "grpc": _grpc_routes}


async def generate_routes(ctx: RoutesCtx) -> list[FileResult]:
    return await ROUTES_BUILDERS[ctx.api_style](ctx)


def _is_grpc(ctx: WiringCtx) -> bool:
    return any(f.path == "backend/Protos/api.proto" for f in ctx.routes_files)


def _entity_class_from_path(file: GeneratedFile) -> str:
    return file.path.split("/")[-1].removesuffix(".cs")


def _build_db_context_cs(model_files: list[GeneratedFile]) -> str:
    entities = [_entity_class_from_path(f) for f in model_files]
    dbsets = "\n".join(f"    public DbSet<{name}> {name}s {{ get; set; }}" for name in entities)
    return f"""using Microsoft.EntityFrameworkCore;
using {_NAMESPACE}.Models;

namespace {_NAMESPACE}.Data;

public class AppDbContext : DbContext
{{
    public AppDbContext(DbContextOptions<AppDbContext> options) : base(options) {{ }}

{dbsets}
}}
"""


def _program_cs(project_name: str, grpc: bool) -> str:
    grpc_service = "builder.Services.AddGrpc();\n" if grpc else ""
    controllers_line = "" if grpc else "builder.Services.AddControllers();\n"
    map_line = f"app.MapGrpcService<{_NAMESPACE}.ApiGrpcService>();\n" if grpc else "app.MapControllers();\n"
    return f"""using Microsoft.EntityFrameworkCore;
using {_NAMESPACE}.Data;

var builder = WebApplication.CreateBuilder(args);

{controllers_line}{grpc_service}builder.Services.AddDbContext<AppDbContext>(options => options.UseSqlite("Data Source=app.db"));
builder.Services.AddCors(options => options.AddDefaultPolicy(policy => policy.AllowAnyOrigin().AllowAnyMethod().AllowAnyHeader()));

var app = builder.Build();

using (var scope = app.Services.CreateScope())
{{
    var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
    db.Database.EnsureCreated();
}}

app.UseCors();
{map_line}
app.Run();
"""


def _csproj(project_name: str, grpc: bool) -> str:
    # Versions confirmed live via NuGet's own package index at the time
    # this was written. Grpc.Tools compiles Protos/*.proto (see the
    # <Protobuf> item below) into real C# classes at `dotnet build` time.
    grpc_items = (
        """
  <ItemGroup>
    <PackageReference Include="Grpc.AspNetCore" Version="2.84.0" />
  </ItemGroup>

  <ItemGroup>
    <Protobuf Include="Protos\\api.proto" GrpcServices="Server" />
  </ItemGroup>
"""
        if grpc
        else ""
    )
    return f"""<Project Sdk="Microsoft.NET.Sdk.Web">

  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
  </PropertyGroup>

  <ItemGroup>
    <PackageReference Include="Microsoft.EntityFrameworkCore.Sqlite" Version="8.0.2" />
    <PackageReference Include="Microsoft.EntityFrameworkCore.Design" Version="8.0.2" />
  </ItemGroup>
{grpc_items}
</Project>
"""


def manifest_files(ctx: WiringCtx) -> list[GeneratedFile]:
    return [
        GeneratedFile(path=f"backend/{_NAMESPACE}.csproj", language="xml", content=_csproj(ctx.project_name, _is_grpc(ctx)), description=".NET project manifest"),
    ]


def entry_point_files(ctx: WiringCtx) -> list[GeneratedFile]:
    return [
        GeneratedFile(path="backend/Program.cs", language="csharp", content=_program_cs(ctx.project_name, _is_grpc(ctx)), description="ASP.NET Core entry point"),
        GeneratedFile(path="backend/Data/AppDbContext.cs", language="csharp", content=_build_db_context_cs(ctx.model_files), description="EF Core DbContext — one DbSet per generated entity"),
    ]


def setup_commands(project_name: str) -> list[str]:
    return ["cd backend", "dotnet restore", "dotnet run"]


ADAPTER = BackendAdapter(
    key="aspnet_core",
    label="ASP.NET Core",
    supported_languages=("csharp",),
    supported_api_styles=tuple(ROUTES_BUILDERS),
    generate_model=generate_model,
    generate_routes=generate_routes,
    manifest_files=manifest_files,
    entry_point_files=entry_point_files,
    setup_commands=setup_commands,
)
