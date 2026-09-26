# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Deterministic (no-AI) Spring Boot + JPA + Flyway (H2)
#  ai/codegen_spring.py — The Spring Boot backend codegen_deterministic
#  dispatches to, following the knowledge registry's Spring rules:
#  jakarta.persistence entities in model/, Spring Data repositories,
#  constructor injection, controllers that return DTOs (never entities
#  with lazy relations), Flyway owning the schema with Hibernate set to
#  validate it, errors handled in one @RestControllerAdvice.
#
#  Same REST surface as every other generated backend: /api/<table> and
#  /api/<table>/<id>, JSON keyed by column name, PUT changes only the
#  fields it sends (Optional fields tell "left out" from "set to null"),
#  the database's constraint violations answered with the same sentences
#  (409 duplicate, 422 broken rule), a missing parent 422, a refused
#  delete 409. Errors are RFC 7807 problem details, whose "detail" the
#  screens read.
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations

from app.ai import db_schema
from app.ai import spring_render as sr
from app.ai.codegen_shared import GeneratedFile

# Names the generated Java files define or import besides the per-table
# classes (a table whose class would be called one of these is refused).
IMPORTED_NAMES = frozenset(
    {
        "ApiErrors",
        "ApiException",
        "JsonText",
        "References",
        "BigDecimal",
        "Instant",
        "LocalDate",
        "ZoneOffset",
        "List",
        "ArrayList",
        "Optional",
        "Sort",
        "EntityManager",
        "HttpStatus",
        "ProblemDetail",
        "Valid",
        "Size",
        "Digits",
    }
)
SUFFIXES = ("Repository", "Request", "Response", "Service", "Controller")


def _path(package: str, sub: str, name: str) -> str:
    return f"backend/src/main/java/{package.replace('.', '/')}/{sub}/{name}.java"


def _cap(name: str) -> str:
    return name[:1].upper() + name[1:]


def _column(table: dict, tables: dict, c: str) -> tuple[dict, dict]:
    col = table["columns"][c]
    return col, sr.base_column(col, tables)


def _java_imports(types: set[str]) -> list[str]:
    known = {
        "BigDecimal": "java.math.BigDecimal",
        "Instant": "java.time.Instant",
        "LocalDate": "java.time.LocalDate",
        "ZoneOffset": "java.time.ZoneOffset",
    }
    return [f"import {known[t]};" for t in sorted(types) if t in known]


