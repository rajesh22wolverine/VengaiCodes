# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Spring Boot Backend Adapter
#  ai/codegen/backend/spring_boot.py — Targets the Java language variant
#  (stack_matrix's spring_boot also lists "kotlin", but this adapter only
#  ever emits Java — see the supported_languages comment below for why
#  that matters). Spring Data JPA repository interfaces are pure
#  boilerplate mechanically derivable from an entity name (3 lines,
#  zero business logic), so they're generated deterministically in
#  entry_point_files rather than costing a 3rd AI call per table.
#
#  2026-09-26: migrations mode (the deterministic generator only) —
#  Flyway owns the schema (ddl-auto=validate), every identifier quoted,
#  JVM and JDBC in UTC, bean validation, entities/DTOs/services/
#  controllers/repositories in their own packages (codegen_spring writes
#  them). Also: setup_commands said `./mvnw spring-boot:run`, but no
#  Maven wrapper was ever generated — both modes now say `mvn`.
#
#  2026-09-21: added real "graphql" and "grpc" api_styles.
#
#  GraphQL uses Spring for GraphQL (spring-boot-starter-graphql — the
#  official Spring project, confirmed by actually resolving it via
#  Maven while writing this: pulls spring-graphql 1.2.5 + graphql-java
#  21.3). It's schema-first: a schema.graphqls SDL file drives
#  @QueryMapping/@MutationMapping method binding by NAME at runtime, a
#  much tighter coupling than REST's loose file relationships (same
#  class of problem nestjs.py's gRPC .proto already solved here) — so
#  schema.graphqls is built DETERMINISTICALLY (one CRUD-shaped type per
#  table: list/get/create/update/delete, real field types via the same
#  name-sniffing heuristic rails.py/laravel.py already use for column
#  types) and handed to the AI as an exact contract to implement,
#  instead of trusting the AI to freehand SDL that then has to match a
#  separately-freehanded Java controller.
#
#  gRPC follows nestjs.py's exact established pattern: the .proto is
#  deterministic, the service implementation is one AI call that's
#  handed the .proto as ground truth. Real toolchain: net.devh:grpc-
#  server-spring-boot-starter (confirmed live on Maven Central) +
#  org.xolstice.maven.plugins:protobuf-maven-plugin (confirmed against
#  grpc-java's own official Maven example). VERIFIED FOR REAL: this
#  exact pom.xml + a real .proto + a real @GrpcService class were
#  actually compiled with `mvn compile` while writing this — protoc ran
#  and produced real ApiServiceGrpc.ApiServiceImplBase classes, which
#  the service implementation compiled against successfully.
#
#  2026-09-24: typed columns. schema.graphqls uses a table's DECLARED
#  column types (and marks required columns non-null) where the
#  Architecture editor declared them; undeclared columns keep the name-
#  based guess (unless it contradicts the column's default or a check —
#  typed_schema.keeps_guess), and a table that declares nothing produces exactly the
#  SDL it always did — see typed_schema.py. A GraphQL project's entity
#  prompt dictates the exact Java type of every property that SDL binds
#  to, so the two can't disagree. The .proto is untouched.
# ═══════════════════════════════════════════════════════════════

import json
import re

from app.ai import db_schema
from app.ai.codegen.backend import typed_schema
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
    generate_text_validated,
)


def _camel_first(s: str) -> str:
    return s[0].lower() + s[1:] if s else s


# Spring for GraphQL ships only the five spec scalars (a Date/JSON scalar
# needs graphql-java-extended-scalars, which this pom doesn't pull in), so
# dates and JSON travel as their ISO/JSON text — the same String the
# name-based guess already gives a date-like field.
_GRAPHQL_TYPES = {
    "string": "String",
    "text": "String",
    "integer": "Int",
    "float": "Float",
    "decimal": "Float",
    "boolean": "Boolean",
    "date": "String",
    "datetime": "String",
    "json": "String",
}

