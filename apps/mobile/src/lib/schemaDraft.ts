// ─── Architecture schema — editor draft helpers ───
//
// Pure functions behind the typed table editor on the Architecture
// screen (app/(app)/project/[id]/architecture.tsx), kept out of the
// components so they can be unit-tested (schemaDraft.test.ts).
//
// The draft IS the wire format (DatabaseTable with every array present),
// on purpose: the backend's SchemaIssue.index points into this table's
// key_fields / field_specs / foreign_keys / checks / indexes arrays, so a
// live-validation issue can be pinned to the exact row that caused it
// only if those arrays go out in the same order they sit in the editor.
// The one exception is seed rows — fully blank rows are left out of the
// payload — so draftToPayload() hands back an index map for them.
//
// Field and table names are matched the way the backend matches them
// (db_schema.py: exact name first, then the snake_case slug), so an
// AI-authored "Price" field spec still lines up with a "price" field.
//
// A port of the desktop app's copy
// (apps/desktop/src/screens/architecture/schemaDraft.ts), identical below
// this header so a rename or removal propagates exactly the same way in
// both apps — change the two together (their tests are the same too).

import {
  CheckConstraint,
  DatabaseTable,
  DraftTable,
  FieldSpec,
  FieldType,
  FIELD_TYPES,
  ForeignKey,
  IMPLICIT_COLUMNS,
  IndexSpec,
  OnDeleteRule,
  ResolvedTable,
  SchemaIssue,
} from "./schemaTypes";

// ─── Names ───

