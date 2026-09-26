# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Deterministic (no-AI) NestJS + TypeORM (SQLite)
#  ai/codegen_nestjs.py — The NestJS backend codegen_deterministic
#  dispatches to, written the way NestJS asks (knowledge registry): one
#  feature module per table — entity, DTOs, service, controller, module —
#  thin controllers, class-validator DTOs behind the global
#  ValidationPipe, Nest HTTP exceptions for errors. Entities come from
#  the db_schema snapshot through typeorm_render, the same source the
#  migrations do.
#
#  The REST surface matches every other generated backend: /api/<table>
#  and /api/<table>/<id>, PUT changes only the fields it sends, a refused
#  delete is 409, and the database's constraint violations come back as
#  the same sentences (409 duplicate, 422 broken rule). Validation
#  errors are Nest's own 400 {"message": [...]}, which the screens read.
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations

from app.ai import db_schema
from app.ai import typeorm_render as tr
from app.ai.codegen_shared import GeneratedFile
from app.ai.typeorm_render import ts

_VALIDATORS = {
    "string": lambda col: ["IsString()", f"MaxLength({col['length']})"],
    "text": lambda col: ["IsString()"],
    "integer": lambda col: ["IsInt()"],
    "float": lambda col: ["IsNumber()"],
    "decimal": lambda col: [
        f"IsDecimalValue({db_schema.DECIMAL_PRECISION}, {db_schema.DECIMAL_SCALE})"
    ],
    "boolean": lambda col: ["IsBoolean()"],
    "date": lambda col: [
        "IsDateString({ strict: true })",
        "Matches(/^\\d{4}-\\d{2}-\\d{2}$/, { message: '$property must be a date like 2024-01-31' })",
    ],
    "datetime": lambda col: ["IsDateString()"],
    "json": lambda col: ["Allow()"],
}
_DTO_TS_TYPE = {
    "string": "string",
    "text": "string",
    "integer": "number",
    "float": "number",
    "decimal": "number | string",
    "boolean": "boolean",
    "date": "string",
    "datetime": "string",
    "json": "any",
}


def name_problems(schema: db_schema.ResolvedSchema) -> list[str]:
    """Generated class names that would collide (FooService is also the
    class of a table called "foo service"...)."""
    owners: dict[str, str] = {}
    problems = []
    for t in schema.tables:
        for name in (
            t.class_name,
            f"{t.class_name}Service",
            f"{t.class_name}Controller",
            f"{t.class_name}Module",
            f"Create{t.class_name}Dto",
            f"Update{t.class_name}Dto",
        ):
            if name in owners and owners[name] != t.name:
                problems.append(
                    f'Tables "{owners[name]}" and "{t.name}" would both produce a class named {name} — '
                    "rename one of them."
                )
            owners[name] = t.name
    return problems


def _column_type(col: dict, tables: dict) -> dict:
    return tr.fk_column_type(col, tables) if col.get("fk") else col


