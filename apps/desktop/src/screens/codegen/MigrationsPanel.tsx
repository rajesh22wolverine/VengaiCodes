// ─── "Database migrations" panel for the Code Generation screen ───
//
// The deterministic generator ships real, versioned migrations with the
// app it builds (Alembic for FastAPI, migrate-mongo for Express); every
// regeneration that changes the schema appends a revision. This panel is
// the user's view of that history: which tool runs them, what each
// revision changes, which changes can lose existing data (highlighted),
// and how to run them by hand. Clicking a revision's file name opens its
// code in the preview next to it.

import { AlertTriangle, ChevronDown, ChevronRight, Database, Terminal } from "lucide-react";
import {
  isDestructiveLine,
  MigrationsInfo,
  migrationToolLabel,
  revisionCanLoseData,
  unmatchedDestructiveLines,
} from "./deterministicCodegen";

function formatCreatedAt(value: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export default function MigrationsPanel({
  migrations,
  open,
  onToggle,
  onOpenFile,
  hasFile,
  fromEarlierRun = false,
}: {
  migrations: MigrationsInfo;
  open: boolean;
  onToggle: () => void;
  onOpenFile: (filename: string) => void;
  hasFile: (filename: string) => boolean;
  /** The code on screen is AI-generated, so these revisions describe the
   *  last No-AI run rather than the files shown. */
  fromEarlierRun?: boolean;
}) {
  const tool = migrationToolLabel(migrations.tool) || "Migrations";
  const count = migrations.revisions.length;
  const risky = migrations.revisions.filter(revisionCanLoseData).length;

  return (
    <div className="border-b border-[var(--color-border)] bg-[var(--color-surface)] flex-shrink-0">
      <button
        onClick={onToggle}
        aria-expanded={open}
        className="w-full flex items-center gap-2 px-6 py-2.5 text-left hover:bg-[var(--color-surface-raised)] transition-colors"
      >
        {open ? (
          <ChevronDown className="w-3.5 h-3.5 text-[var(--color-text-tertiary)]" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 text-[var(--color-text-tertiary)]" />
        )}
        <Database className="w-3.5 h-3.5 text-[var(--color-primary)]" />
        <span className="text-xs font-semibold text-[var(--color-text-primary)]">Database migrations</span>
        <span className="text-xs text-[var(--color-text-tertiary)]">
          {tool} · {count} revision{count === 1 ? "" : "s"}
        </span>
        {risky > 0 && (
          <span className="flex items-center gap-1 text-xs font-medium text-[var(--color-error)]">
            <AlertTriangle className="w-3 h-3" />
            {risky} can delete data
          </span>
        )}
      </button>

      {open && (
        <div className="px-6 pb-4 max-h-72 overflow-y-auto">
          <div className="max-w-3xl space-y-2">
            {fromEarlierRun && (
              <p className="text-xs text-[var(--color-text-tertiary)] leading-relaxed">
                Recorded by the last No-AI generation — the AI-generated code shown here doesn't include
                these migration files.
              </p>
            )}
            {migrations.run_hint && (
              <div className="flex items-start gap-2 rounded-lg bg-[var(--color-surface-raised)] border border-[var(--color-border)] px-3 py-2">
                <Terminal className="w-3.5 h-3.5 text-[var(--color-text-tertiary)] flex-shrink-0 mt-0.5" />
                <p className="text-xs text-[var(--color-text-secondary)] leading-relaxed whitespace-pre-line font-mono">
                  {migrations.run_hint}
                </p>
              </div>
            )}

            {count === 0 && (
              <p className="text-xs text-[var(--color-text-tertiary)]">No revisions yet.</p>
            )}

            {migrations.revisions.map((rev) => {
              const canLoseData = revisionCanLoseData(rev);
              const extraWarnings = unmatchedDestructiveLines(rev);
              const created = formatCreatedAt(rev.created_at);
              return (
                <div
                  key={rev.id}
                  className={`rounded-lg border px-3 py-2 ${
                    canLoseData
                      ? "border-[var(--color-error)] bg-[var(--color-error-light)]"
                      : "border-[var(--color-border)] bg-[var(--color-surface-raised)]"
                  }`}
                >
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs font-bold font-mono text-[var(--color-text-primary)]">{rev.id}</span>
                    {rev.filename &&
                      (hasFile(rev.filename) ? (
                        <button
                          onClick={() => onOpenFile(rev.filename)}
                          title="Show this migration's code"
                          className="text-xs font-mono text-[var(--color-primary)] hover:underline"
                        >
                          {rev.filename}
                        </button>
                      ) : (
                        <span className="text-xs font-mono text-[var(--color-text-secondary)]">{rev.filename}</span>
                      ))}
                    {canLoseData && (
                      <span className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--color-error)]">
                        <AlertTriangle className="w-3 h-3" /> can delete data
                      </span>
                    )}
                    {created && <span className="ml-auto text-[10px] text-[var(--color-text-tertiary)]">{created}</span>}
                  </div>

                  {rev.summary.length > 0 && (
                    <ul className="mt-1 space-y-0.5">
                      {rev.summary.map((line, i) => {
                        const destructive = isDestructiveLine(line, rev.destructive);
                        return (
                          <li
                            key={i}
                            className={`flex items-start gap-1 text-xs leading-relaxed ${
                              destructive
                                ? "text-[var(--color-error)] font-medium"
                                : "text-[var(--color-text-secondary)]"
                            }`}
                          >
                            {destructive ? (
                              <AlertTriangle className="w-3 h-3 flex-shrink-0 mt-0.5" />
                            ) : (
                              <span className="w-3 flex-shrink-0 text-center">•</span>
                            )}
                            <span>{line}</span>
                          </li>
                        );
                      })}
                    </ul>
                  )}

                  {/* A data-losing change the summary doesn't spell out
                      itself must still be visible. */}
                  {extraWarnings.length > 0 && (
                    <ul className="mt-1 space-y-0.5">
                      {extraWarnings.map((line, i) => (
                        <li key={i} className="flex items-start gap-1 text-xs font-medium text-[var(--color-error)]">
                          <AlertTriangle className="w-3 h-3 flex-shrink-0 mt-0.5" />
                          <span>{line}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
