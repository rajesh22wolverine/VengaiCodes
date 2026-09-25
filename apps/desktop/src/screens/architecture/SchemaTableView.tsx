// ─── Read-only view of one database table ───
//
// Shows what code generation will actually build for the table — the
// backend's resolved schema (GET /architecture → resolved_tables), not a
// re-derivation here — so a type, key or default shown on this card is
// exactly what the generated model and migration contain. A declared
// type gets a solid badge; a type still inferred from the field's name
// gets a muted "auto" one, so it's obvious which parts were decided and
// which are a best guess worth checking.
//
// Falls back to the plain field-name chips this screen always showed
// when there's no resolved table (an older backend, or a table whose
// own name is invalid and so can't be resolved).

import { motion } from "framer-motion";
import { AlertTriangle, Database, KeyRound, Link2, ListChecks, Rows3, ShieldCheck } from "lucide-react";
import { DatabaseTable, ON_DELETE_LABELS, OnDeleteRule, ResolvedColumn, ResolvedTable } from "./schemaTypes";
import { describeDefault, isImplicitField, sameField } from "./schemaDraft";

const BADGE = "px-1.5 py-0.5 rounded text-[10px] font-semibold font-mono leading-none";

export function TypeBadge({ type, declared }: { type: string; declared: boolean }) {
  return declared ? (
    <span className={`${BADGE} bg-[var(--color-primary-light)] text-[var(--color-primary)]`}>{type}</span>
  ) : (
    <span
      title="Inferred from the field's name — declare a type in Edit to pin it"
      className={`${BADGE} border border-dashed border-[var(--color-border)] text-[var(--color-text-tertiary)]`}
    >
      {type} <span className="font-normal opacity-80">auto</span>
    </span>
  );
}

/** Unique either by its own flag or through a one-field unique index —
 *  the same rule the backend's ERD uses for its UK marker. */
function isUniqueColumn(col: ResolvedColumn, table: ResolvedTable): boolean {
  return (
    col.unique || table.indexes.some((ix) => ix.unique && ix.columns.length === 1 && ix.columns[0] === col.column)
  );
}

function ColumnBadges({ col, unique }: { col: ResolvedColumn; unique: boolean }) {
  const rule = ON_DELETE_LABELS[col.fk?.on_delete as OnDeleteRule] ?? col.fk?.on_delete;
  return (
    <>
      {col.fk && (
        <span
          title={`Foreign key → ${col.fk.table_sql}.${col.fk.column}, on delete: ${rule}`}
          className={`${BADGE} bg-[var(--color-info-light)] text-[var(--color-info)] inline-flex items-center gap-0.5`}
        >
          <Link2 className="w-2.5 h-2.5" />
          FK → {col.fk.table}
          {col.fk.column !== "id" ? `.${col.fk.column}` : ""}
        </span>
      )}
      {unique && (
        <span title="Unique" className={`${BADGE} bg-[var(--color-accent-light)] text-[var(--color-accent)]`}>
          UQ
        </span>
      )}
      {!col.nullable && (
        <span
          className={`${BADGE} border border-[var(--color-border)] bg-[var(--color-surface)] text-[var(--color-text-secondary)] font-sans`}
        >
          required
        </span>
      )}
      {col.default !== null && col.default !== undefined && (
        <span className="text-[10px] font-mono text-[var(--color-text-tertiary)] truncate max-w-[10rem]">
          = {describeDefault(col.default, col.type)}
        </span>
      )}
    </>
  );
}