# ─── entity ───
def entity_file(
    sql_name: str, table: dict, tables: dict, slug: str, heading: str
) -> GeneratedFile:
    name = tr.entity_name(table)
    decorators = {
        "Column",
        "CreateDateColumn",
        "Entity",
        "PrimaryGeneratedColumn",
        "UpdateDateColumn",
    }
    class_decorators = [f"@Entity({{ name: {ts(sql_name)} }})"]
    for uname, cols in tr.uniques(table):
        decorators.add("Unique")
        class_decorators.append(
            f"@Unique({ts(uname)}, [{', '.join(ts(c) for c in cols)}])"
        )
    for cname in table["checks"]:
        decorators.add("Check")
        class_decorators.append(
            f"@Check({ts(cname)}, {ts(tr.check_sql(table, cname))})"
        )
    for iname, cols in tr.indexes(table):
        decorators.add("Index")
        class_decorators.append(
            f"@Index({ts(iname)}, [{', '.join(ts(c) for c in cols)}])"
        )

    imports: dict[str, str] = {}  # class -> module path
    body = ["  @PrimaryGeneratedColumn()", "  id: number;", ""]
    for c in table["column_order"]:
        col = table["columns"][c]
        base = _column_type(col, tables)
        options = [f"type: {ts(tr.column_type(base, migration=False))}"]
        if base["type"] == "string":
            options.append(f"length: {base['length']}")
        if base["type"] == "decimal":
            options += [
                f"precision: {db_schema.DECIMAL_PRECISION}",
                f"scale: {db_schema.DECIMAL_SCALE}",
            ]
        if col["nullable"]:
            options.append("nullable: true")
        default = tr.entity_default(col)
        if default is not None:
            options.append(f"default: {default}")
        ts_type = tr._TS_TYPE[base["type"]] + (" | null" if col["nullable"] else "")
        body += [f"  @Column({{ {', '.join(options)} }})", f"  {c}: {ts_type};", ""]
        if col["fk"]:
            decorators |= {"JoinColumn", "ManyToOne"}
            target = tables[col["fk"]["table"]]
            target_name = tr.entity_name(target)
            if col["fk"]["table"] != sql_name:
                target_slug = tr.file_slug(target)
                imports[target_name] = f"../{target_slug}/{target_slug}.entity"
            join = [
                f"name: {ts(c)}",
                f"foreignKeyConstraintName: {ts(col['fk']['name'])}",
            ]
            if col["fk"]["column"] != "id":
                join.insert(1, f"referencedColumnName: {ts(col['fk']['column'])}")
            on_delete = tr._ON_DELETE[col["fk"]["on_delete"]]
            body += [
                f"  @ManyToOne(() => {target_name}, {{ onDelete: {ts(on_delete)}, nullable: {'true' if col['nullable'] else 'false'} }})",
                f"  @JoinColumn({{ {', '.join(join)} }})",
                f"  {tr.relation_name(c, table)}?: {target_name};",
                "",
            ]
    body += [
        "  @CreateDateColumn({ type: 'datetime' })",
        "  created_at: Date;",
        "",
        "  @UpdateDateColumn({ type: 'datetime' })",
        "  updated_at: Date;",
        "",
        f"  // VENGAI:CUSTOM:{slug}_model:start",
        f"  // Add methods or getters for {name} here. A new column belongs in the Architecture",
        "  // tab instead, so a migration adds it to the database.",
        "  // This block is preserved across future regenerations.",
        f"  // VENGAI:CUSTOM:{slug}_model:end",
    ]
    lines = [
        f"// {tr.comment(heading)}",
        "//",
        "// Deterministically generated by VengaiCode from the Architecture tab (no AI call).",
        "// The table is created and changed by the migrations in src/migrations/; this",
        "// class describes it to TypeORM.",
        f"import {{ {', '.join(sorted(decorators))} }} from 'typeorm';",
    ]
    lines += [
        f"import {{ {cls} }} from '{path}';" for cls, path in sorted(imports.items())
    ]
    lines += ["", *class_decorators, f"export class {name} {{", *body, "}", ""]
    return GeneratedFile(
        path=f"backend/src/{slug}/{slug}.entity.ts",
        language="typescript",
        content="\n".join(lines),
        description=f"Deterministic TypeORM entity for {table['label']}",
    )


# ─── DTOs ───
def _dto_class(
    name: str, table: dict, tables: dict, mode: str, used: set[str]
) -> list[str]:
    lines = [f"export class {name} {{"]
    for c in table["column_order"]:
        col = table["columns"][c]
        base = _column_type(col, tables)
        validators = _VALIDATORS[base["type"]](base)
        required = mode == "create" and not col["nullable"] and col["default"] is None
        if col["nullable"]:
            gate = ["IsOptional()"]
        elif required:
            gate = []
        else:
            # May be left out (the default applies, or the value is kept),
            # but an explicit null is refused before it reaches NOT NULL.
            gate = [f"ValidateIf((o) => o.{c} !== undefined)"]
        for decorator in gate + validators:
            used.add(decorator.split("(")[0])
            lines.append(f"  @{decorator}")
        optional = "" if required else "?"
        null = " | null" if col["nullable"] else ""
        lines += [f"  {c}{optional}: {_DTO_TS_TYPE[base['type']]}{null};", ""]
    if lines[-1] == "":
        lines.pop()
    lines.append("}")
    return lines