# ─── entity ───
def entity_file(
    package: str, sql_name: str, table: dict, tables: dict, slug: str, heading: str
) -> GeneratedFile:
    name = sr.class_name(table)
    used: set[str] = {"Instant"}
    fields, accessors = [], []
    jpa = {"Column", "Entity", "GeneratedValue", "GenerationType", "Id", "Table"}
    hibernate = {"CreationTimestamp", "UpdateTimestamp"}
    extra_imports: set[str] = set()

    def accessor(java_type: str, field: str) -> None:
        cap = _cap(field)
        accessors.extend(
            [
                f"    public {java_type} get{cap}() {{",
                f"        return {field};",
                "    }",
                "",
                f"    public void set{cap}({java_type} {field}) {{",
                f"        this.{field} = {field};",
                "    }",
                "",
            ]
        )

    fields += [
        "    @Id",
        "    @GeneratedValue(strategy = GenerationType.IDENTITY)",
        f"    @Column(name = {sr.java_string('id')})",
        "    private Long id;",
        "",
    ]
    accessor("Long", "id")
    for c in table["column_order"]:
        col, base = _column(table, tables, c)
        field = sr.java_name(c)
        jtype = sr.java_type(base)
        used.add(jtype)
        opts = [f"name = {sr.java_string(c)}"]
        if not col["nullable"]:
            opts.append("nullable = false")
        if base["type"] == "string":
            opts.append(f"length = {base['length']}")
        if base["type"] == "decimal":
            opts += [
                f"precision = {db_schema.DECIMAL_PRECISION}",
                f"scale = {db_schema.DECIMAL_SCALE}",
            ]
        annotations = [f"    @Column({', '.join(opts)})"]
        if base["type"] == "json":
            jpa.add("Convert")
            annotations.insert(0, "    @Convert(converter = JsonText.class)")
        default = sr.java_default(col)
        if default is not None:
            if "ZoneOffset" in default:
                used.add("ZoneOffset")
            if "LocalDate" in default:
                used.add("LocalDate")
        init = f" = {default}" if default is not None else ""
        fields += annotations + [f"    private {jtype} {field}{init};", ""]
        accessor(jtype, field)
        if col["fk"]:
            jpa |= {"FetchType", "JoinColumn", "ManyToOne"}
            target = sr.class_name(tables[col["fk"]["table"]])
            rel = sr.relation_name(c, table)
            join = [
                f"name = {sr.java_string(c)}",
                "insertable = false",
                "updatable = false",
            ]
            if col["fk"]["column"] != "id":
                join.append(
                    f"referencedColumnName = {sr.java_string(col['fk']['column'])}"
                )
            fields += [
                "    // Read-only: set the id above; load the row itself when you need it.",
                "    @ManyToOne(fetch = FetchType.LAZY)",
                f"    @JoinColumn({', '.join(join)})",
                f"    private {target} {rel};",
                "",
            ]
            accessors += [
                f"    public {target} get{_cap(rel)}() {{",
                f"        return {rel};",
                "    }",
                "",
            ]
    fields += [
        "    @CreationTimestamp",
        '    @Column(name = "created_at", nullable = false, updatable = false)',
        "    private Instant createdAt;",
        "",
        "    @UpdateTimestamp",
        '    @Column(name = "updated_at", nullable = false)',
        "    private Instant updatedAt;",
        "",
    ]
    accessors += [
        "    public Instant getCreatedAt() {",
        "        return createdAt;",
        "    }",
        "",
        "    public Instant getUpdatedAt() {",
        "        return updatedAt;",
        "    }",
    ]
    if any(table["columns"][c]["type"] == "json" for c in table["column_order"]):
        extra_imports.add(f"import {package}.support.JsonText;")
    lines = [
        f"package {package}.model;",
        "",
        *[f"import jakarta.persistence.{n};" for n in sorted(jpa)],
        *_java_imports(used),
        *[f"import org.hibernate.annotations.{n};" for n in sorted(hibernate)],
        *sorted(extra_imports),
        "",
        "/**",
        f" * {sr.comment(heading)}",
        " *",
        " * Deterministically generated by VengaiCode from the Architecture tab (no AI",
        " * call). The table is created and changed by the Flyway migrations in",
        " * src/main/resources/db/migration/; Hibernate checks this class against it at",
        " * every start (spring.jpa.hibernate.ddl-auto=validate).",
        " */",
        "@Entity",
        f"@Table(name = {sr.java_string(sql_name)})",
        f"public class {name} {{",
        *fields,
        *accessors,
        "",
        f"    // VENGAI:CUSTOM:{slug}_model:start",
        f"    // Add methods to {name} here. A new column belongs in the Architecture tab",
        "    // instead, so a migration adds it to the database.",
        "    // This block is preserved across future regenerations.",
        f"    // VENGAI:CUSTOM:{slug}_model:end",
        "}",
        "",
    ]
    return GeneratedFile(
        path=_path(package, "model", name),
        language="java",
        content="\n".join(lines),
        description=f"Deterministic JPA entity for {table['label']}",
    )


# ─── DTOs ───
def request_file(package: str, table: dict, tables: dict) -> GeneratedFile:
    name = sr.class_name(table)
    used: set[str] = set()
    validation: set[str] = set()
    fields = []
    for c in table["column_order"]:
        _col, base = _column(table, tables, c)
        jtype = sr.java_type(base)
        used.add(jtype)
        constraint = ""
        if base["type"] == "string":
            validation.add("Size")
            constraint = f"@Size(max = {base['length']}) "
        elif base["type"] == "decimal":
            validation.add("Digits")
            whole = db_schema.DECIMAL_PRECISION - db_schema.DECIMAL_SCALE
            constraint = (
                f"@Digits(integer = {whole}, fraction = {db_schema.DECIMAL_SCALE}) "
            )
        fields.append(f"    public Optional<{constraint}{jtype}> {c};")
    lines = [
        f"package {package}.dto;",
        "",
        *[f"import jakarta.validation.constraints.{v};" for v in sorted(validation)],
        *_java_imports(used),
        "import java.util.Optional;",
        "",
        "/**",
        f" * The body of POST and PUT /api/{sr.comment(table['label'])} requests.",
        " * Fields are named exactly as the JSON keys. A field left out is null here; one",
        " * sent as null is Optional.empty() — so PUT can change only what it sends, and",
        " * an explicit null on a required field is refused.",
        " */",
        f"public class {name}Request {{",
        *fields,
        "}",
        "",
    ]
    return GeneratedFile(
        path=_path(package, "dto", f"{name}Request"),
        language="java",
        content="\n".join(lines),
        description=f"Request body for {table['label']}",
    )