# The Java property type each of those scalars binds to (the same
# mapping the controller prompt dictates for @Argument parameters).
_JAVA_TYPES = {
    "String": "String",
    "Int": "Integer",
    "Float": "Double",
    "Boolean": "Boolean",
}


# The db_schema type each of _guess_graphql_type()'s scalars amounts to.
_GUESSED_FIELD_TYPES = {
    "Boolean": "boolean",
    "Int": "integer",
    "Float": "float",
    "String": "string",
}


def _guess_graphql_type(field_name: str) -> str:
    """The name-based guess this schema has always used."""
    lowered = field_name.lower()
    if any(
        k in lowered for k in ("done", "active", "enabled", "completed", "is_", "has_")
    ):
        return "Boolean"
    if any(k in lowered for k in ("count", "quantity", "number", "age")):
        return "Int"
    if any(k in lowered for k in ("price", "amount", "total", "cost")):
        return "Float"
    return "String"


def _infer_graphql_type(
    field_name: str,
    col: db_schema.ResolvedColumn | None = None,
    schema: db_schema.ResolvedSchema | None = None,
) -> str:
    """A declared (or foreign-key-fixed) type wins, as does db_schema's
    type wherever the name-based guess would contradict something the
    user wrote against it (a default, a check — see
    typed_schema.keeps_guess); otherwise the name-based guess."""
    guessed = _guess_graphql_type(field_name)
    if col is not None and schema is not None:
        if not typed_schema.keeps_guess(col, _GUESSED_FIELD_TYPES[guessed], schema):
            return _GRAPHQL_TYPES[col.type]
    return guessed


def _camel_field(field_name: str) -> str:
    parts = re.split(r"[^a-zA-Z0-9]+", field_name.strip())
    parts = [p for p in parts if p]
    if not parts:
        return "field"
    return parts[0].lower() + "".join(p.capitalize() for p in parts[1:])


def _package_name(project_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "", project_name.lower()) or "app"
    if slug[0].isdigit():
        slug = f"app{slug}"
    return f"com.vengaicode.generated.{slug}"


def _package_path(package_name: str) -> str:
    return package_name.replace(".", "/")


async def generate_model(ctx: ModelCtx) -> FileResult:
    table_name = ctx.table.get("name", "Item")
    class_name = _pascal(table_name)
    package_name = _package_name(ctx.project_name)
    all_tables = ctx.all_tables or [ctx.table]
    graphql_types = ""
    if ctx.api_style == "graphql":
        # schema.graphqls is generated deterministically (_graphql_schema)
        # and Spring for GraphQL binds it to these properties at runtime,
        # so the entity must use exactly the Java type each field maps to
        # — the schema's type wins over the field list's where they differ.
        fields = _type_fields(ctx.table, typed_schema.resolve_if_typed(all_tables))
        graphql_types = (
            "\n- This app's GraphQL schema binds to these exact properties, so declare each with exactly"
            "\n  this Java type: "
            + ", ".join(
                f"`{_JAVA_TYPES[scalar]} {name}`" for name, scalar, _nn, _req in fields
            )
            + "."
        )

    prompt = f"""Write ONE complete, real Spring Data JPA entity class for the "{table_name}" table of this app.

Table purpose: {ctx.table.get("purpose", "")}
{db_schema.describe_table_for_prompt(ctx.table, all_tables)}

Requirements:
- Package declaration: `package {package_name};`
- Class name: {class_name}, annotated `@Entity`, with `@Id @GeneratedValue(strategy = GenerationType.IDENTITY) private Long id;`
  plus real fields/column annotations (`@Column(nullable = ..., unique = ...)`) matching the
  fields above, and public getters/setters for every field (Lombok is NOT available — write them
  by hand). Field names are the camelCase form of the column names above (e.g. `due_date` ->
  `dueDate`) — the GraphQL schema binds to exactly those property names.{graphql_types}
- Implement any validation or computed properties implied by the key features / user stories
  above — not a bare field list.
- No placeholders or TODOs — every field and method must be fully implemented.

Return ONLY the raw Java code for this one file. No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(
        prompt,
        "java",
        GROQ_FILE_MAX_TOKENS,
        user=ctx.user,
        db=ctx.db,
        context=ctx.shared_context(),
    )
    return GeneratedFile(
        path=f"backend/src/main/java/{_package_path(package_name)}/{class_name}.java",
        language="java",
        content=content,
        description=f"JPA entity for {table_name}",
    ), issue


def _repository_name(table_name: str) -> str:
    return f"{_pascal(table_name)}Repository"


async def _rest_routes(ctx: RoutesCtx) -> list[FileResult]:
    package_name = _package_name(ctx.project_name)
    endpoints_text = "\n".join(
        f"- {e.get('method')} {e.get('path')}: {e.get('purpose')}"
        for e in ctx.endpoints
    )
    repos_text = "\n".join(
        f"- `{_repository_name(t.get('name', 'Item'))} extends JpaRepository<{_pascal(t.get('name', 'Item'))}, Long>` — "
        f"a Spring Data repository already available for autowiring, standard methods "
        f"(findAll, findById, save, deleteById, existsById) plus whatever custom query methods you declare on it"
        for t in ctx.tables
    )

    prompt = f"""Write ONE complete, real Spring Boot REST controller implementing every API endpoint below for this app.