def dto_file(table: dict, tables: dict, slug: str) -> GeneratedFile:
    name = tr.entity_name(table)
    used: set[str] = set()
    create = _dto_class(f"Create{name}Dto", table, tables, "create", used)
    update = _dto_class(f"Update{name}Dto", table, tables, "update", used)
    decimal = "IsDecimalValue" in used
    used.discard("IsDecimalValue")
    lines = [
        f"// Request bodies for {tr.comment(table['label'])} — deterministically generated by VengaiCode.",
        "// Checked by the global ValidationPipe (unknown fields are dropped).",
    ]
    if used:
        lines.append(f"import {{ {', '.join(sorted(used))} }} from 'class-validator';")
    if decimal:
        lines.append("import { IsDecimalValue } from '../common/validation';")
    lines += ["", *create, "", *update, ""]
    return GeneratedFile(
        path=f"backend/src/{slug}/{slug}.dto.ts",
        language="typescript",
        content="\n".join(lines),
        description=f"Validated request bodies for {table['label']}",
    )


# ─── service / controller / module ───
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
    sql_name: str, table: dict, snapshot: dict, slug: str
) -> GeneratedFile:
    tables = snapshot["tables"]
    name = tr.entity_name(table)
    imports: dict[str, str] = {}
    references = []
    for c in table["column_order"]:
        col = table["columns"][c]
        if not col["fk"]:
            continue
        target = tables[col["fk"]["table"]]
        target_name = tr.entity_name(target)
        if col["fk"]["table"] != sql_name:
            target_slug = tr.file_slug(target)
            imports[target_name] = f"../{target_slug}/{target_slug}.entity"
        references.append(
            f"  {{ field: {ts(c)}, entity: {target_name}, column: {ts(col['fk']['column'])}, label: {ts(target['label'])} }},"
        )
    lines = [
        f"// Everything the {tr.comment(table['label'])} routes do — deterministically generated by VengaiCode.",
        "import { Injectable, NotFoundException } from '@nestjs/common';",
        "import { InjectRepository } from '@nestjs/typeorm';",
        "import { DataSource, DeepPartial, Repository } from 'typeorm';",
        "import { Reference, checkReferences, removeOrExplain } from '../common/crud';",
        f"import {{ Create{name}Dto, Update{name}Dto }} from './{slug}.dto';",
        f"import {{ {name} }} from './{slug}.entity';",
    ]
    lines += [
        f"import {{ {cls} }} from '{path}';" for cls, path in sorted(imports.items())
    ]
    lines += [
        "",
        "// Foreign keys, checked before a write so a missing parent is a 422 naming the field.",
        "const REFERENCES: Reference[] = [",
        *references,
        "];",
        f"const LABEL = {ts(table['label'])};",
        f"const RESTRICT_MESSAGE = {ts(_restrict_message(sql_name, snapshot))};",
        "",
        "@Injectable()",
        f"export class {name}Service {{",
        "  constructor(",
        f"    @InjectRepository({name}) private readonly repo: Repository<{name}>,",
        "    private readonly dataSource: DataSource,",
        "  ) {}",
        "",
        f"  list(): Promise<{name}[]> {{",
        "    return this.repo.find({ order: { id: 'ASC' } });",
        "  }",
        "",
        f"  async get(id: number): Promise<{name}> {{",
        "    const item = await this.repo.findOneBy({ id });",
        "    if (!item) throw new NotFoundException(`${LABEL} ${id} not found.`);",
        "    return item;",
        "  }",
        "",
        f"  async create(dto: Create{name}Dto): Promise<{name}> {{",
        "    await checkReferences(this.dataSource, dto, REFERENCES);",
        "    // Validated values; TypeORM stores date strings as dates itself.",
        f"    const saved = await this.repo.save(this.repo.create(dto as unknown as DeepPartial<{name}>));",
        "    return this.get(saved.id);",
        "  }",
        "",
        f"  async update(id: number, dto: Update{name}Dto): Promise<{name}> {{",
        "    await this.get(id);",
        "    await checkReferences(this.dataSource, dto, REFERENCES);",
        "    if (Object.keys(dto).length) await this.repo.update(id, dto as any);",
        "    return this.get(id);",
        "  }",
        "",
        "  async remove(id: number): Promise<void> {",
        "    await this.get(id);",
        "    await removeOrExplain(() => this.repo.delete(id), RESTRICT_MESSAGE);",
        "  }",
        "}",
        "",
    ]
    return GeneratedFile(
        path=f"backend/src/{slug}/{slug}.service.ts",
        language="typescript",
        content="\n".join(lines),
        description=f"CRUD service for {table['label']}",
    )