def response_file(package: str, table: dict, tables: dict) -> GeneratedFile:
    name = sr.class_name(table)
    used: set[str] = {"Instant"}
    components = ['    @JsonProperty("id") Long id']
    getters = ["            item.getId()"]
    for c in table["column_order"]:
        _col, base = _column(table, tables, c)
        jtype = sr.java_type(base)
        used.add(jtype)
        components.append(
            f"    @JsonProperty({sr.java_string(c)}) {jtype} {sr.java_name(c)}"
        )
        getters.append(f"            item.get{_cap(sr.java_name(c))}()")
    components += [
        '    @JsonProperty("created_at") Instant createdAt',
        '    @JsonProperty("updated_at") Instant updatedAt',
    ]
    getters += ["            item.getCreatedAt()", "            item.getUpdatedAt()"]
    lines = [
        f"package {package}.dto;",
        "",
        "import com.fasterxml.jackson.annotation.JsonProperty;",
        *_java_imports(used),
        f"import {package}.model.{name};",
        "",
        f"/** What the API answers for a {sr.comment(table['label'])} row — keyed by column name. */",
        f"public record {name}Response(",
        ",\n".join(components),
        ") {",
        f"    public static {name}Response from({name} item) {{",
        f"        return new {name}Response(",
        ",\n".join(getters),
        "        );",
        "    }",
        "}",
        "",
    ]
    return GeneratedFile(
        path=_path(package, "dto", f"{name}Response"),
        language="java",
        content="\n".join(lines),
        description=f"Response body for {table['label']}",
    )


# ─── service / controller / repository ───
def _restrict_message(sql_name: str, snapshot: dict) -> str:
    blockers = sorted(
        {
            other["label"]
            for other in snapshot["tables"].values()
            for col in other["columns"].values()
            if col["fk"]
            and col["fk"]["table"] == sql_name
            and col["fk"]["on_delete"] == "restrict"
        }
    )
    if blockers:
        return f"Can't delete this record: {', '.join(blockers)} still refer to it."
    return "Can't delete this record: other records still refer to it."


