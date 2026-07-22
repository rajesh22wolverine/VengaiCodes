# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Spring Boot Backend Adapter
#  ai/codegen/backend/spring_boot.py — Targets the Java language variant
#  (stack_matrix's spring_boot also lists "kotlin", but this adapter only
#  ever emits Java — see the supported_languages comment below for why
#  that matters). Spring Data JPA repository interfaces are pure
#  boilerplate mechanically derivable from an entity name (3 lines,
#  zero business logic), so they're generated deterministically in
#  entry_point_files rather than costing a 3rd AI call per table.
# ═══════════════════════════════════════════════════════════════

from app.ai.codegen.types import BackendAdapter, FileResult, ModelCtx, RoutesCtx, WiringCtx
from app.ai.codegen_shared import GROQ_FILE_MAX_TOKENS, GeneratedFile, _pascal, generate_text_validated


def _package_name(project_name: str) -> str:
    import re

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

    prompt = f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Write ONE complete, real Spring Data JPA entity class for the "{table_name}" table of this app.

App: {ctx.project_name}
{ctx.requirements_text}
Table purpose: {ctx.table.get('purpose', '')}
Fields: {', '.join(ctx.table.get('key_fields', []))}

Requirements:
- Package declaration: `package {package_name};`
- Class name: {class_name}, annotated `@Entity`, with `@Id @GeneratedValue(strategy = GenerationType.IDENTITY) private Long id;`
  plus real fields/column annotations (`@Column(nullable = ..., unique = ...)`) matching the
  fields above, and public getters/setters for every field (Lombok is NOT available — write them
  by hand).
- Implement any validation or computed properties implied by the key features / user stories
  above — not a bare field list.
- No placeholders or TODOs — every field and method must be fully implemented.

Return ONLY the raw Java code for this one file. No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(prompt, "java", GROQ_FILE_MAX_TOKENS)
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
        f"- {e.get('method')} {e.get('path')}: {e.get('purpose')}" for e in ctx.endpoints
    )
    repos_text = "\n".join(
        f"- `{_repository_name(t.get('name', 'Item'))} extends JpaRepository<{_pascal(t.get('name', 'Item'))}, Long>` — "
        f"a Spring Data repository already available for autowiring, standard methods "
        f"(findAll, findById, save, deleteById, existsById) plus whatever custom query methods you declare on it"
        for t in ctx.tables
    )

    prompt = f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Write ONE complete, real Spring Boot REST controller implementing every API endpoint below for this app.

App: {ctx.project_name}
{ctx.requirements_text}
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

    content, issue = await generate_text_validated(prompt, "java", GROQ_FILE_MAX_TOKENS)
    return [(
        GeneratedFile(
            path=f"backend/src/main/java/{_package_path(package_name)}/ApiController.java",
            language="java",
            content=content,
            description="Spring REST controller implementing all API endpoints against the real repositories",
        ),
        issue,
    )]


ROUTES_BUILDERS = {"rest": _rest_routes}


async def generate_routes(ctx: RoutesCtx) -> list[FileResult]:
    return await ROUTES_BUILDERS[ctx.api_style](ctx)


def _entity_class_from_path(file: GeneratedFile) -> str:
    return file.path.split("/")[-1].removesuffix(".java")


def _build_repository_java(package_name: str, entity_class: str) -> str:
    return f"""package {package_name};

import org.springframework.data.jpa.repository.JpaRepository;

public interface {_repository_name(entity_class)} extends JpaRepository<{entity_class}, Long> {{
}}
"""


def _build_application_java(package_name: str, project_name: str) -> str:
    app_class = "".join(ch for ch in project_name.title() if ch.isalnum()) or "Generated"
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


def _pom_xml(package_name: str, artifact_id: str, project_name: str) -> str:
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
    <java.version>17</java.version>
  </properties>

  <dependencies>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-web</artifactId>
    </dependency>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-data-jpa</artifactId>
    </dependency>
    <dependency>
      <groupId>com.h2database</groupId>
      <artifactId>h2</artifactId>
      <scope>runtime</scope>
    </dependency>
  </dependencies>

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


_APPLICATION_PROPERTIES = """spring.datasource.url=jdbc:h2:file:./data/app;AUTO_SERVER=TRUE
spring.datasource.driver-class-name=org.h2.Driver
spring.jpa.hibernate.ddl-auto=update
spring.jpa.show-sql=false
server.port=8080
"""


def manifest_files(ctx: WiringCtx) -> list[GeneratedFile]:
    package_name = _package_name(ctx.project_name)
    artifact_id = package_name.split(".")[-1]
    return [
        GeneratedFile(path="backend/pom.xml", language="xml", content=_pom_xml(package_name, artifact_id, ctx.project_name), description="Maven project manifest"),
        GeneratedFile(path="backend/src/main/resources/application.properties", language="text", content=_APPLICATION_PROPERTIES, description="Spring Boot config (H2 file-based DB, zero external setup)"),
    ]


def entry_point_files(ctx: WiringCtx) -> list[GeneratedFile]:
    package_name = _package_name(ctx.project_name)
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
        files.append(GeneratedFile(
            path=f"backend/src/main/java/{_package_path(package_name)}/{_repository_name(entity_class)}.java",
            language="java",
            content=_build_repository_java(package_name, entity_class),
            description=f"Spring Data repository for {entity_class}",
        ))
    return files


def setup_commands(project_name: str) -> list[str]:
    return ["cd backend", "./mvnw spring-boot:run"]


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