def controller_file(sql_name: str, table: dict, slug: str) -> GeneratedFile:
    name = tr.entity_name(table)
    lines = [
        f"// REST routes for {tr.comment(table['label'])} — deterministically generated by VengaiCode.",
        f"// Everything outside the VENGAI:CUSTOM:{slug}_routes block is rewritten on regeneration.",
        "import { Body, Controller, Delete, Get, HttpCode, Param, ParseIntPipe, Post, Put } from '@nestjs/common';",
        f"import {{ Create{name}Dto, Update{name}Dto }} from './{slug}.dto';",
        f"import {{ {name}Service }} from './{slug}.service';",
        "",
        "// Under the global /api prefix (src/main.ts) — the paths the generated screens call.",
        f"@Controller({ts(sql_name)})",
        f"export class {name}Controller {{",
        f"  constructor(private readonly service: {name}Service) {{}}",
        "",
        "  @Get()",
        "  list() {",
        "    return this.service.list();",
        "  }",
        "",
        "  @Post()",
        f"  create(@Body() dto: Create{name}Dto) {{",
        "    return this.service.create(dto);",
        "  }",
        "",
        "  @Get(':id')",
        "  get(@Param('id', ParseIntPipe) id: number) {",
        "    return this.service.get(id);",
        "  }",
        "",
        "  // Changes only the fields it sends, like the other generated backends.",
        "  @Put(':id')",
        f"  update(@Param('id', ParseIntPipe) id: number, @Body() dto: Update{name}Dto) {{",
        "    return this.service.update(id, dto);",
        "  }",
        "",
        "  @Delete(':id')",
        "  @HttpCode(204)",
        "  remove(@Param('id', ParseIntPipe) id: number) {",
        "    return this.service.remove(id);",
        "  }",
        "",
        f"  // VENGAI:CUSTOM:{slug}_routes:start",
        "  // Add custom, non-CRUD routes here — this block is preserved across regenerations.",
        f"  // VENGAI:CUSTOM:{slug}_routes:end",
        "}",
        "",
    ]
    return GeneratedFile(
        path=f"backend/src/{slug}/{slug}.controller.ts",
        language="typescript",
        content="\n".join(lines),
        description=f"REST controller for {table['label']}",
    )


def module_file(table: dict, slug: str) -> GeneratedFile:
    name = tr.entity_name(table)
    content = f"""import {{ Module }} from '@nestjs/common';
import {{ TypeOrmModule }} from '@nestjs/typeorm';
import {{ {name}Controller }} from './{slug}.controller';
import {{ {name} }} from './{slug}.entity';
import {{ {name}Service }} from './{slug}.service';

@Module({{
  imports: [TypeOrmModule.forFeature([{name}])],
  controllers: [{name}Controller],
  providers: [{name}Service],
}})
export class {name}Module {{}}
"""
    return GeneratedFile(
        path=f"backend/src/{slug}/{slug}.module.ts",
        language="typescript",
        content=content,
        description=f"Feature module for {table['label']}",
    )


# ─── shared ───
_CRUD_TS = """// What every generated service shares — written by VengaiCode.
import { ConflictException, UnprocessableEntityException } from '@nestjs/common';
import { DataSource, EntityTarget, ObjectLiteral, QueryFailedError } from 'typeorm';

export interface Reference {
  field: string;
  entity: EntityTarget<ObjectLiteral>;
  column: string;
  label: string;
}

/** A 422 naming the field when a foreign key points at a row that doesn't exist. */
export async function checkReferences(dataSource: DataSource, dto: object, references: Reference[]): Promise<void> {
  for (const ref of references) {
    const value = (dto as Record<string, unknown>)[ref.field];
    if (value === undefined || value === null) continue;
    const found = await dataSource.getRepository(ref.entity).existsBy({ [ref.column]: value });
    if (!found) {
      throw new UnprocessableEntityException(`${ref.field}: no row in ${ref.label} has ${ref.column} ${JSON.stringify(value)}.`);
    }
  }
}

/** Deletes, or answers 409 when a RESTRICT foreign key still points at the row. */
export async function removeOrExplain(remove: () => Promise<unknown>, restrictMessage: string): Promise<void> {
  try {
    await remove();
  } catch (error) {
    if (error instanceof QueryFailedError && /foreign key/i.test(error.message)) {
      throw new ConflictException(restrictMessage);
    }
    throw error;
  }
}
"""