/** Port of codegen_shared._slug(): the physical column / table slug. */
export function slug(name: string): string {
  const cleaned = (name || "item")
    .replace(/[^a-zA-Z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .toLowerCase();
  return cleaned || "item";
}

/** Port of db_schema.table_sql_name(): plural slug = table/collection. */
export function tableSqlName(name: string): string {
  const s = slug(name);
  return s.endsWith("s") ? s : `${s}s`;
}

export function sameField(a: string | undefined, b: string | undefined): boolean {
  const ta = (a ?? "").trim();
  const tb = (b ?? "").trim();
  // slug("") is "item" — never let two blanks match a real "item" field.
  if (!ta || !tb) return ta === tb;
  return ta === tb || slug(ta) === slug(tb);
}

/** How the backend resolves foreign_keys.references_table: exact name,
 *  or the same slug, or the same physical (plural) table name. */
export function sameTable(a: string | undefined, b: string | undefined): boolean {
  const ta = (a ?? "").trim();
  const tb = (b ?? "").trim();
  if (!ta || !tb) return false;
  return ta === tb || slug(ta) === slug(tb) || tableSqlName(ta) === tableSqlName(tb);
}

export function isImplicitField(name: string): boolean {
  return !!name.trim() && IMPLICIT_COLUMNS.includes(slug(name));
}

const IDENTIFIER_RE = /^[a-z][a-z0-9_]*$/;

// ─── By-name type inference (port of db_schema.classify_field) ───
// Only used for the "Auto (<type>)" label until the backend's live
// validation answers with the authoritative resolved type.
const CATEGORY_RULES: [RegExp, FieldType][] = [
  [/email/, "string"],
  [/url|link|href|website/, "string"],
  [/price|amount|total|cost|rating|score|percent|rate|weight|latitude|longitude/, "float"],
  [/count|quantity|qty|number|num|age|year|stock|inventory|duration/, "integer"],
  [/^is_|^has_/, "boolean"],
  [/_at$|_date$|^date|^time|timestamp/, "datetime"],
  [/description|bio|notes|content|body|summary|address/, "text"],
];

export function inferFieldType(fieldName: string): FieldType {
  const lowered = fieldName.toLowerCase();
  for (const [pattern, type] of CATEGORY_RULES) {
    if (pattern.test(lowered)) return type;
  }
  return "string";
}

// ─── Lookups ───

export function findSpec(table: DraftTable, field: string): FieldSpec | undefined {
  return table.field_specs.find((s) => sameField(s.name, field));
}

export function findFk(table: DraftTable, field: string): ForeignKey | undefined {
  return table.foreign_keys.find((fk) => sameField(fk.field, field));
}

export function fkTargetsId(fk: ForeignKey | undefined): boolean {
  return !!fk && slug(fk.references_field || "id") === "id";
}

/** What "Auto" resolves to for a field: the backend's own answer when
 *  live validation has one, otherwise the same rules computed locally
 *  (a link to an id is an integer; a link to another field takes that
 *  field's type; anything else is inferred from the name). */
export function autoFieldType(
  tables: DraftTable[],
  tableIndex: number,
  field: string,
  resolved?: ResolvedTable
): string {
  const col = resolved?.columns.find((c) => sameField(c.name, field));
  if (col && !col.declared) return col.type;
  const table = tables[tableIndex];
  const fk = table ? findFk(table, field) : undefined;
  if (fk) {
    if (fkTargetsId(fk)) return "integer";
    const target = tables.find((t) => sameTable(t.name, fk.references_table));
    const refField = fk.references_field || "id";
    const declared = target ? findSpec(target, refField)?.type : null;
    return declared || inferFieldType(refField);
  }
  return inferFieldType(field);
}

// ─── Values ───

function isBlank(value: unknown): boolean {
  return value === null || value === undefined || (typeof value === "string" && value.trim() === "");
}

/** JSON values are edited as JSON text. The backend json.loads() any
 *  string it gets for a json column, so a stored JSON *string* value has
 *  to go back quoted — while text that already parses is kept as typed. */
function jsonToText(value: unknown): string {
  if (typeof value === "string") {
    try {
      JSON.parse(value);
      return value;
    } catch {
      return JSON.stringify(value);
    }
  }
  return JSON.stringify(value);
}

/** A stored default or seed value as the text shown in an input. */
export function valueToText(value: unknown, type?: string): string {
  if (value === null || value === undefined) return "";
  if (type === "json") return jsonToText(value);
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** A resolved default (storage form) for the read-only view. */
export function describeDefault(value: unknown, type: string): string {
  if (value === null || value === undefined) return "";
  if ((value === "now" && type === "datetime") || (value === "today" && type === "date")) {
    return value;
  }
  if (type === "string" || type === "text") return `"${String(value)}"`;
  if (type === "json") return JSON.stringify(value);
  return String(value);
}

// ─── Field specs: only emitted when something is non-default ───

export function normalizeSpec(spec: FieldSpec): FieldSpec {
  const rawType = typeof spec.type === "string" ? spec.type.trim().toLowerCase() : null;
  return {
    name: spec.name,
    type: rawType && rawType !== "auto" ? (rawType as FieldType) : null,
    nullable: spec.nullable !== false,
    default: isBlank(spec.default) ? null : spec.default,
    unique: !!spec.unique,
  };
}

/** A spec that declares nothing (auto type, optional, no default, not
 *  unique) is exactly the same as having no spec at all. */
export function isNoopSpec(spec: FieldSpec): boolean {
  const n = normalizeSpec(spec);
  return !n.type && n.nullable !== false && n.default === null && !n.unique;
}

export function upsertFieldSpec(table: DraftTable, field: string, patch: Partial<FieldSpec>): DraftTable {
  const idx = table.field_specs.findIndex((s) => sameField(s.name, field));
  const base: FieldSpec =
    idx >= 0
      ? table.field_specs[idx]!
      : { name: field, type: null, nullable: true, default: null, unique: false };
  const next = normalizeSpec({ ...base, ...patch, name: base.name });
  const specs = [...table.field_specs];
  if (isNoopSpec(next)) {
    if (idx >= 0) specs.splice(idx, 1);
  } else if (idx >= 0) {
    specs[idx] = next;
  } else {
    specs.push(next);
  }
  return { ...table, field_specs: specs };
}

/** Required = NOT NULL. ON DELETE SET NULL can't work on a required
 *  column, so turning Required on moves such a link to RESTRICT (the rule
 *  that, like SET NULL, never deletes the child rows). */
export function setFieldRequired(table: DraftTable, field: string, required: boolean): DraftTable {
  let next = upsertFieldSpec(table, field, { nullable: !required });
  if (required) {
    next = {
      ...next,
      foreign_keys: next.foreign_keys.map((fk) =>
        sameField(fk.field, field) && fk.on_delete === "set_null" ? { ...fk, on_delete: "restrict" } : fk
      ),
    };
  }
  return next;
}

// ─── Foreign keys ───

/** Links a field to another table (or unlinks it with `target` null).
 *  Linking to a table's id also clears a conflicting declared type (an
 *  id link is always an integer) and any seed values for the field —
 *  ids are assigned by the database, so seed data can't set them. */
export function setFieldLink(
  table: DraftTable,
  field: string,
  target: { table: string; onDelete?: OnDeleteRule } | null
): DraftTable {
  const idx = table.foreign_keys.findIndex((fk) => sameField(fk.field, field));
  if (target === null) {
    if (idx < 0) return table;
    return { ...table, foreign_keys: table.foreign_keys.filter((_, i) => i !== idx) };
  }
  const existing = idx >= 0 ? table.foreign_keys[idx] : undefined;
  const keepsTarget = !!existing && sameTable(existing.references_table, target.table);
  const required = findSpec(table, field)?.nullable === false;
  let onDelete: string = target.onDelete ?? existing?.on_delete ?? "cascade";
  if (required && onDelete === "set_null") onDelete = "restrict";
  const fk: ForeignKey = {
    field: existing?.field ?? field,
    references_table: target.table,
    references_field: keepsTarget ? existing?.references_field || "id" : "id",
    on_delete: onDelete,
  };
  const fks = [...table.foreign_keys];
  if (idx >= 0) fks[idx] = fk;
  else fks.push(fk);
  let next: DraftTable = { ...table, foreign_keys: fks };

  if (fkTargetsId(fk)) {
    const spec = findSpec(next, field);
    if (spec?.type && spec.type !== "integer") next = upsertFieldSpec(next, field, { type: null });
    next = {
      ...next,
      seed_rows: next.seed_rows.map((row) => omitKey(row, field)),
    };
  }
  return next;
}

export function setFieldOnDelete(table: DraftTable, field: string, rule: OnDeleteRule): DraftTable {
  return {
    ...table,
    foreign_keys: table.foreign_keys.map((fk) => (sameField(fk.field, field) ? { ...fk, on_delete: rule } : fk)),
  };
}

// ─── Check expressions ───

const CHECK_KEYWORDS = new Set(["and", "or", "not", "is", "null", "in", "between", "like", "true", "false"]);

/** Renames a field inside a check expression, token by token: only bare
 *  identifiers are touched — never text inside 'quotes', keywords, or a
 *  function name like LENGTH( — so "name <> 'name'" renames just the
 *  column. Mirrors check_expr.py's tokenizer, which resolves identifiers
 *  by their slug. */
export function renameInExpression(expression: string, oldName: string, newName: string): string {
  if (!oldName.trim() || !newName.trim()) return expression;
  const oldSlug = slug(oldName);
  const newSlug = slug(newName);
  if (oldSlug === newSlug || !IDENTIFIER_RE.test(newSlug)) return expression;

  let out = "";
  let i = 0;
  while (i < expression.length) {
    const ch = expression[i]!;
    if (ch === "'" || ch === '"') {
      // A quoted run: '' inside single quotes is an escaped quote.
      let j = i + 1;
      while (j < expression.length) {
        if (expression[j] === ch) {
          if (ch === "'" && expression[j + 1] === "'") {
            j += 2;
            continue;
          }
          j += 1;
          break;
        }
        j += 1;
      }
      out += expression.slice(i, j);
      i = j;
      continue;
    }
    const number = /^\d+(?:\.\d+)?/.exec(expression.slice(i));
    if (number) {
      out += number[0];
      i += number[0].length;
      continue;
    }
    const word = /^[A-Za-z_][A-Za-z0-9_]*/.exec(expression.slice(i));
    if (word) {
      const text = word[0];
      const isCall = /^\s*\(/.test(expression.slice(i + text.length));
      const matches = !isCall && !CHECK_KEYWORDS.has(text.toLowerCase()) && slug(text) === oldSlug;
      out += matches ? newSlug : text;
      i += text.length;
      continue;
    }
    out += ch;
    i += 1;
  }
  return out;
}

// ─── Structural edits (fields / tables) ───

export type EditResult<T> = { ok: true; value: T } | { ok: false; error: string };

function omitKey<V>(row: Record<string, V>, field: string): Record<string, V> {
  return Object.fromEntries(Object.entries(row).filter(([k]) => !sameField(k, field)));
}

function renameKey<V>(row: Record<string, V>, oldName: string, newName: string): Record<string, V> {
  return Object.fromEntries(Object.entries(row).map(([k, v]) => [sameField(k, oldName) ? newName : k, v]));
}

export function emptyDraftTable(): DraftTable {
  return {
    name: "",
    purpose: "",
    key_fields: [],
    field_specs: [],
    foreign_keys: [],
    checks: [],
    indexes: [],
    seed_rows: [],
  };
}

export function addField(table: DraftTable, name: string): EditResult<DraftTable> {
  const trimmed = name.trim();
  if (!trimmed) return { ok: false, error: "Type a field name first." };
  const clash = table.key_fields.find((f) => sameField(f, trimmed));
  if (clash) {
    return { ok: false, error: `This table already has a field "${clash}".` };
  }
  return { ok: true, value: { ...table, key_fields: [...table.key_fields, trimmed] } };
}

/** Renames a field everywhere it's referenced: its field spec, its own
 *  foreign key, index entries, seed-row keys, identifiers in check
 *  expressions, and any foreign key (in any table) that targets this
 *  exact field instead of the table's id. */
export function renameField(
  tables: DraftTable[],
  tableIndex: number,
  fieldIndex: number,
  newName: string
): EditResult<DraftTable[]> {
  const table = tables[tableIndex];
  const oldName = table?.key_fields[fieldIndex];
  if (!table || oldName === undefined) return { ok: false, error: "That field no longer exists." };
  const trimmed = newName.trim();
  if (!trimmed) return { ok: false, error: "A field needs a name — use × to remove it instead." };
  if (trimmed === oldName) return { ok: true, value: tables };
  const clash = table.key_fields.find((f, j) => j !== fieldIndex && sameField(f, trimmed));
  if (clash) return { ok: false, error: `This table already has a field "${clash}".` };

  const keyFields = table.key_fields.map((f, j) => (j === fieldIndex ? trimmed : f));
  // id / created_at / updated_at exist whether or not they're listed, so
  // an index or check naming one still means the automatic column.
  if (isImplicitField(oldName) || !oldName.trim()) {
    return {
      ok: true,
      value: tables.map((t, i) => (i === tableIndex ? { ...t, key_fields: keyFields } : t)),
    };
  }

  const renamed: DraftTable = {
    ...table,
    key_fields: keyFields,
    field_specs: table.field_specs.map((s) => (sameField(s.name, oldName) ? { ...s, name: trimmed } : s)),
    foreign_keys: table.foreign_keys.map((fk) => (sameField(fk.field, oldName) ? { ...fk, field: trimmed } : fk)),
    indexes: table.indexes.map((ix) => ({
      ...ix,
      fields: ix.fields.map((f) => (sameField(f, oldName) ? trimmed : f)),
    })),
    checks: table.checks.map((c) => ({ ...c, expression: renameInExpression(c.expression, oldName, trimmed) })),
    seed_rows: table.seed_rows.map((row) => renameKey(row, oldName, trimmed)),
  };

  return {
    ok: true,
    value: tables.map((t, i) => {
      const base = i === tableIndex ? renamed : t;
      return {
        ...base,
        foreign_keys: base.foreign_keys.map((fk) =>
          sameTable(fk.references_table, table.name) &&
          !fkTargetsId(fk) &&
          sameField(fk.references_field, oldName)
            ? { ...fk, references_field: trimmed }
            : fk
        ),
      };
    }),
  };
}

/** Removes a field with its spec, its foreign key, its index entries
 *  (an index left with no fields goes too) and its seed values. Checks
 *  that mention it are left for validation to flag: silently deleting a
 *  business rule would be worse than asking the user to fix it. */
export function removeField(table: DraftTable, fieldIndex: number): DraftTable {
  const name = table.key_fields[fieldIndex];
  if (name === undefined) return table;
  const keyFields = table.key_fields.filter((_, j) => j !== fieldIndex);
  if (isImplicitField(name) || !name.trim()) return { ...table, key_fields: keyFields };
  return {
    ...table,
    key_fields: keyFields,
    field_specs: table.field_specs.filter((s) => !sameField(s.name, name)),
    foreign_keys: table.foreign_keys.filter((fk) => !sameField(fk.field, name)),
    indexes: table.indexes
      .map((ix) => ({ ...ix, fields: ix.fields.filter((f) => !sameField(f, name)), hadFields: ix.fields.length > 0 }))
      .filter((ix) => ix.fields.length > 0 || !ix.hadFields)
      .map(({ hadFields: _hadFields, ...ix }) => ix),
    seed_rows: table.seed_rows.map((row) => omitKey(row, name)),
  };
}

/** Renames a table and repoints every foreign key (in any table,
 *  including a self-reference) that referenced it by its old name. */
export function renameTable(tables: DraftTable[], tableIndex: number, newName: string): EditResult<DraftTable[]> {
  const table = tables[tableIndex];
  if (!table) return { ok: false, error: "That table no longer exists." };
  const oldName = table.name.trim();
  const trimmed = newName.trim();
  if (!trimmed) {
    if (!oldName) return { ok: true, value: tables };
    return { ok: false, error: "A table needs a name — use × to remove it instead." };
  }
  if (trimmed === table.name) return { ok: true, value: tables };
  const clash = tables.find((t, i) => i !== tableIndex && t.name.trim() && sameTable(t.name, trimmed));
  if (clash) {
    return {
      ok: false,
      error: `"${trimmed}" would be stored in the same database table as "${clash.name}" — pick a distinct name.`,
    };
  }
  return {
    ok: true,
    value: tables.map((t, i) => {
      const base = i === tableIndex ? { ...t, name: trimmed } : t;
      if (!oldName) return base;
      return {
        ...base,
        foreign_keys: base.foreign_keys.map((fk) =>
          sameTable(fk.references_table, oldName) ? { ...fk, references_table: trimmed } : fk
        ),
      };
    }),
  };
}

/** Removes a table; links that pointed at it become plain fields again
 *  (a dangling link could never be generated). */
export function removeTable(tables: DraftTable[], tableIndex: number): DraftTable[] {
  const removed = tables[tableIndex];
  const rest = tables.filter((_, i) => i !== tableIndex);
  if (!removed || !removed.name.trim()) return rest;
  return rest.map((t) => ({
    ...t,
    foreign_keys: t.foreign_keys.filter(
      (fk) => !sameTable(fk.references_table, removed.name) || rest.some((r) => sameTable(r.name, fk.references_table))
    ),
  }));
}

// ─── Checks / indexes / seed rows ───

export function addCheck(table: DraftTable): DraftTable {
  return { ...table, checks: [...table.checks, { name: "", expression: "" }] };
}

export function updateCheck(table: DraftTable, index: number, patch: Partial<CheckConstraint>): DraftTable {
  return { ...table, checks: table.checks.map((c, i) => (i === index ? { ...c, ...patch } : c)) };
}

export function removeCheck(table: DraftTable, index: number): DraftTable {
  return { ...table, checks: table.checks.filter((_, i) => i !== index) };
}

/** Fields an index can use: the automatic id first, then the table's own
 *  fields in order, then the automatic timestamps. */
export function indexFieldChoices(table: DraftTable): string[] {
  const own = table.key_fields.filter((f) => f.trim() && !isImplicitField(f));
  const seen = new Set<string>();
  return ["id", ...own, "created_at", "updated_at"].filter((f) => {
    const key = slug(f);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function addIndex(table: DraftTable): DraftTable {
  return { ...table, indexes: [...table.indexes, { fields: [], unique: false }] };
}

/** Column order matters in a composite index, so a field is appended in
 *  the order it's picked; picking it again takes it out. */
export function toggleIndexField(table: DraftTable, index: number, field: string): DraftTable {
  return {
    ...table,
    indexes: table.indexes.map((ix, i) => {
      if (i !== index) return ix;
      const has = ix.fields.some((f) => sameField(f, field));
      return { ...ix, fields: has ? ix.fields.filter((f) => !sameField(f, field)) : [...ix.fields, field] };
    }),
  };
}

export function updateIndex(table: DraftTable, index: number, patch: Partial<IndexSpec>): DraftTable {
  return { ...table, indexes: table.indexes.map((ix, i) => (i === index ? { ...ix, ...patch } : ix)) };
}

export function removeIndex(table: DraftTable, index: number): DraftTable {
  return { ...table, indexes: table.indexes.filter((_, i) => i !== index) };
}

/** Seed-row columns: every field except the automatic ones and links to
 *  another table's id (the database assigns ids, so seed data can't). */
export function seedColumns(table: DraftTable): string[] {
  const seen = new Set<string>();
  return table.key_fields.filter((f) => {
    if (!f.trim() || isImplicitField(f) || fkTargetsId(findFk(table, f))) return false;
    const key = slug(f);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function addSeedRow(table: DraftTable): DraftTable {
  return { ...table, seed_rows: [...table.seed_rows, {}] };
}

export function removeSeedRow(table: DraftTable, index: number): DraftTable {
  return { ...table, seed_rows: table.seed_rows.filter((_, i) => i !== index) };
}

export function setSeedCell(table: DraftTable, rowIndex: number, field: string, value: string): DraftTable {
  return {
    ...table,
    seed_rows: table.seed_rows.map((row, i) => {
      if (i !== rowIndex) return row;
      const cleared = omitKey(row, field);
      return value === "" ? cleared : { ...cleared, [field]: value };
    }),
  };
}

export function seedCell(row: Record<string, string>, field: string): string {
  const key = Object.keys(row).find((k) => sameField(k, field));
  return key === undefined ? "" : row[key] ?? "";
}

export function isBlankSeedRow(row: Record<string, string>): boolean {
  return Object.values(row).every((v) => v.trim() === "");
}

// ─── Saved table <-> draft <-> request payload ───

/** Opens a saved table for editing: every array present, specs that
 *  declare nothing dropped (so field_specs positions stay stable while
 *  editing), and defaults/seed values turned into the text the inputs
 *  show. `resolved` supplies column types for JSON values. */
export function tableToDraft(table: DatabaseTable, resolved?: ResolvedTable): DraftTable {
  const typeOf = (field: string): string | undefined =>
    resolved?.columns.find((c) => sameField(c.name, field))?.type;
  const specs = (table.field_specs ?? [])
    .map(normalizeSpec)
    .filter((s) => !isNoopSpec(s))
    .map((s) => ({
      ...s,
      default:
        s.default === null || typeof s.default === "boolean"
          ? s.default
          : valueToText(s.default, s.type ?? typeOf(s.name)),
    }));
  return {
    name: table.name ?? "",
    purpose: table.purpose ?? "",
    key_fields: [...(table.key_fields ?? [])],
    field_specs: specs,
    foreign_keys: (table.foreign_keys ?? []).map((fk) => ({
      field: fk.field,
      references_table: fk.references_table,
      references_field: fk.references_field || "id",
      on_delete: fk.on_delete || "cascade",
    })),
    checks: (table.checks ?? []).map((c) => ({ name: c.name ?? "", expression: c.expression ?? "" })),
    indexes: (table.indexes ?? []).map((ix) => ({ fields: [...(ix.fields ?? [])], unique: !!ix.unique })),
    seed_rows: (table.seed_rows ?? []).map((row) => {
      const out: Record<string, string> = {};
      for (const [k, v] of Object.entries(row ?? {})) {
        const text = valueToText(v, typeOf(k));
        if (text !== "") out[k] = text;
      }
      return out;
    }),
  };
}

export interface DraftPayload {
  tables: DatabaseTable[];
  /** seedIndexMaps[table][payloadRow] = draft row — fully blank seed rows
   *  aren't sent, so a seed_row issue's index needs translating back. */
  seedIndexMaps: number[][];
}

/** The request body form of the draft. Blank seed cells are omitted and
 *  fully blank seed rows dropped; every other array keeps its order so
 *  issue positions match the editor. */
export function draftToPayload(tables: DraftTable[]): DraftPayload {
  const seedIndexMaps: number[][] = [];
  const out = tables.map((t) => {
    const map: number[] = [];
    const seedRows: Record<string, string>[] = [];
    t.seed_rows.forEach((row, i) => {
      const kept = Object.fromEntries(Object.entries(row).filter(([, v]) => v.trim() !== ""));
      if (Object.keys(kept).length === 0) return;
      map.push(i);
      seedRows.push(kept);
    });
    seedIndexMaps.push(map);
    return {
      name: t.name,
      purpose: t.purpose,
      key_fields: t.key_fields,
      field_specs: t.field_specs.map(normalizeSpec),
      foreign_keys: t.foreign_keys,
      checks: t.checks,
      indexes: t.indexes.map((ix) => ({ fields: ix.fields, unique: !!ix.unique })),
      seed_rows: seedRows,
    };
  });
  return { tables: out, seedIndexMaps };
}

// ─── Pinning validation issues to editor rows ───

export type IssueLocation =
  | { area: "table" }
  | { area: "field"; field: number }
  | { area: "check"; index: number }
  | { area: "index"; index: number }
  | { area: "seed"; index: number };

export function issuesForTable(issues: SchemaIssue[], tableName: string): SchemaIssue[] {
  const name = tableName.trim();
  if (!name) return [];
  return issues.filter((i) => i.table !== null && i.table.trim() === name);
}

/** Where in a table's editor an issue belongs, from its kind + index.
 *  Anything that can't be pinned (or points past the draft because the
 *  user kept typing while validation ran) lands at table level. */
export function locateIssue(table: DraftTable, issue: SchemaIssue, seedIndexMap?: number[]): IssueLocation {
  const i = issue.index;
  const tableLevel: IssueLocation = { area: "table" };
  if (i === null || i === undefined || i < 0) return tableLevel;
  const fieldAt = (name: string | undefined): IssueLocation => {
    if (name === undefined) return tableLevel;
    const f = table.key_fields.findIndex((k) => sameField(k, name));
    return f >= 0 ? { area: "field", field: f } : tableLevel;
  };
  switch (issue.kind) {
    case "field":
      return i < table.key_fields.length ? { area: "field", field: i } : tableLevel;
    case "field_spec":
      return fieldAt(table.field_specs[i]?.name);
    case "foreign_key":
      return fieldAt(table.foreign_keys[i]?.field);
    case "check":
      return i < table.checks.length ? { area: "check", index: i } : tableLevel;
    case "index":
      return i < table.indexes.length ? { area: "index", index: i } : tableLevel;
    case "seed_row": {
      const draftRow = seedIndexMap ? seedIndexMap[i] : i;
      return draftRow !== undefined && draftRow < table.seed_rows.length ? { area: "seed", index: draftRow } : tableLevel;
    }
    default:
      return tableLevel;
  }
}

/** Issues grouped by table name, in first-seen order ("" = not tied to
 *  a named table, e.g. a table with no name yet). */
export function groupIssuesByTable(issues: SchemaIssue[]): [string, SchemaIssue[]][] {
  const groups = new Map<string, SchemaIssue[]>();
  for (const issue of issues) {
    const key = issue.table ?? "";
    const list = groups.get(key);
    if (list) list.push(issue);
    else groups.set(key, [issue]);
  }
  return [...groups.entries()];
}

export function isKnownFieldType(value: unknown): value is FieldType {
  return typeof value === "string" && (FIELD_TYPES as readonly string[]).includes(value);
}
