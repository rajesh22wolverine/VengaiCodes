// ─── Architecture schema — wire types ───
//
// Mirrors the backend's single source of truth for typed tables
// (apps/backend/app/ai/db_schema.py) and the Pydantic models in
// apps/backend/app/api/v1/architecture.py. A table saved before typed
// columns existed is just {name, purpose, key_fields}: every other array
// here is optional on the wire and means "nothing declared", in which
// case the backend keeps inferring each field's type from its name —
// exactly what it always did.
//
// Kept identical to the desktop app's copy
// (apps/desktop/src/screens/architecture/schemaTypes.ts) so both editors
// send and read exactly the same shapes — change the two together.

export const FIELD_TYPES = [
  "string",
  "text",
  "integer",
  "float",
  "decimal",
  "boolean",
  "date",
  "datetime",
  "json",
] as const;
export type FieldType = (typeof FIELD_TYPES)[number];

export const ON_DELETE_RULES = ["cascade", "set_null", "restrict"] as const;
export type OnDeleteRule = (typeof ON_DELETE_RULES)[number];

export const ON_DELETE_LABELS: Record<OnDeleteRule, string> = {
  cascade: "Cascade",
  set_null: "Set null",
  restrict: "Restrict",
};

/** Columns every generated table gets without the user listing them.
 *  Checks and indexes may reference them; field specs, foreign keys and
 *  seed rows may not (the database fills them in). */
export const IMPLICIT_COLUMN_TYPES: Record<string, FieldType> = {
  id: "integer",
  created_at: "datetime",
  updated_at: "datetime",
};
export const IMPLICIT_COLUMNS = Object.keys(IMPLICIT_COLUMN_TYPES);

/** {name, type: null = keep inferring from the name, nullable (default
 *  true), default: any JSON value or null, unique}. */
export interface FieldSpec {
  name: string;
  type?: FieldType | null;
  nullable?: boolean;
  default?: unknown;
  unique?: boolean;
}

export interface ForeignKey {
  field: string;
  /** A table NAME (not its SQL name). */
  references_table: string;
  /** "id" unless the target is a field marked unique. */
  references_field?: string;
  on_delete?: OnDeleteRule | string;
}

export interface CheckConstraint {
  name: string;
  expression: string;
}

export interface IndexSpec {
  fields: string[];
  unique?: boolean;
}

export interface DatabaseTable {
  name: string;
  purpose: string;
  key_fields: string[];
  field_specs?: FieldSpec[];
  foreign_keys?: ForeignKey[];
  checks?: CheckConstraint[];
  indexes?: IndexSpec[];
  seed_rows?: Record<string, unknown>[];
}

/** The editor's working copy of a table: every array present, and seed
 *  cells held as the text the user typed (the backend coerces text to
 *  each column's type, and reports anything that doesn't convert). */
export interface DraftTable {
  name: string;
  purpose: string;
  key_fields: string[];
  field_specs: FieldSpec[];
  foreign_keys: ForeignKey[];
  checks: CheckConstraint[];
  indexes: IndexSpec[];
  seed_rows: Record<string, string>[];
}

export type SchemaIssueKind =
  | "table"
  | "field"
  | "field_spec"
  | "foreign_key"
  | "check"
  | "index"
  | "seed_row";

/** One structural problem. `index` is a position in the table's
 *  key_fields / field_specs / foreign_keys / checks / indexes /
 *  seed_rows array, depending on `kind`. */
export interface SchemaIssue {
  table: string | null;
  kind: SchemaIssueKind | string;
  index: number | null;
  message: string;
}

export interface ResolvedColumnFk {
  table: string;
  table_sql: string;
  column: string;
  on_delete: OnDeleteRule | string;
}

export interface ResolvedColumn {
  name: string;
  column: string;
  type: FieldType | string;
  /** true = the type came from a field spec; false = inferred. */
  declared: boolean;
  nullable: boolean;
  unique: boolean;
  /** Storage form: a literal value, "now"/"today", or null. */
  default: unknown;
  fk: ResolvedColumnFk | null;
}

export interface ResolvedTable {
  name: string;
  sql_name: string;
  columns: ResolvedColumn[];
  checks: { name: string; sql: string }[];
  indexes: { name: string; columns: string[]; unique: boolean }[];
  seed_row_count: number;
}

/** POST /architecture/{id}/validate — never 400s for schema problems. */
export interface SchemaValidationResult {
  success?: boolean;
  valid: boolean;
  issues: SchemaIssue[];
  erd?: string | null;
  resolved_tables?: ResolvedTable[];
}