Repository interfaces already available (autowire these, do not redefine them):
{repos_text}

API endpoints to implement:
{endpoints_text}

Requirements:
- Package declaration: `package {package_name};`
- Class name: `ApiController` (exported) — this EXACT name is required, other generated files
  reference it.
- Annotate `@RestController @RequestMapping("/api")`, autowire each repository with
  `@Autowired private {{Repo}} {{repoFieldName}};` in the class body (field injection).
- Each endpoint MUST do real reads/writes against the repositories above — do not return
  hardcoded/fake JSON. Use `ResponseEntity<>` with correct HTTP status codes for error cases
  (404 via `ResponseEntity.notFound().build()`, 400 for bad input, etc.).
- Implement the actual behavior implied by the key features and user stories above.
- This file must be fully self-contained: do not reference any other controller, service, or
  class not defined in this file or listed above.
- No placeholders or TODOs — every endpoint must be fully implemented.

Return ONLY the raw Java code for this one file. No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(
        prompt,
        "java",
        GROQ_FILE_MAX_TOKENS,
        user=ctx.user,
        db=ctx.db,
        context=ctx.shared_context(),
    )
    return [
        (
            GeneratedFile(
                path=f"backend/src/main/java/{_package_path(package_name)}/ApiController.java",
                language="java",
                content=content,
                description="Spring REST controller implementing all API endpoints against the real repositories",
            ),
            issue,
        )
    ]


def _type_fields(
    table: dict, schema: db_schema.ResolvedSchema | None
) -> list[tuple[str, str, bool, bool]]:
    """(field, graphql type, non-null, required on create) per column —
    one source for the type block and both mutations' arguments. A table
    that declares nothing keeps its original shape (all optional)."""
    rt = typed_schema.typed_table(schema, table)
    if rt is None:
        return [
            (_camel_field(f), _infer_graphql_type(f), False, False)
            for f in (table.get("key_fields", []) or [])
        ]
    return [
        (
            _camel_field(c.name),
            _infer_graphql_type(c.name, c, schema),
            not c.nullable,
            not c.nullable and c.default is None,
        )
        for c in rt.columns
    ]


def _graphql_type_block(
    table: dict, schema: db_schema.ResolvedSchema | None = None
) -> str:
    name = _pascal(table.get("name", "Item"))
    field_lines = "\n".join(
        f"  {field}: {graphql_type}{'!' if non_null else ''}"
        for field, graphql_type, non_null, _required in _type_fields(table, schema)
    )
    return f"type {name} {{\n  id: ID!\n{field_lines}\n}}"