export default function SchemaTableView({
  table,
  resolved,
  issueCount,
  delay,
}: {
  table: DatabaseTable;
  resolved?: ResolvedTable;
  issueCount: number;
  delay: number;
}) {
  const ownFields = table.key_fields.filter((f) => !isImplicitField(f));

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay }}
      className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4"
    >
      <div className="flex items-center gap-2 mb-2">
        <Database className="w-3.5 h-3.5 text-[var(--color-primary)] flex-shrink-0" />
        <h4 className="text-sm font-semibold text-[var(--color-text-primary)] font-mono truncate">{table.name}</h4>
        {resolved && resolved.sql_name !== table.name && (
          <span
            title="The table's name in the database"
            className="text-[10px] font-mono text-[var(--color-text-tertiary)] truncate"
          >
            ({resolved.sql_name})
          </span>
        )}
        {issueCount > 0 && (
          <span
            title="This table has schema problems — see the list above"
            className="ml-auto flex items-center gap-1 text-[10px] font-semibold text-[var(--color-warning)] flex-shrink-0"
          >
            <AlertTriangle className="w-3 h-3" /> {issueCount}
          </span>
        )}
      </div>
      <p className="text-xs text-[var(--color-text-secondary)] mb-3 leading-relaxed">{table.purpose}</p>

      {resolved ? (
        <>
          <div className="space-y-1">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="text-xs font-mono text-[var(--color-text-primary)]">id</span>
              <TypeBadge type="integer" declared />
              <span
                title="Primary key — created automatically"
                className={`${BADGE} bg-[var(--color-warning-light)] text-[var(--color-warning)] inline-flex items-center gap-0.5`}
              >
                <KeyRound className="w-2.5 h-2.5" /> PK
              </span>
            </div>
            {ownFields.map((field, j) => {
              const col = resolved.columns.find((c) => sameField(c.name, field));
              return (
                <div key={j} className="flex items-center gap-1.5 flex-wrap">
                  <span className="text-xs font-mono text-[var(--color-text-primary)]">{field}</span>
                  {col ? (
                    <>
                      <TypeBadge type={col.type} declared={col.declared} />
                      <ColumnBadges col={col} unique={isUniqueColumn(col, resolved)} />
                    </>
                  ) : (
                    <span
                      title="This field has a problem (see above), so it isn't generated yet"
                      className={`${BADGE} bg-[var(--color-warning-light)] text-[var(--color-warning)] font-sans`}
                    >
                      not generated
                    </span>
                  )}
                </div>
              );
            })}
          </div>
          <p className="mt-1.5 text-[10px] text-[var(--color-text-tertiary)]">
            + created_at, updated_at (set automatically)
          </p>

          {resolved.checks.length > 0 && (
            <div className="mt-3">
              <p className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-tertiary)] mb-1">
                <ShieldCheck className="w-3 h-3" /> Checks
              </p>
              <div className="space-y-1">
                {resolved.checks.map((chk, k) => (
                  <div key={k} className="text-xs leading-snug">
                    <span className="font-medium text-[var(--color-text-secondary)]">{chk.name}: </span>
                    <code className="font-mono text-[var(--color-text-primary)] break-all">{chk.sql}</code>
                  </div>
                ))}
              </div>
            </div>
          )}

          {resolved.indexes.length > 0 && (
            <div className="mt-3">
              <p className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-tertiary)] mb-1">
                <ListChecks className="w-3 h-3" /> Indexes
              </p>
              <div className="flex flex-wrap gap-1.5">
                {resolved.indexes.map((ix, k) => (
                  <span
                    key={k}
                    title={ix.name}
                    className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-[var(--color-surface)] border border-[var(--color-border)] text-xs font-mono text-[var(--color-text-secondary)]"
                  >
                    ({ix.columns.join(", ")})
                    {ix.unique && (
                      <span className={`${BADGE} bg-[var(--color-accent-light)] text-[var(--color-accent)]`}>UNIQUE</span>
                    )}
                  </span>
                ))}
              </div>
            </div>
          )}

          {resolved.seed_row_count > 0 && (
            <p className="mt-3 flex items-center gap-1 text-xs text-[var(--color-text-tertiary)]">
              <Rows3 className="w-3 h-3" />
              {resolved.seed_row_count} starter row{resolved.seed_row_count === 1 ? "" : "s"} (seed data)
            </p>
          )}
        </>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {table.key_fields.map((field, j) => (
            <span
              key={j}
              className="px-2 py-1 rounded-md bg-[var(--color-surface)] text-[var(--color-text-tertiary)] text-xs font-mono border border-[var(--color-border)]"
            >
              {field}
            </span>
          ))}
        </div>
      )}
    </motion.div>
  );
}