def service_file(
    package: str, sql_name: str, table: dict, snapshot: dict
) -> GeneratedFile:
    tables = snapshot["tables"]
    name = sr.class_name(table)
    models = {name}
    apply = []
    references = []
    for c in table["column_order"]:
        col, base = _column(table, tables, c)
        setter = f"item.set{_cap(sr.java_name(c))}"
        required = not col["nullable"] and col["default"] is None
        if col["nullable"]:
            apply += [f"        if (body.{c} != null) {setter}(body.{c}.orElse(null));"]
        else:
            apply += [
                f"        if (body.{c} != null) {{",
                f"            if (body.{c}.isEmpty()) errors.add({sr.java_string(c + ': may not be null')});",
                f"            else {setter}(body.{c}.get());",
                "        }"
                + (
                    f" else if (creating) errors.add({sr.java_string(c + ': is required')});"
                    if required
                    else ""
                ),
            ]
        if col["fk"]:
            target_table = tables[col["fk"]["table"]]
            target = sr.class_name(target_table)
            models.add(target)
            ref_field = sr.java_name(col["fk"]["column"])
            references.append(
                f"        if (body.{c} != null && body.{c}.isPresent()) References.require(em, {target}.class, "
                f"{sr.java_string(ref_field)}, body.{c}.get(), {sr.java_string(c)}, "
                f"{sr.java_string(target_table['label'])}, {sr.java_string(col['fk']['column'])});"
            )
    lines = [
        f"package {package}.service;",
        "",
        f"import {package}.dto.{name}Request;",
        f"import {package}.dto.{name}Response;",
        *[f"import {package}.model.{m};" for m in sorted(models)],
        f"import {package}.repository.{name}Repository;",
        f"import {package}.support.ApiException;",
        f"import {package}.support.References;",
        "import jakarta.persistence.EntityManager;",
        "import java.util.ArrayList;",
        "import java.util.List;",
        "import org.springframework.dao.DataIntegrityViolationException;",
        "import org.springframework.data.domain.Sort;",
        "import org.springframework.http.HttpStatus;",
        "import org.springframework.stereotype.Service;",
        "import org.springframework.transaction.annotation.Transactional;",
        "",
        f"/** Everything the {sr.comment(table['label'])} routes do — deterministically generated by VengaiCode. */",
        "@Service",
        "@Transactional",
        f"public class {name}Service {{",
        f"    private static final String LABEL = {sr.java_string(table['label'])};",
        f"    private static final String RESTRICT_MESSAGE = {sr.java_string(_restrict_message(sql_name, snapshot))};",
        "",
        f"    private final {name}Repository repository;",
        "    private final EntityManager em;",
        "",
        f"    public {name}Service({name}Repository repository, EntityManager em) {{",
        "        this.repository = repository;",
        "        this.em = em;",
        "    }",
        "",
        "    @Transactional(readOnly = true)",
        f"    public List<{name}Response> list() {{",
        f'        return repository.findAll(Sort.by("id")).stream().map({name}Response::from).toList();',
        "    }",
        "",
        "    @Transactional(readOnly = true)",
        f"    public {name}Response get(long id) {{",
        f"        return {name}Response.from(find(id));",
        "    }",
        "",
        f"    public {name}Response create({name}Request body) {{",
        f"        {name} item = new {name}();",
        "        apply(item, body, true);",
        "        return save(item);",
        "    }",
        "",
        f"    public {name}Response update(long id, {name}Request body) {{",
        f"        {name} item = find(id);",
        "        apply(item, body, false);",
        "        return save(item);",
        "    }",
        "",
        "    public void delete(long id) {",
        f"        {name} item = find(id);",
        "        try {",
        "            repository.delete(item);",
        "            repository.flush();",
        "        } catch (DataIntegrityViolationException e) {",
        "            // A RESTRICT foreign key still points at this row.",
        "            throw new ApiException(HttpStatus.CONFLICT, RESTRICT_MESSAGE);",
        "        }",
        "    }",
        "",
        f"    private {name} find(long id) {{",
        "        return repository",
        "            .findById(id)",
        '            .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, LABEL + " " + id + " not found."));',
        "    }",
        "",
        f"    private {name}Response save({name} item) {{",
        f"        {name} saved = repository.saveAndFlush(item);",
        "        em.refresh(saved);",
        f"        return {name}Response.from(saved);",
        "    }",
        "",
        f"    private void apply({name} item, {name}Request body, boolean creating) {{",
        "        List<String> errors = new ArrayList<>();",
        *apply,
        '        if (!errors.isEmpty()) throw new ApiException(HttpStatus.BAD_REQUEST, String.join("\\n", errors));',
        *references,
        "    }",
        "}",
        "",
    ]
    return GeneratedFile(
        path=_path(package, "service", f"{name}Service"),
        language="java",
        content="\n".join(lines),
        description=f"CRUD service for {table['label']}",
    )


def controller_file(
    package: str, sql_name: str, table: dict, slug: str
) -> GeneratedFile:
    name = sr.class_name(table)
    lines = [
        f"package {package}.controller;",
        "",
        f"import {package}.dto.{name}Request;",
        f"import {package}.dto.{name}Response;",
        f"import {package}.service.{name}Service;",
        "import jakarta.validation.Valid;",
        "import java.util.List;",
        "import org.springframework.http.HttpStatus;",
        "import org.springframework.web.bind.annotation.DeleteMapping;",
        "import org.springframework.web.bind.annotation.GetMapping;",
        "import org.springframework.web.bind.annotation.PathVariable;",
        "import org.springframework.web.bind.annotation.PostMapping;",
        "import org.springframework.web.bind.annotation.PutMapping;",
        "import org.springframework.web.bind.annotation.RequestBody;",
        "import org.springframework.web.bind.annotation.RequestMapping;",
        "import org.springframework.web.bind.annotation.ResponseStatus;",
        "import org.springframework.web.bind.annotation.RestController;",
        "",
        f"/** REST routes for {sr.comment(table['label'])} — the paths the generated screens call. */",
        "@RestController",
        f"@RequestMapping({sr.java_string('/api/' + sql_name)})",
        f"public class {name}Controller {{",
        f"    private final {name}Service service;",
        "",
        f"    public {name}Controller({name}Service service) {{",
        "        this.service = service;",
        "    }",
        "",
        "    @GetMapping",
        f"    public List<{name}Response> list() {{",
        "        return service.list();",
        "    }",
        "",
        "    @PostMapping",
        "    @ResponseStatus(HttpStatus.CREATED)",
        f"    public {name}Response create(@Valid @RequestBody {name}Request body) {{",
        "        return service.create(body);",
        "    }",
        "",
        '    @GetMapping("/{id}")',
        f'    public {name}Response get(@PathVariable("id") long id) {{',
        "        return service.get(id);",
        "    }",
        "",
        "    // Changes only the fields it sends, like the other generated backends.",
        '    @PutMapping("/{id}")',
        f'    public {name}Response update(@PathVariable("id") long id, @Valid @RequestBody {name}Request body) {{',
        "        return service.update(id, body);",
        "    }",
        "",
        '    @DeleteMapping("/{id}")',
        "    @ResponseStatus(HttpStatus.NO_CONTENT)",
        '    public void delete(@PathVariable("id") long id) {',
        "        service.delete(id);",
        "    }",
        "",
        f"    // VENGAI:CUSTOM:{slug}_routes:start",
        "    // Add custom, non-CRUD endpoints here — this block is preserved across regenerations.",
        f"    // VENGAI:CUSTOM:{slug}_routes:end",
        "}",
        "",
    ]
    return GeneratedFile(
        path=_path(package, "controller", f"{name}Controller"),
        language="java",
        content="\n".join(lines),
        description=f"REST controller for {table['label']}",
    )


