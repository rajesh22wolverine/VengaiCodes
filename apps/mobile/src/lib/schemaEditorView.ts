// ─── Architecture schema — mobile editor view helpers ───
//
// The decisions the typed table editor makes about WHAT to show, kept
// out of the React Native components so they can be unit-tested
// (schemaEditorView.test.ts) under plain vitest, without the RN runtime:
// which row a validation issue belongs to, which chips a field offers
// and which of them is selected, how seed rows are numbered, and so on.
//
// On desktop the same logic sits inline in SchemaTableEditor.tsx /
// SchemaStatus.tsx; everything here is written to produce exactly what
// those components show (a <select> there is a chip row here), so the
// two apps agree on every label and every rule. The data-changing edits
// themselves all live in schemaDraft.ts, shared line-for-line with
// desktop.

import {
  DraftTable,
  FIELD_TYPES,
  ForeignKey,
  ON_DELETE_LABELS,
  ON_DELETE_RULES,
  OnDeleteRule,
  SchemaIssue,
} from "./schemaTypes";
import { fkTargetsId, isBlankSeedRow, isKnownFieldType, locateIssue, sameTable } from "./schemaDraft";

// ─── Server error text ───

/** FastAPI's `detail` is usually a string (the schema editor's 400 is a
 *  multi-line "Fix these before saving:\n• …" list); a 422 carries a
 *  list of {msg} objects. Anything else is shown as JSON rather than
 *  dropped, so the user always sees *why*. */
export function detailToText(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => (typeof d === "object" && d && "msg" in d ? String((d as { msg: unknown }).msg) : String(d)))
      .join("\n");
  }
  if (detail && typeof detail === "object") return JSON.stringify(detail);
  return "";
}

// ─── Pinning live-validation issues to editor rows ───

export interface PinnedIssues {
  /** Not tied to a row (or pointing past the draft) — shown on the card. */
  table: string[];
  /** By key_fields position. */
  fields: Map<number, string[]>;
  checks: Map<number, string[]>;
  indexes: Map<number, string[]>;
  /** By DRAFT seed row position (blank rows included). */
  seeds: Map<number, string[]>;
}

function push(map: Map<number, string[]>, key: number, message: string): void {
  const list = map.get(key);
  if (list) list.push(message);
  else map.set(key, [message]);
}

/** Sorts one table's issues into the rows they're about. */
export function pinIssues(table: DraftTable, issues: SchemaIssue[], seedIndexMap?: number[]): PinnedIssues {
  const pinned: PinnedIssues = {
    table: [],
    fields: new Map(),
    checks: new Map(),
    indexes: new Map(),
    seeds: new Map(),
  };
  for (const issue of issues) {
    const loc = locateIssue(table, issue, seedIndexMap);
    if (loc.area === "field") push(pinned.fields, loc.field, issue.message);
    else if (loc.area === "check") push(pinned.checks, loc.index, issue.message);
    else if (loc.area === "index") push(pinned.indexes, loc.index, issue.message);
    else if (loc.area === "seed") push(pinned.seeds, loc.index, issue.message);
    else pinned.table.push(issue.message);
  }
  return pinned;
}

export function countPinned(map: Map<number, string[]>): number {
  let n = 0;
  for (const list of map.values()) n += list.length;
  return n;
}

// ─── Field choices ───

export interface TypeChoice {
  /** null = Auto (keep inferring the type from the field's name). */
  value: string | null;
  label: string;
  /** A declared type the backend doesn't know — shown so it can be fixed. */
  invalid?: boolean;
}

/** "Auto (<what it resolves to>)" first, then the nine real types; a
 *  declared type that isn't one of them (hand-edited or AI-authored data)
 *  is kept as a last choice so it stays visible until changed. */
export function typeChoices(declaredType: string | null | undefined, autoType: string): TypeChoice[] {
  const choices: TypeChoice[] = [
    { value: null, label: `Auto (${autoType})` },
    ...FIELD_TYPES.map((t) => ({ value: t, label: t })),
  ];
  if (declaredType && !isKnownFieldType(declaredType)) {
    choices.push({ value: declaredType, label: `${declaredType} (not a valid type)`, invalid: true });
  }
  return choices;
}

