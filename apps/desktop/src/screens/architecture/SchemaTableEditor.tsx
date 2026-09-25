// ─── Typed editor for one database table ───
//
// One card per table: name + purpose, a field grid (type / required /
// unique / default / "links to" + on-delete), check constraints, indexes
// and seed rows. Every edit goes through a pure helper in schemaDraft.ts
// so the cross-references stay consistent (renaming a field renames it in
// its spec, foreign key, indexes, seed rows and check expressions), and
// field specs are only emitted when a field actually declares something.
//
// Names (table and field) are committed on blur / Enter rather than per
// keystroke: a rename has to carry every reference along with it, and
// half-typed intermediate names ("pri", "pric"…) would otherwise collide
// with other fields or briefly drop a reference on the floor.
//
// Validation is the backend's job (POST /architecture/{id}/validate, run
// by the screen); this card only places the returned issues next to the
// row they're about.

import { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronRight, KeyRound, ListChecks, Plus, Rows3, ShieldCheck, X } from "lucide-react";
import {
  DraftTable,
  FieldType,
  FIELD_TYPES,
  ON_DELETE_LABELS,
  ON_DELETE_RULES,
  OnDeleteRule,
  ResolvedTable,
  SchemaIssue,
} from "./schemaTypes";
import {
  addCheck,
  addField,
  addIndex,
  addSeedRow,
  autoFieldType,
  EditResult,
  findFk,
  findSpec,
  fkTargetsId,
  indexFieldChoices,
  isBlankSeedRow,
  isImplicitField,
  isKnownFieldType,
  locateIssue,
  removeCheck,
  removeField,
  removeIndex,
  removeSeedRow,
  sameField,
  sameTable,
  seedCell,
  seedColumns,
  setFieldLink,
  setFieldOnDelete,
  setFieldRequired,
  setSeedCell,
  toggleIndexField,
  updateCheck,
  updateIndex,
  upsertFieldSpec,
  valueToText,
} from "./schemaDraft";
import { InlineIssues } from "./SchemaStatus";

const INPUT =
  "px-2 py-1.5 rounded-md text-xs bg-[var(--color-surface)] border border-[var(--color-border)] text-[var(--color-text-primary)] disabled:opacity-50";
const REMOVE_BTN =
  "p-1.5 rounded-md text-[var(--color-text-tertiary)] hover:text-[var(--color-error)] hover:bg-[var(--color-surface)] transition-colors flex-shrink-0";
const ADD_BTN =
  "flex items-center gap-1.5 px-2.5 py-1 rounded-md border border-dashed border-[var(--color-border)] text-xs font-medium text-[var(--color-text-secondary)] hover:bg-[var(--color-surface)] transition-colors";

// Field grid: name | type | required | unique | default | links to | on delete | ×
const FIELD_GRID = "minmax(130px,1.4fr) 128px 46px 46px minmax(110px,1fr) minmax(120px,1fr) 96px 28px";

const CHECK_EXAMPLES = ["price >= 0", "status IN ('draft','paid')", "LENGTH(name) > 0", "end_date >= start_date"];

const DEFAULT_PLACEHOLDERS: Record<string, string> = {
  datetime: 'now, or 2024-01-31T09:00',
  date: "today, or 2024-01-31",
  integer: "e.g. 0",
  float: "e.g. 0.5",
  decimal: "e.g. 9.99",
  json: 'e.g. {"key": 1}',
};

/** A text input that only reports its value on blur / Enter (Escape
 *  reverts). `onCommit` returns false to reject the value, which puts the
 *  last good value back. */
export function CommitInput({
  value,
  onCommit,
  className,
  placeholder,
  ariaLabel,
}: {
  value: string;
  onCommit: (next: string) => boolean;
  className?: string;
  placeholder?: string;
  ariaLabel?: string;
}) {
  const [text, setText] = useState(value);
  const reverting = useRef(false);

  useEffect(() => setText(value), [value]);

  const commit = () => {
    if (reverting.current) {
      reverting.current = false;
      return;
    }
    if (text === value) return;
    if (!onCommit(text)) setText(value);
  };

  return (
    <input
      value={text}
      aria-label={ariaLabel}
      placeholder={placeholder}
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          e.currentTarget.blur();
        } else if (e.key === "Escape") {
          reverting.current = true;
          setText(value);
          e.currentTarget.blur();
        }
      }}
      className={className}
    />
  );
}