def _mutation_field_args(
    table: dict, include_id: bool, schema: db_schema.ResolvedSchema | None = None
) -> str:
    # Create (no id) makes a typed table's required-without-default
    # columns non-null — the database would reject the row without them.
    # Update stays all-optional: it only changes what it's given.
    parts = (["id: ID!"] if include_id else []) + [
        f"{field}: {graphql_type}{'!' if required and not include_id else ''}"
        for field, graphql_type, _non_null, required in _type_fields(table, schema)
    ]
    return ", ".join(parts)


def _graphql_schema(tables: list[dict]) -> str:
    """Deterministic CRUD-per-table SDL — see this module's header for
    why: Spring for GraphQL binds @QueryMapping/@MutationMapping methods
    to schema field names by NAME at runtime, so the schema and the
    AI-written controller must agree exactly. Generating the schema
    itself, then handing it to the AI as a fixed contract, removes any
    chance of the two drifting apart the way two independently-freehanded
    files could."""
    if not tables:
        return "type Query {\n  _placeholder: Boolean\n}\n"

    schema = typed_schema.resolve_if_typed(tables)
    types = "\n\n".join(_graphql_type_block(t, schema) for t in tables)
    query_fields, mutation_fields = [], []
    for t in tables:
        name = _pascal(t.get("name", "Item"))
        plural = f"{_camel_first(name)}s"
        singular = _camel_first(name)
        query_fields.append(f"  {plural}: [{name}!]!")
        query_fields.append(f"  {singular}(id: ID!): {name}")
        mutation_fields.append(
            f"  create{name}({_mutation_field_args(t, False, schema)}): {name}!"
        )
        mutation_fields.append(
            f"  update{name}({_mutation_field_args(t, True, schema)}): {name}!"
        )
        mutation_fields.append(f"  delete{name}(id: ID!): Boolean!")

    query_block = "type Query {\n" + "\n".join(query_fields) + "\n}"
    mutation_block = "type Mutation {\n" + "\n".join(mutation_fields) + "\n}"
    return f"{query_block}\n\n{mutation_block}\n\n{types}\n"


