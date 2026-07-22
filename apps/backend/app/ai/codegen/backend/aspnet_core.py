# ═══════════════════════════════════════════════════════════════
#  VengaiCode — ASP.NET Core Backend Adapter
#  ai/codegen/backend/aspnet_core.py — EF Core (SQLite) + a Controllers-
#  based Web API. AppDbContext.cs is pure boilerplate mechanically
#  derived from the generated entities (one DbSet<T> per table), so
#  it's built deterministically rather than costing another AI call —
#  same reasoning as Spring Boot's repository interfaces.
# ═══════════════════════════════════════════════════════════════

from app.ai.codegen.types import BackendAdapter, FileResult, ModelCtx, RoutesCtx, WiringCtx
from app.ai.codegen_shared import GROQ_FILE_MAX_TOKENS, GeneratedFile, _pascal, generate_text_validated

_NAMESPACE = "GeneratedApp"


async def generate_model(ctx: ModelCtx) -> FileResult:
    table_name = ctx.table.get("name", "Item")
    class_name = _pascal(table_name)

    prompt = f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Write ONE complete, real EF Core entity class for the "{table_name}" table of this app.

App: {ctx.project_name}
{ctx.requirements_text}
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

    content, issue = await generate_text_validated(prompt, "csharp", GROQ_FILE_MAX_TOKENS)
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

    prompt = f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Write ONE complete, real ASP.NET Core API controller implementing every API endpoint below for this app.

App: {ctx.project_name}
{ctx.requirements_text}
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

    content, issue = await generate_text_validated(prompt, "csharp", GROQ_FILE_MAX_TOKENS)
    return [(
        GeneratedFile(
            path="backend/Controllers/ApiController.cs",
            language="csharp",
            content=content,
            description="ASP.NET Core controller implementing all API endpoints against the real DbContext",
        ),
        issue,
    )]


ROUTES_BUILDERS = {"rest": _rest_routes}


async def generate_routes(ctx: RoutesCtx) -> list[FileResult]:
    return await ROUTES_BUILDERS[ctx.api_style](ctx)


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


def _program_cs(project_name: str) -> str:
    return f"""using Microsoft.EntityFrameworkCore;
using {_NAMESPACE}.Data;

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddControllers();
builder.Services.AddDbContext<AppDbContext>(options => options.UseSqlite("Data Source=app.db"));
builder.Services.AddCors(options => options.AddDefaultPolicy(policy => policy.AllowAnyOrigin().AllowAnyMethod().AllowAnyHeader()));

var app = builder.Build();

using (var scope = app.Services.CreateScope())
{{
    var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
    db.Database.EnsureCreated();
}}

app.UseCors();
app.MapControllers();

app.Run();
"""


def _csproj(project_name: str) -> str:
    return """<Project Sdk="Microsoft.NET.Sdk.Web">

  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
  </PropertyGroup>

  <ItemGroup>
    <PackageReference Include="Microsoft.EntityFrameworkCore.Sqlite" Version="8.0.2" />
    <PackageReference Include="Microsoft.EntityFrameworkCore.Design" Version="8.0.2" />
  </ItemGroup>

</Project>
"""


def manifest_files(ctx: WiringCtx) -> list[GeneratedFile]:
    return [
        GeneratedFile(path=f"backend/{_NAMESPACE}.csproj", language="xml", content=_csproj(ctx.project_name), description=".NET project manifest"),
    ]


def entry_point_files(ctx: WiringCtx) -> list[GeneratedFile]:
    return [
        GeneratedFile(path="backend/Program.cs", language="csharp", content=_program_cs(ctx.project_name), description="ASP.NET Core entry point"),
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