_VALIDATION_TS = """// Decimal fields: a number, or a numeric string like "12.50" (what the screens
// send), with at most the digits the column stores — written by VengaiCode.
import { ValidationOptions, registerDecorator } from 'class-validator';

export function IsDecimalValue(precision: number, scale: number, options?: ValidationOptions) {
  const whole = precision - scale;
  const pattern = new RegExp(`^-?\\\\d{1,${whole}}(\\\\.\\\\d{1,${scale}})?$`);
  return (object: object, propertyName: string) =>
    registerDecorator({
      name: 'isDecimalValue',
      target: object.constructor,
      propertyName,
      options: {
        message: `$property must be a number with at most ${whole} digits before the point and ${scale} after it`,
        ...options,
      },
      validator: {
        validate: (value: unknown) =>
          (typeof value === 'number' && Number.isFinite(value) && pattern.test(String(value))) ||
          (typeof value === 'string' && pattern.test(value)),
      },
    });
}
"""


def _database_errors_ts(constraints: list[tuple[str, int, str]]) -> str:
    entries = "\n".join(
        f"  [{ts(k)}, {s}, {ts(m)}],"
        for k, s, m in sorted(constraints, key=lambda e: -len(e[0]))
    )
    return f"""// Readable answers for what the database refuses — written by VengaiCode.
import {{ ArgumentsHost, Catch, ExceptionFilter }} from '@nestjs/common';
import {{ QueryFailedError }} from 'typeorm';

// What each database constraint means, so a violation comes back as a sentence
// instead of a raw database error: [text to find, status, message].
const CONSTRAINTS: [string, number, string][] = [
{entries}
];

const ERRORS: Record<number, string> = {{ 409: 'Conflict', 422: 'Unprocessable Entity' }};

function escape(text: string): string {{
  return text.replace(/[.*+?^${{}}()|[\\]\\\\]/g, '\\\\$&');
}}

@Catch(QueryFailedError)
export class DatabaseErrorFilter implements ExceptionFilter {{
  catch(error: QueryFailedError, host: ArgumentsHost) {{
    const response = host.switchToHttp().getResponse();
    let status = 409;
    let message = `The database refused this change: ${{error.message}}`;
    for (const [key, code, text] of CONSTRAINTS) {{
      if (new RegExp(escape(key) + '(?![\\\\w.])').test(error.message)) {{
        status = code;
        message = text;
        break;
      }}
    }}
    response.status(status).json({{ statusCode: status, message, error: ERRORS[status] }});
  }}
}}
"""


def backend_files(
    schema: db_schema.ResolvedSchema,
    constraints: list[tuple[str, int, str]],
    headings: dict[str, str],
) -> tuple[list[GeneratedFile], list[GeneratedFile]]:
    snapshot = db_schema.snapshot(schema)
    tables = snapshot["tables"]
    models = [
        entity_file(
            t.sql_name, tables[t.sql_name], tables, t.slug, headings[t.sql_name]
        )
        for t in schema.tables
    ]
    backend: list[GeneratedFile] = []
    for t in schema.tables:
        table = tables[t.sql_name]
        backend += [
            controller_file(t.sql_name, table, t.slug),
            service_file(t.sql_name, table, snapshot, t.slug),
            dto_file(table, tables, t.slug),
            module_file(table, t.slug),
        ]
    backend += [
        GeneratedFile(
            path="backend/src/common/crud.ts",
            language="typescript",
            content=_CRUD_TS,
            description="Shared CRUD helpers (reference checks, refused deletes)",
        ),
        GeneratedFile(
            path="backend/src/common/database-errors.ts",
            language="typescript",
            content=_database_errors_ts(constraints),
            description="Turns database constraint errors into readable API answers",
        ),
        GeneratedFile(
            path="backend/src/common/validation.ts",
            language="typescript",
            content=_VALIDATION_TS,
            description="Decimal field validator",
        ),
    ]
    return models, backend