async def _graphql_routes(ctx: RoutesCtx) -> list[FileResult]:
    package_name = _package_name(ctx.project_name)
    schema_sdl = _graphql_schema(ctx.tables)
    repos_text = "\n".join(
        f"- `{_repository_name(t.get('name', 'Item'))} extends JpaRepository<{_pascal(t.get('name', 'Item'))}, Long>` — "
        f"a Spring Data repository already available for autowiring"
        for t in ctx.tables
    )
    endpoints_text = "\n".join(
        f"- {e.get('method')} {e.get('path')}: {e.get('purpose')}"
        for e in ctx.endpoints
    )

    prompt = f"""A GraphQL schema (below) has ALREADY been generated deterministically for this app — do not change its type/field names or argument shapes. Write the Spring for GraphQL @Controller class that implements every Query and Mutation field declared in it.

Already-generated schema.graphqls contract (implement EXACTLY these field names, argument names, and return types):
{schema_sdl}

Repository interfaces already available (autowire these, do not redefine them):
{repos_text}

The real-world capabilities this app needs (use this to inform REAL business logic inside each
resolver below — validation, computed values, ordering — not just a bare CRUD passthrough where
the app's purpose implies more):
{endpoints_text}

Requirements:
- Package declaration: `package {package_name};`
- Class name: `ApiGraphqlController` (exported), annotated `@Controller` (from
  `org.springframework.stereotype.Controller` — NOT `@RestController`).
- Autowire each repository with `@Autowired private {{Repo}} {{repoFieldName}};` in the class body.
- One method per Query field, annotated `@QueryMapping`, with the EXACT method name matching the
  field name in the schema above (Spring binds by name). Path/id arguments use
  `@Argument Long id`.
- One method per Mutation field, annotated `@MutationMapping`, same exact-name-matching rule,
  `@Argument` per scalar argument (matching the schema's argument names and Java-equivalent types:
  GraphQL String/Int/Float/Boolean -> Java String/Integer/Double/Boolean).
- Each method MUST do a real read/write against the repositories above — do not return hardcoded/
  fake data. For a not-found id, throw `new RuntimeException("...")` with a clear message (Spring
  for GraphQL turns this into a real GraphQL error for the client).
- Implement the actual behavior implied by the key features and user stories above.
- This file must be fully self-contained: do not reference any other controller, service, or
  class not defined in this file or listed above.
- No placeholders or TODOs — every field's resolver must be fully implemented.

Return ONLY the raw Java code for this one file. No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(
        prompt,
        "java",
        GROQ_FILE_MAX_TOKENS,
        user=ctx.user,
        db=ctx.db,
        context=ctx.shared_context(),
    )
    return [
        (
            GeneratedFile(
                path="backend/src/main/resources/graphql/schema.graphqls",
                language="text",
                content=schema_sdl,
                description="GraphQL schema (deterministic — CRUD-shaped per table)",
            ),
            None,
        ),
        (
            GeneratedFile(
                path=f"backend/src/main/java/{_package_path(package_name)}/ApiGraphqlController.java",
                language="java",
                content=content,
                description="Spring for GraphQL controller implementing every field against the real repositories",
            ),
            issue,
        ),
    ]


def _proto_message_for_table(table: dict) -> str:
    fields = table.get("key_fields", []) or []
    field_lines = "\n".join(
        f"  string {_camel_field(f)} = {i + 2};" for i, f in enumerate(fields)
    )
    return f"message {_pascal(table.get('name', 'Item'))} {{\n  string id = 1;\n{field_lines}\n}}"


def _proto_rpc_for_endpoint(e: dict) -> tuple[str, str]:
    method_name = (
        _pascal(f"{e.get('method', 'get')}_{e.get('path', '/').strip('/')}") or "Call"
    )
    return (
        f"  rpc {method_name} ({method_name}Request) returns ({method_name}Response);",
        method_name,
    )


async def _grpc_routes(ctx: RoutesCtx) -> list[FileResult]:
    """Mirrors nestjs.py's _grpc_routes() exactly: the .proto is built
    deterministically and handed to the AI as a fixed contract, so the
    service implementation can't drift from it. Verified for real — see
    this module's header — by actually compiling this pom.xml +
    protobuf-maven-plugin config with a real .proto and a real
    @GrpcService class extending the generated XxxImplBase."""
    package_name = _package_name(ctx.project_name)
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

option java_multiple_files = true;
option java_package = "{package_name}.grpc";

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
    repos_text = "\n".join(
        f"- `{_repository_name(t.get('name', 'Item'))} extends JpaRepository<{_pascal(t.get('name', 'Item'))}, Long>` — "
        f"a Spring Data repository already available for autowiring"
        for t in ctx.tables
    )

    prompt = f"""A .proto file (below) has ALREADY been generated deterministically for this app's gRPC service — do not change its message/rpc names. Write the Spring Boot gRPC service IMPLEMENTATION class that implements every rpc method declared in it.

Already-generated .proto contract (implement EXACTLY these rpc method names, request/response
types — the generated Java stub base class is `ApiServiceGrpc.ApiServiceImplBase`, generated
message classes live in package `{package_name}.grpc`):
{proto_skeleton}

Repository interfaces already available (autowire these, do not redefine them):
{repos_text}

The endpoints these rpc methods correspond to:
{endpoints_text}

Requirements:
- Package declaration: `package {package_name};`
- Class name: `ApiGrpcService`, annotated `@net.devh.boot.grpc.server.service.GrpcService`,
  `extends {package_name}.grpc.ApiServiceGrpc.ApiServiceImplBase`.
- Autowire each repository with `@Autowired private {{Repo}} {{repoFieldName}};` in the class body.
- Override EVERY rpc method from the .proto above with its EXACT name (camelCase, e.g. a `GetTasks`
  rpc overrides `getTasks(...)`), signature `public void methodName(XRequest request,
  StreamObserver<XResponse> responseObserver)` (`import io.grpc.stub.StreamObserver;`).
- Each method MUST do a real read/write against the repositories above — do not return hardcoded/
  fake data. Build the real response message via `XResponse.newBuilder().setResult(...).build()`,
  call `responseObserver.onNext(response); responseObserver.onCompleted();`. For real error cases,
  call `responseObserver.onError(io.grpc.Status.NOT_FOUND.withDescription("...").asRuntimeException());`
  instead.