def repository_file(package: str, table: dict) -> GeneratedFile:
    name = sr.class_name(table)
    content = f"""package {package}.repository;

import {package}.model.{name};
import org.springframework.data.jpa.repository.JpaRepository;

public interface {name}Repository extends JpaRepository<{name}, Long> {{
}}
"""
    return GeneratedFile(
        path=_path(package, "repository", f"{name}Repository"),
        language="java",
        content=content,
        description=f"Spring Data repository for {table['label']}",
    )


# ─── shared support classes ───
def _support(
    package: str, constraints: list[tuple[str, int, str]]
) -> list[GeneratedFile]:
    entries = ",\n".join(
        f"        new Constraint({sr.java_string(k)}, {s}, {sr.java_string(m)})"
        for k, s, m in sorted(constraints, key=lambda e: -len(e[0]))
    )
    api_exception = f"""package {package}.support;

import org.springframework.http.HttpStatus;

/** An error the API answers with its status and a readable detail. */
public class ApiException extends RuntimeException {{
    private final HttpStatus status;

    public ApiException(HttpStatus status, String detail) {{
        super(detail);
        this.status = status;
    }}

    public HttpStatus getStatus() {{
        return status;
    }}
}}
"""
    api_errors = f"""package {package}.support;

import com.fasterxml.jackson.databind.JsonMappingException;
import java.util.List;
import java.util.regex.Pattern;
import java.util.stream.Collectors;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;

/** Every error as an RFC 7807 problem detail — written by VengaiCode. */
@RestControllerAdvice
public class ApiErrors {{
    private record Constraint(String key, int status, String message) {{
        // H2 names a UNIQUE constraint's index <constraint>_INDEX_<hex id> in its errors.
        Pattern pattern() {{
            return Pattern.compile(Pattern.quote(key) + "(?:_INDEX_[0-9A-F]+)?(?![\\\\w.])");
        }}
    }}

    // What each database constraint means, so a violation comes back as a
    // sentence instead of a raw database error.
    private static final List<Constraint> CONSTRAINTS = List.of(
{entries}
    );

    @ExceptionHandler(ApiException.class)
    public ProblemDetail api(ApiException e) {{
        return ProblemDetail.forStatusAndDetail(e.getStatus(), e.getMessage());
    }}

    @ExceptionHandler(DataIntegrityViolationException.class)
    public ProblemDetail database(DataIntegrityViolationException e) {{
        String text = e.getMostSpecificCause().getMessage();
        for (Constraint c : CONSTRAINTS) {{
            if (c.pattern().matcher(text).find()) {{
                return ProblemDetail.forStatusAndDetail(HttpStatus.valueOf(c.status()), c.message());
            }}
        }}
        return ProblemDetail.forStatusAndDetail(HttpStatus.CONFLICT, "The database refused this change: " + text);
    }}

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ProblemDetail invalid(MethodArgumentNotValidException e) {{
        String detail = e.getBindingResult().getFieldErrors().stream()
            .map(error -> error.getField().replaceAll("\\\\[.*", "") + ": " + error.getDefaultMessage())
            .collect(Collectors.joining("\\n"));
        return ProblemDetail.forStatusAndDetail(HttpStatus.BAD_REQUEST, detail);
    }}

    @ExceptionHandler(HttpMessageNotReadableException.class)
    public ProblemDetail unreadable(HttpMessageNotReadableException e) {{
        if (e.getCause() instanceof JsonMappingException mapping && !mapping.getPath().isEmpty()) {{
            String field = mapping.getPath().get(mapping.getPath().size() - 1).getFieldName();
            return ProblemDetail.forStatusAndDetail(HttpStatus.BAD_REQUEST, field + ": not a valid value for this field");
        }}
        return ProblemDetail.forStatusAndDetail(HttpStatus.BAD_REQUEST, "Send the record as a JSON object.");
    }}

    @ExceptionHandler(MethodArgumentTypeMismatchException.class)
    public ProblemDetail badPath(MethodArgumentTypeMismatchException e) {{
        return ProblemDetail.forStatusAndDetail(HttpStatus.BAD_REQUEST, e.getName() + ": not a valid id");
    }}
}}
"""
    references = f"""package {package}.support;

import jakarta.persistence.EntityManager;
import org.springframework.http.HttpStatus;

/** Foreign keys, checked before a write so a missing parent is a 422 naming the field. */
public final class References {{
    private References() {{
    }}

    public static void require(
        EntityManager em, Class<?> entity, String javaField, Object value, String field, String label, String column
    ) {{
        Long found = em.createQuery(
                "select count(e) from " + entity.getSimpleName() + " e where e." + javaField + " = :value", Long.class)
            .setParameter("value", value)
            .getSingleResult();
        if (found == 0) {{
            throw new ApiException(
                HttpStatus.UNPROCESSABLE_ENTITY, field + ": no row in " + label + " has " + column + " " + value + ".");
        }}
    }}
}}
"""
    json_text = f"""package {package}.support;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.persistence.AttributeConverter;
import jakarta.persistence.Converter;

/** JSON fields, stored as text so every database (and H2) can hold any JSON value. */
@Converter
public class JsonText implements AttributeConverter<Object, String> {{
    private static final ObjectMapper MAPPER = new ObjectMapper();

    public static Object read(String text) {{
        try {{
            return text == null ? null : MAPPER.readValue(text, Object.class);
        }} catch (JsonProcessingException e) {{
            throw new IllegalArgumentException("stored JSON can't be read", e);
        }}
    }}

    @Override
    public String convertToDatabaseColumn(Object value) {{
        try {{
            return value == null ? null : MAPPER.writeValueAsString(value);
        }} catch (JsonProcessingException e) {{
            throw new IllegalArgumentException("value can't be written as JSON", e);
        }}
    }}

    @Override
    public Object convertToEntityAttribute(String text) {{
        return read(text);
    }}
}}
"""
    return [
        GeneratedFile(
            path=_path(package, "support", "ApiException"),
            language="java",
            content=api_exception,
            description="API error type",
        ),
        GeneratedFile(
            path=_path(package, "support", "ApiErrors"),
            language="java",
            content=api_errors,
            description="Turns every error into a readable problem detail",
        ),
        GeneratedFile(
            path=_path(package, "support", "References"),
            language="java",
            content=references,
            description="Foreign key checks",
        ),
        GeneratedFile(
            path=_path(package, "support", "JsonText"),
            language="java",
            content=json_text,
            description="JSON field converter",
        ),
    ]


def backend_files(
    schema: db_schema.ResolvedSchema,
    package: str,
    constraints: list[tuple[str, int, str]],
    headings: dict[str, str],
) -> tuple[list[GeneratedFile], list[GeneratedFile]]:
    snapshot = db_schema.snapshot(schema)
    tables = snapshot["tables"]
    models = [
        entity_file(
            package,
            t.sql_name,
            tables[t.sql_name],
            tables,
            t.slug,
            headings[t.sql_name],
        )
        for t in schema.tables
    ]
    backend: list[GeneratedFile] = []
    for t in schema.tables:
        table = tables[t.sql_name]
        backend += [
            controller_file(package, t.sql_name, table, t.slug),
            service_file(package, t.sql_name, table, snapshot),
            request_file(package, table, tables),
            response_file(package, table, tables),
            repository_file(package, table),
        ]
    backend += _support(package, constraints)
    return models, backend