export interface LinkChoice {
  /** The table NAME to link to, or null for "no link". */
  value: string | null;
  label: string;
  selected: boolean;
  /** The link points at a table that isn't in the draft any more. */
  missing?: boolean;
}

/** The "Links to" chips for one field: none, then every named table in
 *  editor order (this one included — a self-reference is legal), with a
 *  link to a table that no longer exists kept visible as "(missing)". */
export function linkChoices(tables: DraftTable[], tableIndex: number, fk: ForeignKey | undefined): LinkChoice[] {
  const choices: LinkChoice[] = [{ value: null, label: "None", selected: !fk }];
  let matched = false;
  tables.forEach((t, k) => {
    const name = t.name.trim();
    if (!name) return;
    const selected = !!fk && !matched && sameTable(name, fk.references_table);
    if (selected) matched = true;
    let label = selected && !fkTargetsId(fk) ? `${name}.${fk!.references_field}` : name;
    if (k === tableIndex) label += " (this table)";
    choices.push({ value: name, label, selected });
  });
  if (fk && !matched) {
    choices.push({ value: fk.references_table, label: `${fk.references_table} (missing)`, selected: true, missing: true });
  }
  return choices;
}

export interface OnDeleteChoice {
  rule: OnDeleteRule;
  label: string;
  selected: boolean;
  disabled: boolean;
}

/** ON DELETE SET NULL can't work on a required (NOT NULL) column, so it
 *  is offered but disabled — the same rule setFieldRequired() enforces. */
export function onDeleteChoices(fk: ForeignKey | undefined, required: boolean): OnDeleteChoice[] {
  const current = fk ? String(fk.on_delete || "cascade") : "cascade";
  return ON_DELETE_RULES.map((rule) => ({
    rule,
    label: ON_DELETE_LABELS[rule],
    selected: current === rule,
    disabled: rule === "set_null" && required,
  }));
}

// ─── Defaults ───

export type BooleanDefaultChoice = "true" | "false" | "none";

/** A boolean field's default as one of three chips. The draft may hold
 *  true/false or, from text typed before the type was pinned, the
 *  strings "true"/"false" — both mean the same to the backend. */
export function booleanDefaultChoice(value: unknown): BooleanDefaultChoice {
  if (value === true || value === "true") return "true";
  if (value === false || value === "false") return "false";
  return "none";
}

export function booleanDefaultValue(choice: BooleanDefaultChoice): boolean | null {
  return choice === "none" ? null : choice === "true";
}

const DEFAULT_PLACEHOLDERS: Record<string, string> = {
  datetime: "now, or 2024-01-31T09:00",
  date: "today, or 2024-01-31",
  integer: "e.g. 0",
  float: "e.g. 0.5",
  decimal: "e.g. 9.99",
  json: 'e.g. {"key": 1}',
};

export function defaultPlaceholder(type: string): string {
  return DEFAULT_PLACEHOLDERS[type] ?? "No default";
}

/** One line under the default input explaining the two special values. */
export function defaultHint(type: string): string | null {
  if (type === "datetime") return '"now" = the moment the row is created';
  if (type === "date") return '"today" = the day the row is created';
  return null;
}

// ─── Seed rows ───

/** "#1", "#2"… numbered the way the backend numbers them ("Seed row 2"),
 *  which skips fully blank rows because those are never sent; a blank
 *  row is labelled "—". */
export function seedRowLabels(rows: Record<string, string>[]): string[] {
  let sent = 0;
  return rows.map((row) => {
    if (isBlankSeedRow(row)) return "—";
    sent += 1;
    return `#${sent}`;
  });
}

// ─── Status banner titles ───

/** The collapsed title of the "what was dropped from the AI's proposal"
 *  banner (notes starting with "Dropped" are removals; anything else is
 *  an adjustment). */
export function schemaNotesTitle(notes: string[]): string {
  const dropped = notes.filter((n) => n.startsWith("Dropped")).length;
  const other = notes.length - dropped;
  if (dropped > 0) {
    return (
      `Baby Tiger dropped ${dropped} suggestion${dropped === 1 ? "" : "s"} that didn't validate` +
      (other > 0 ? ` and made ${other} other fix${other === 1 ? "" : "es"}` : "")
    );
  }
  return `Baby Tiger adjusted ${notes.length} of its suggestion${notes.length === 1 ? "" : "s"} so they validate`;
}

export function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}