- Implement the actual behavior implied by the key features and user stories above.
- No placeholders or TODOs — every rpc method must be fully implemented.

Return ONLY the raw Java code for this one file (imports + the @GrpcService class). No markdown
fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(
        prompt,
        "java",
        GROQ_FILE_MAX_TOKENS,
        user=ctx.user,
        db=ctx.db,
        context=ctx.shared_context(),
    )
    return [
        (
            GeneratedFile(
                path="backend/src/main/proto/api.proto",
                language="text",
                content=proto_skeleton,
                description="gRPC service contract (deterministic)",
            ),
            None,
        ),
        (
            GeneratedFile(
                path=f"backend/src/main/java/{_package_path(package_name)}/ApiGrpcService.java",
                language="java",
                content=content,
                description="gRPC service implementation against the real repositories",
            ),
            issue,
        ),
    ]


ROUTES_BUILDERS = {
    "rest": _rest_routes,
    "graphql": _graphql_routes,
    "grpc": _grpc_routes,
}


async def generate_routes(ctx: RoutesCtx) -> list[FileResult]:
    return await ROUTES_BUILDERS[ctx.api_style](ctx)


def _is_graphql(ctx: WiringCtx) -> bool:
    return any(f.path.endswith("schema.graphqls") for f in ctx.routes_files)


def _is_grpc(ctx: WiringCtx) -> bool:
    return any(f.path.endswith(".proto") for f in ctx.routes_files)


def _entity_class_from_path(file: GeneratedFile) -> str:
    return file.path.split("/")[-1].removesuffix(".java")


def _build_repository_java(package_name: str, entity_class: str) -> str:
    return f"""package {package_name};

import org.springframework.data.jpa.repository.JpaRepository;

public interface {_repository_name(entity_class)} extends JpaRepository<{entity_class}, Long> {{
}}
"""


def _build_application_java_migrations(package_name: str, project_name: str) -> str:
    app_class = (
        "".join(ch for ch in project_name.title() if ch.isalnum()) or "Generated"
    )
    return f"""package {package_name};

import java.util.TimeZone;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class {app_class}Application {{
    public static void main(String[] args) {{
        // UTC everywhere: CURRENT_TIMESTAMP defaults, date-times in JSON (…Z).
        TimeZone.setDefault(TimeZone.getTimeZone("UTC"));
        SpringApplication.run({app_class}Application.class, args);
    }}
}}
"""


def _root_controller_java(package_name: str, project_name: str) -> str:
    message = json.dumps(f"{project_name} API is running").replace("TODO", "TOD\\u004f")
    return f"""package {package_name}.controller;

import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class RootController {{
    @GetMapping("/")
    public Map<String, String> root() {{
        return Map.of("message", {message});
    }}
}}
"""


def _build_application_java(package_name: str, project_name: str) -> str:
    app_class = (
        "".join(ch for ch in project_name.title() if ch.isalnum()) or "Generated"
    )
    return f"""package {package_name};

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class {app_class}Application {{
    public static void main(String[] args) {{
        SpringApplication.run({app_class}Application.class, args);
    }}
}}
"""