function SubSection({
  icon: Icon,
  title,
  count,
  issueCount,
  defaultOpen,
  children,
}: {
  icon: React.ElementType;
  title: string;
  count: number;
  issueCount: number;
  defaultOpen: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  // A problem inside a collapsed section must never be hidden.
  const isOpen = open || issueCount > 0;
  return (
    <div className="mt-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)]">
      <button
        onClick={() => setOpen(!isOpen)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left"
      >
        {isOpen ? (
          <ChevronDown className="w-3.5 h-3.5 text-[var(--color-text-tertiary)]" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 text-[var(--color-text-tertiary)]" />
        )}
        <Icon className="w-3.5 h-3.5 text-[var(--color-primary)]" />
        <span className="text-xs font-semibold text-[var(--color-text-primary)]">{title}</span>
        <span className="text-[10px] text-[var(--color-text-tertiary)]">({count})</span>
        {issueCount > 0 && (
          <span className="ml-auto text-[10px] font-semibold text-[var(--color-error)]">
            {issueCount} problem{issueCount === 1 ? "" : "s"}
          </span>
        )}
      </button>
      {isOpen && <div className="px-3 pb-3">{children}</div>}
    </div>
  );
}

export default function SchemaTableEditor({
  tables,
  tableIndex,
  resolved,
  issues,
  seedIndexMap,
  onUpdate,
  onRenameTable,
  onRenameField,
  onRemove,
  onError,
}: {
  tables: DraftTable[];
  tableIndex: number;
  /** This table as the live validation resolved it (authoritative types). */
  resolved?: ResolvedTable;
  /** Live-validation issues for this table. */
  issues: SchemaIssue[];
  seedIndexMap?: number[];
  onUpdate: (fn: (table: DraftTable) => DraftTable) => void;
  onRenameTable: (name: string) => boolean;
  onRenameField: (fieldIndex: number, name: string) => boolean;
  onRemove: () => void;
  onError: (message: string) => void;
}) {
  const table = tables[tableIndex]!;
  const [newField, setNewField] = useState("");

  // Pin each issue to the row it's about.
  const tableIssues: string[] = [];
  const fieldIssues = new Map<number, string[]>();
  const checkIssues = new Map<number, string[]>();
  const indexIssues = new Map<number, string[]>();
  const seedIssues = new Map<number, string[]>();
  const push = (map: Map<number, string[]>, key: number, message: string) => {
    const list = map.get(key);
    if (list) list.push(message);
    else map.set(key, [message]);
  };
  for (const issue of issues) {
    const loc = locateIssue(table, issue, seedIndexMap);
    if (loc.area === "field") push(fieldIssues, loc.field, issue.message);
    else if (loc.area === "check") push(checkIssues, loc.index, issue.message);
    else if (loc.area === "index") push(indexIssues, loc.index, issue.message);
    else if (loc.area === "seed") push(seedIssues, loc.index, issue.message);
    else tableIssues.push(issue.message);
  }

  const commitNewField = () => {
    if (!newField.trim()) return;
    const result: EditResult<DraftTable> = addField(table, newField);
    if (!result.ok) {
      onError(result.error);
      return;
    }
    onUpdate((t) => {
      const r = addField(t, newField);
      return r.ok ? r.value : t;
    });
    setNewField("");
  };

  // Every named table, this one included (a self-link like parent_id is
  // legitimate). `self` is worked out before filtering out unnamed
  // tables, so it still points at the right one.
  const linkOptions = tables
    .map((t, i) => ({ name: t.name.trim(), self: i === tableIndex }))
    .filter((o) => o.name);
  const linkTargets = linkOptions.map((o) => o.name);
  const seedCols = seedColumns(table);
  const indexChoices = indexFieldChoices(table);
  const countIssues = (m: Map<number, string[]>) => [...m.values()].reduce((n, l) => n + l.length, 0);

  return (
    <div
      className={`rounded-xl border bg-[var(--color-surface-raised)] p-4 ${
        issues.length > 0 ? "border-[var(--color-warning)]" : "border-[var(--color-border)]"
      }`}
    >
      {/* Name + purpose */}
      <div className="flex items-start gap-2 mb-2">
        <CommitInput
          value={table.name}
          onCommit={onRenameTable}
          placeholder="table_name"
          ariaLabel="Table name"
          className="flex-1 px-2 py-1.5 rounded-md text-sm font-mono font-semibold bg-[var(--color-surface)] border border-[var(--color-border)] text-[var(--color-text-primary)]"
        />
        <button onClick={onRemove} title="Remove table" className={REMOVE_BTN}>
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
      <input
        value={table.purpose}
        onChange={(e) => onUpdate((t) => ({ ...t, purpose: e.target.value }))}
        placeholder="What this table is for"
        className="w-full mb-3 px-2 py-1.5 rounded-md text-xs bg-[var(--color-surface)] border border-[var(--color-border)] text-[var(--color-text-secondary)]"
      />
      {tableIssues.length > 0 && (
        <div className="mb-3">
          <InlineIssues messages={tableIssues} />
        </div>
      )}

      {/* Field grid */}
      <div className="overflow-x-auto">
        <div className="min-w-[760px]">
          <div
            className="grid gap-1.5 px-1 pb-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-tertiary)]"
            style={{ gridTemplateColumns: FIELD_GRID }}
          >
            <span>Field</span>
            <span>Type</span>
            <span className="text-center" title="Required (NOT NULL)">Req.</span>
            <span className="text-center">Unique</span>
            <span>Default</span>
            <span>Links to</span>
            <span>On delete</span>
            <span />
          </div>

          {/* The automatic primary key, always there */}
          <div
            className="grid gap-1.5 items-center px-1 py-1 rounded-md"
            style={{ gridTemplateColumns: FIELD_GRID }}
          >
            <span className="flex items-center gap-1 px-2 text-xs font-mono text-[var(--color-text-secondary)]">
              <KeyRound className="w-3 h-3 text-[var(--color-warning)]" /> id
            </span>
            <span className="col-span-7 text-[11px] text-[var(--color-text-tertiary)]">
              integer primary key, plus created_at / updated_at timestamps — all created automatically
            </span>
          </div>

          {table.key_fields.map((field, fi) => {
            const messages = fieldIssues.get(fi) ?? [];
            if (isImplicitField(field) || !field.trim()) {
              return (
                <FieldRowShell key={fi} messages={messages}>
                  <CommitInput
                    value={field}
                    onCommit={(name) => onRenameField(fi, name)}
                    ariaLabel="Field name"
                    className={`${INPUT} font-mono w-full`}
                  />
                  <span className="col-span-6 text-[11px] text-[var(--color-text-tertiary)]">
                    {field.trim() ? "Created automatically — nothing to set here." : "Give this field a name."}
                  </span>
                  <button onClick={() => onUpdate((t) => removeField(t, fi))} title="Remove field" className={REMOVE_BTN}>
                    <X className="w-3.5 h-3.5" />
                  </button>
                </FieldRowShell>
              );
            }

            const spec = findSpec(table, field);
            const fk = findFk(table, field);
            const required = spec?.nullable === false;
            const declaredType = spec?.type ?? null;
            const auto = autoFieldType(tables, tableIndex, field, resolved);
            const effectiveType = declaredType || auto;
            const linkValue = fk
              ? linkTargets.find((name) => sameTable(name, fk.references_table)) ?? fk.references_table
              : "";
            const linkMissing = !!fk && !linkTargets.some((name) => sameTable(name, fk.references_table));

            return (
              <FieldRowShell key={fi} messages={messages}>
                <CommitInput
                  value={field}
                  onCommit={(name) => onRenameField(fi, name)}
                  ariaLabel="Field name"
                  className={`${INPUT} font-mono w-full`}
                />

                <select
                  value={declaredType ?? ""}
                  aria-label={`Type of ${field}`}
                  onChange={(e) => onUpdate((t) => upsertFieldSpec(t, field, { type: e.target.value ? (e.target.value as FieldType) : null }))}
                  className={`${INPUT} w-full ${declaredType ? "font-semibold" : "text-[var(--color-text-tertiary)]"}`}
                >
                  <option value="">Auto ({auto})</option>
                  {FIELD_TYPES.map((ft) => (
                    <option key={ft} value={ft}>
                      {ft}
                    </option>
                  ))}
                  {declaredType && !isKnownFieldType(declaredType) && (
                    <option value={declaredType}>{declaredType} (not a valid type)</option>
                  )}
                </select>

                <label className="flex justify-center" title="Required — every row must have a value">
                  <input
                    type="checkbox"
                    checked={required}
                    onChange={(e) => onUpdate((t) => setFieldRequired(t, field, e.target.checked))}
                    className="w-3.5 h-3.5 accent-[var(--color-primary)]"
                  />
                </label>

                <label className="flex justify-center" title="Unique — no two rows may share a value">
                  <input
                    type="checkbox"
                    checked={!!spec?.unique}
                    onChange={(e) => onUpdate((t) => upsertFieldSpec(t, field, { unique: e.target.checked }))}
                    className="w-3.5 h-3.5 accent-[var(--color-primary)]"
                  />
                </label>

                {effectiveType === "boolean" ? (
                  <select
                    value={
                      spec?.default === true || spec?.default === "true"
                        ? "true"
                        : spec?.default === false || spec?.default === "false"
                          ? "false"
                          : ""
                    }
                    aria-label={`Default for ${field}`}
                    onChange={(e) =>
                      onUpdate((t) =>
                        upsertFieldSpec(t, field, {
                          default: e.target.value === "" ? null : e.target.value === "true",
                        })
                      )
                    }
                    className={`${INPUT} w-full`}
                  >
                    <option value="">No default</option>
                    <option value="true">true</option>
                    <option value="false">false</option>
                  </select>
                ) : (
                  <input
                    value={valueToText(spec?.default)}
                    aria-label={`Default for ${field}`}
                    placeholder={DEFAULT_PLACEHOLDERS[effectiveType] ?? "No default"}
                    title={
                      effectiveType === "datetime"
                        ? '"now" = the moment the row is created'
                        : effectiveType === "date"
                          ? '"today" = the day the row is created'
                          : undefined
                    }
                    onChange={(e) => onUpdate((t) => upsertFieldSpec(t, field, { default: e.target.value }))}
                    className={`${INPUT} w-full font-mono`}
                  />
                )}

                <select
                  value={linkValue}
                  aria-label={`${field} links to`}
                  onChange={(e) =>
                    onUpdate((t) => setFieldLink(t, field, e.target.value ? { table: e.target.value } : null))
                  }
                  className={`${INPUT} w-full ${fk ? "" : "text-[var(--color-text-tertiary)]"}`}
                >
                  <option value="">— none —</option>
                  {linkOptions.map(({ name, self }, k) => (
                    <option key={`${name}-${k}`} value={name}>
                      {fk && sameTable(name, fk.references_table) && !fkTargetsId(fk)
                        ? `${name}.${fk.references_field}`
                        : name}
                      {self ? " (this table)" : ""}
                    </option>
                  ))}
                  {linkMissing && <option value={fk!.references_table}>{fk!.references_table} (missing)</option>}
                </select>

                <select
                  value={fk ? String(fk.on_delete || "cascade") : "cascade"}
                  disabled={!fk}
                  aria-label={`When the linked ${field} row is deleted`}
                  title="What happens to this row when the row it links to is deleted"
                  onChange={(e) => onUpdate((t) => setFieldOnDelete(t, field, e.target.value as OnDeleteRule))}
                  className={`${INPUT} w-full`}
                >
                  {ON_DELETE_RULES.map((rule) => (
                    <option key={rule} value={rule} disabled={rule === "set_null" && required}>
                      {ON_DELETE_LABELS[rule]}
                    </option>
                  ))}
                </select>

                <button onClick={() => onUpdate((t) => removeField(t, fi))} title="Remove field" className={REMOVE_BTN}>
                  <X className="w-3.5 h-3.5" />
                </button>
              </FieldRowShell>
            );
          })}
        </div>
      </div>

      <input
        value={newField}
        onChange={(e) => setNewField(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commitNewField();
          }
        }}
        onBlur={commitNewField}
        placeholder="+ add field, press Enter"
        className="w-full mt-2 px-2 py-1 rounded-md text-xs font-mono bg-transparent border border-dashed border-[var(--color-border)] text-[var(--color-text-secondary)]"
      />

      {/* Checks */}
      <SubSection
        icon={ShieldCheck}
        title="Checks"
        count={table.checks.length}
        issueCount={countIssues(checkIssues)}
        defaultOpen={table.checks.length > 0}
      >
        <p className="text-[11px] text-[var(--color-text-tertiary)] leading-relaxed mb-2">
          A rule every row must pass, enforced by the database. Compare fields and values with = &lt;&gt; &lt;
          &lt;= &gt; &gt;=, IS [NOT] NULL, [NOT] IN (…), [NOT] BETWEEN … AND …, [NOT] LIKE '…' or LENGTH(field),
          joined with AND / OR / NOT. Text goes in 'single quotes'. For example:{" "}
          {CHECK_EXAMPLES.map((ex, k) => (
            <span key={ex}>
              <code className="font-mono text-[var(--color-text-secondary)]">{ex}</code>
              {k < CHECK_EXAMPLES.length - 1 ? " · " : ""}
            </span>
          ))}
        </p>
        <div className="space-y-2">
          {table.checks.map((chk, ci) => (
            <div key={ci} className="space-y-1">
              <div className="flex items-center gap-2">
                <input
                  value={chk.name}
                  onChange={(e) => onUpdate((t) => updateCheck(t, ci, { name: e.target.value }))}
                  placeholder="rule_name"
                  aria-label="Check name"
                  className={`${INPUT} w-40 flex-shrink-0 font-mono`}
                />
                <input
                  value={chk.expression}
                  onChange={(e) => onUpdate((t) => updateCheck(t, ci, { expression: e.target.value }))}
                  placeholder="price >= 0"
                  aria-label="Check expression"
                  className={`${INPUT} flex-1 font-mono ${checkIssues.has(ci) ? "border-[var(--color-error)]" : ""}`}
                />
                <button onClick={() => onUpdate((t) => removeCheck(t, ci))} title="Remove check" className={REMOVE_BTN}>
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
              <InlineIssues messages={checkIssues.get(ci) ?? []} />
            </div>
          ))}
        </div>
        <button onClick={() => onUpdate(addCheck)} className={`${ADD_BTN} mt-2`}>
          <Plus className="w-3 h-3" /> Add check
        </button>
      </SubSection>

      {/* Indexes */}
      <SubSection
        icon={ListChecks}
        title="Indexes"
        count={table.indexes.length}
        issueCount={countIssues(indexIssues)}
        defaultOpen={table.indexes.length > 0}
      >
        <p className="text-[11px] text-[var(--color-text-tertiary)] leading-relaxed mb-2">
          Speeds up searching, filtering or sorting on the chosen fields. Pick fields in order — a combined
          index uses them in the order you pick. Unique also stops two rows sharing the same combination.
        </p>
        <div className="space-y-2">
          {table.indexes.map((ix, ii) => (
            <div key={ii} className="space-y-1">
              <div className="flex items-start gap-2">
                <div className="flex-1 flex flex-wrap gap-1.5">
                  {indexChoices.map((choice) => {
                    const pos = ix.fields.findIndex((f) => sameField(f, choice));
                    const on = pos >= 0;
                    return (
                      <button
                        key={choice}
                        onClick={() => onUpdate((t) => toggleIndexField(t, ii, choice))}
                        className={`flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-mono border transition-colors ${
                          on
                            ? "bg-[var(--color-primary-light)] border-[var(--color-primary)] text-[var(--color-primary)]"
                            : "bg-[var(--color-surface)] border-[var(--color-border)] text-[var(--color-text-tertiary)] hover:text-[var(--color-text-secondary)]"
                        }`}
                      >
                        {on && <span className="text-[9px] font-bold">{pos + 1}</span>}
                        {choice}
                      </button>
                    );
                  })}
                  {/* Fields an index still names but the table no longer has */}
                  {ix.fields
                    .filter((f) => !indexChoices.some((c) => sameField(c, f)))
                    .map((f) => (
                      <button
                        key={`missing-${f}`}
                        onClick={() => onUpdate((t) => toggleIndexField(t, ii, f))}
                        title="Not a field of this table — click to remove"
                        className="px-2 py-0.5 rounded-md text-xs font-mono border border-[var(--color-error)] text-[var(--color-error)] line-through"
                      >
                        {f}
                      </button>
                    ))}
                </div>
                <label className="flex items-center gap-1 text-xs text-[var(--color-text-secondary)] flex-shrink-0 pt-0.5">
                  <input
                    type="checkbox"
                    checked={!!ix.unique}
                    onChange={(e) => onUpdate((t) => updateIndex(t, ii, { unique: e.target.checked }))}
                    className="w-3.5 h-3.5 accent-[var(--color-primary)]"
                  />
                  unique
                </label>
                <button onClick={() => onUpdate((t) => removeIndex(t, ii))} title="Remove index" className={REMOVE_BTN}>
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
              <InlineIssues messages={indexIssues.get(ii) ?? []} />
            </div>
          ))}
        </div>
        <button onClick={() => onUpdate(addIndex)} className={`${ADD_BTN} mt-2`}>
          <Plus className="w-3 h-3" /> Add index
        </button>
      </SubSection>

      {/* Seed rows */}
      <SubSection
        icon={Rows3}
        title="Seed rows"
        count={table.seed_rows.filter((r) => !isBlankSeedRow(r)).length}
        issueCount={countIssues(seedIssues)}
        defaultOpen={false}
      >
        <p className="text-[11px] text-[var(--color-text-tertiary)] leading-relaxed mb-2">
          Starter rows the first database migration inserts (lookup values, categories, a demo record…).
          Blank cells are left out; a completely blank row is ignored. Links to another table's id can't be
          seeded — the database assigns ids.
        </p>
        {seedCols.length === 0 ? (
          <p className="text-xs text-[var(--color-text-tertiary)]">This table has no fields that can take seed values.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="text-xs border-separate border-spacing-1">
              <thead>
                <tr>
                  <th className="w-8" />
                  {seedCols.map((col) => {
                    const spec = findSpec(table, col);
                    const type = spec?.type || autoFieldType(tables, tableIndex, col, resolved);
                    return (
                      <th key={col} className="text-left font-mono font-semibold text-[var(--color-text-secondary)] px-1">
                        {col}
                        {spec?.nullable === false && (spec.default === null || spec.default === undefined) && (
                          <span className="text-[var(--color-error)]" title="Required">
                            *
                          </span>
                        )}
                        <span className="ml-1 font-normal text-[10px] text-[var(--color-text-tertiary)]">{type}</span>
                      </th>
                    );
                  })}
                  <th className="w-8" />
                </tr>
              </thead>
              <tbody>
                {(() => {
                  let sent = 0;
                  return table.seed_rows.map((row, ri) => {
                    const blank = isBlankSeedRow(row);
                    if (!blank) sent += 1;
                    const rowIssues = seedIssues.get(ri) ?? [];
                    return (
                      <SeedRowView
                        key={ri}
                        label={blank ? "—" : `#${sent}`}
                        columns={seedCols}
                        row={row}
                        blank={blank}
                        messages={rowIssues}
                        onCell={(col, value) => onUpdate((t) => setSeedCell(t, ri, col, value))}
                        onRemove={() => onUpdate((t) => removeSeedRow(t, ri))}
                      />
                    );
                  });
                })()}
              </tbody>
            </table>
          </div>
        )}
        <button onClick={() => onUpdate(addSeedRow)} disabled={seedCols.length === 0} className={`${ADD_BTN} mt-2 disabled:opacity-50`}>
          <Plus className="w-3 h-3" /> Add row
        </button>
      </SubSection>
    </div>
  );
}

function FieldRowShell({ messages, children }: { messages: string[]; children: React.ReactNode }) {
  return (
    <div
      className={`px-1 py-1 rounded-md ${messages.length > 0 ? "bg-[var(--color-error-light)]" : ""}`}
    >
      <div className="grid gap-1.5 items-center" style={{ gridTemplateColumns: FIELD_GRID }}>
        {children}
      </div>
      {messages.length > 0 && (
        <div className="mt-1 px-1">
          <InlineIssues messages={messages} />
        </div>
      )}
    </div>
  );
}

function SeedRowView({
  label,
  columns,
  row,
  blank,
  messages,
  onCell,
  onRemove,
}: {
  label: string;
  columns: string[];
  row: Record<string, string>;
  blank: boolean;
  messages: string[];
  onCell: (column: string, value: string) => void;
  onRemove: () => void;
}) {
  return (
    <>
      <tr>
        <td
          className={`text-[10px] font-mono text-right pr-1 ${blank ? "text-[var(--color-text-disabled)]" : "text-[var(--color-text-tertiary)]"}`}
          title={blank ? "Blank rows are ignored" : undefined}
        >
          {label}
        </td>
        {columns.map((col) => (
          <td key={col}>
            <input
              value={seedCell(row, col)}
              onChange={(e) => onCell(col, e.target.value)}
              aria-label={`Seed value for ${col}`}
              className={`${INPUT} w-32 font-mono ${messages.length > 0 ? "border-[var(--color-error)]" : ""}`}
            />
          </td>
        ))}
        <td>
          <button onClick={onRemove} title="Remove row" className={REMOVE_BTN}>
            <X className="w-3.5 h-3.5" />
          </button>
        </td>
      </tr>
      {messages.length > 0 && (
        <tr>
          <td />
          <td colSpan={columns.length + 1}>
            <InlineIssues messages={messages} />
          </td>
        </tr>
      )}
    </>
  );
}