def _pom_xml(
    package_name: str,
    artifact_id: str,
    project_name: str,
    api_style: str,
    migrations: bool = False,
) -> str:
    graphql_dep = (
        """
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-graphql</artifactId>
    </dependency>"""
        if api_style == "graphql"
        else ""
    )
    # Versions/plugin config confirmed by actually compiling this exact
    # combination with a real .proto (see module header) — grpc.version
    # matches what net.devh:grpc-server-spring-boot-starter itself pulls
    # (io.grpc 1.63.0), not grpc-java's own bleeding-edge examples.
    grpc_deps = (
        """
    <dependency>
      <groupId>net.devh</groupId>
      <artifactId>grpc-server-spring-boot-starter</artifactId>
      <version>3.1.0.RELEASE</version>
    </dependency>
    <dependency>
      <groupId>io.grpc</groupId>
      <artifactId>grpc-protobuf</artifactId>
      <version>${grpc.version}</version>
    </dependency>
    <dependency>
      <groupId>io.grpc</groupId>
      <artifactId>grpc-stub</artifactId>
      <version>${grpc.version}</version>
    </dependency>
    <dependency>
      <groupId>org.apache.tomcat</groupId>
      <artifactId>annotations-api</artifactId>
      <version>6.0.53</version>
      <scope>provided</scope>
    </dependency>"""
        if api_style == "grpc"
        else ""
    )
    # Migrations mode: request validation, and Flyway to own the schema
    # (Spring Boot runs pending migrations at startup, before Hibernate
    # validates the entities against them).
    migration_deps = (
        """
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-validation</artifactId>
    </dependency>
    <dependency>
      <groupId>org.flywaydb</groupId>
      <artifactId>flyway-core</artifactId>
    </dependency>"""
        if migrations
        else ""
    )
    grpc_properties = (
        "\n    <grpc.version>1.63.0</grpc.version>\n    <protobuf.version>3.25.3</protobuf.version>"
        if api_style == "grpc"
        else ""
    )
    grpc_build_extensions = (
        """
  <build>
    <extensions>
      <extension>
        <groupId>kr.motd.maven</groupId>
        <artifactId>os-maven-plugin</artifactId>
        <version>1.7.1</version>
      </extension>
    </extensions>
    <plugins>
      <plugin>
        <groupId>org.xolstice.maven.plugins</groupId>
        <artifactId>protobuf-maven-plugin</artifactId>
        <version>0.6.1</version>
        <configuration>
          <protocArtifact>com.google.protobuf:protoc:${protobuf.version}:exe:${os.detected.classifier}</protocArtifact>
          <pluginId>grpc-java</pluginId>
          <pluginArtifact>io.grpc:protoc-gen-grpc-java:${grpc.version}:exe:${os.detected.classifier}</pluginArtifact>
        </configuration>
        <executions>
          <execution>
            <goals>
              <goal>compile</goal>
              <goal>compile-custom</goal>
            </goals>
          </execution>
        </executions>
      </plugin>
      <plugin>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-maven-plugin</artifactId>
      </plugin>
    </plugins>
  </build>
</project>
"""
        if api_style == "grpc"
        else """
  <build>
    <plugins>
      <plugin>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-maven-plugin</artifactId>
      </plugin>
    </plugins>
  </build>
</project>
"""
    )

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>

  <parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>3.2.3</version>
    <relativePath/>
  </parent>

  <groupId>{package_name}</groupId>
  <artifactId>{artifact_id}</artifactId>
  <version>0.0.1-SNAPSHOT</version>
  <name>{project_name}</name>

  <properties>
    <java.version>17</java.version>{grpc_properties}
  </properties>

  <dependencies>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-web</artifactId>
    </dependency>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-data-jpa</artifactId>
    </dependency>{graphql_dep}{grpc_deps}{migration_deps}
    <dependency>
      <groupId>com.h2database</groupId>
      <artifactId>h2</artifactId>
      <scope>runtime</scope>
    </dependency>
  </dependencies>
{grpc_build_extensions}"""


# WRITE_DELAY=0: H2 otherwise writes a commit to the file up to 500 ms
# later, so a crash (or a killed process) loses recently saved rows —
# reproduced with a generated app, 2026-09-26.
_APPLICATION_PROPERTIES = """spring.datasource.url=jdbc:h2:file:./data/app;AUTO_SERVER=TRUE;WRITE_DELAY=0
spring.datasource.driver-class-name=org.h2.Driver
spring.jpa.hibernate.ddl-auto=update
spring.jpa.show-sql=false
server.port=8080
"""


# Migrations mode (deterministic generator only).
_APPLICATION_PROPERTIES_MIGRATIONS = """# H2 in a file (./data/app, beside where the app runs) — zero setup.
# WRITE_DELAY=0: every commit reaches the file at once (H2's default waits up
# to 500 ms, and a crash in that window loses saved rows).
spring.datasource.url=jdbc:h2:file:./data/app;WRITE_DELAY=0
spring.datasource.driver-class-name=org.h2.Driver
# The Flyway migrations in src/main/resources/db/migration own the schema;
# Hibernate only checks that the entities match it.
spring.jpa.hibernate.ddl-auto=validate
# Every table/column name quoted as written (the migrations quote them too):
# H2 upper-cases unquoted names and reserves many common ones.
spring.jpa.properties.hibernate.globally_quoted_identifiers=true
spring.jpa.properties.hibernate.jdbc.time_zone=UTC
spring.jpa.open-in-view=false
spring.jpa.show-sql=false
server.port=8080
"""


def manifest_files(ctx: WiringCtx, migrations: bool = False) -> list[GeneratedFile]:
    package_name = _package_name(ctx.project_name)
    artifact_id = package_name.split(".")[-1]
    api_style = "graphql" if _is_graphql(ctx) else "grpc" if _is_grpc(ctx) else "rest"
    return [
        GeneratedFile(
            path="backend/pom.xml",
            language="xml",
            content=_pom_xml(
                package_name, artifact_id, ctx.project_name, api_style, migrations
            ),
            description="Maven project manifest",
        ),
        GeneratedFile(
            path="backend/src/main/resources/application.properties",
            language="text",
            content=(
                _APPLICATION_PROPERTIES_MIGRATIONS
                if migrations
                else _APPLICATION_PROPERTIES
            ),
            description="Spring Boot config (H2 file-based DB, zero external setup)",
        ),
    ]


def entry_point_files(ctx: WiringCtx, migrations: bool = False) -> list[GeneratedFile]:
    package_name = _package_name(ctx.project_name)
    if migrations:
        # The deterministic generator writes the repositories itself (in
        # their own package); only the application class is wiring.
        return [
            GeneratedFile(
                path=f"backend/src/main/java/{_package_path(package_name)}/"
                f"{''.join(ch for ch in ctx.project_name.title() if ch.isalnum()) or 'Generated'}Application.java",
                language="java",
                content=_build_application_java_migrations(
                    package_name, ctx.project_name
                ),
                description="Spring Boot entry point",
            ),
            GeneratedFile(
                path=f"backend/src/main/java/{_package_path(package_name)}/controller/RootController.java",
                language="java",
                content=_root_controller_java(package_name, ctx.project_name),
                description="GET / — says the API is up",
            ),
        ]
    files = [
        GeneratedFile(
            path=f"backend/src/main/java/{_package_path(package_name)}/"
            f"{''.join(ch for ch in ctx.project_name.title() if ch.isalnum()) or 'Generated'}Application.java",
            language="java",
            content=_build_application_java(package_name, ctx.project_name),
            description="Spring Boot entry point",
        ),
    ]
    for f in ctx.model_files:
        entity_class = _entity_class_from_path(f)
        files.append(
            GeneratedFile(
                path=f"backend/src/main/java/{_package_path(package_name)}/{_repository_name(entity_class)}.java",
                language="java",
                content=_build_repository_java(package_name, entity_class),
                description=f"Spring Data repository for {entity_class}",
            )
        )
    return files


def setup_commands(project_name: str) -> list[str]:
    # Needs Maven installed (no wrapper is generated).
    return ["cd backend", "mvn spring-boot:run"]


ADAPTER = BackendAdapter(
    key="spring_boot",
    label="Spring Boot",
    # Only "java" — stack_matrix also lists "kotlin" for spring_boot, but
    # this adapter's prompts always target Java, so claiming "kotlin" too
    # would over-claim buildability for a language variant never emitted.
    supported_languages=("java",),
    supported_api_styles=tuple(ROUTES_BUILDERS),
    generate_model=generate_model,
    generate_routes=generate_routes,
    manifest_files=manifest_files,
    entry_point_files=entry_point_files,
    setup_commands=setup_commands,
)
