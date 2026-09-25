// ─── Deterministic codegen: the two answers that aren't "done" ───
//
//   - DestructiveMigrationDialog: the backend answered 409 — this run's
//     migration would drop a table/column or change a column's type, so
//     it wrote nothing and needs an explicit go-ahead. "Generate anyway"
//     retries the same request with allow_destructive_migration: true.
//   - GenerationRefusedPanel: the backend answered 400 — the schema can't
//     be generated as it stands (structural issues, or a change no
//     migration can apply safely). The detail lists every problem on its
//     own line; a toast would squash that into one unreadable run-on.

import { useEffect } from "react";
import { motion } from "framer-motion";
import { AlertTriangle, Pencil, X } from "lucide-react";

export function DestructiveMigrationDialog({
  detail,
  onCancel,
  onConfirm,
}: {
  detail: string;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  // Escape cancels wherever focus happens to be — cancelling is the safe
  // choice, so it's also the one that gets initial focus below.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-6">
      <motion.div
        initial={{ opacity: 0, scale: 0.97 }}
        animate={{ opacity: 1, scale: 1 }}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="destructive-migration-title"
        className="bg-[var(--color-surface)] rounded-2xl p-5 max-w-lg w-full border border-[var(--color-border)] shadow-xl"
      >
        <div className="flex items-start gap-3 mb-3">
          <div className="p-2 rounded-xl bg-[var(--color-error-light)] flex-shrink-0">
            <AlertTriangle className="w-4 h-4 text-[var(--color-error)]" />
          </div>
          <div>
            <p id="destructive-migration-title" className="text-sm font-semibold text-[var(--color-text-primary)]">
              This regeneration can delete data
            </p>
            <p className="mt-0.5 text-xs text-[var(--color-text-secondary)] leading-relaxed">
              Its database migration changes your schema in a way that can remove or fail to convert data
              already stored in any database it runs against:
            </p>
          </div>
        </div>
        <p className="max-h-60 overflow-y-auto whitespace-pre-line rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-3 text-xs font-mono text-[var(--color-text-primary)] leading-relaxed">
          {detail}
        </p>
        <p className="mt-3 text-xs text-[var(--color-text-tertiary)] leading-relaxed">
          Back up any database you've already deployed before running the new migration. Cancel keeps the
          current code — you can change the tables in Architecture instead.
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <button
            autoFocus
            onClick={onCancel}
            className="px-4 py-2 rounded-xl border border-[var(--color-border)] text-xs font-medium text-[var(--color-text-primary)] hover:bg-[var(--color-surface-raised)] transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="px-4 py-2 rounded-xl bg-[var(--color-error)] text-white text-xs font-semibold hover:opacity-90 transition-opacity"
          >
            Generate anyway
          </button>
        </div>
      </motion.div>
    </div>
  );
}

export function GenerationRefusedPanel({
  detail,
  onDismiss,
  fixLabel,
  onFix,
  className = "",
}: {
  detail: string;
  onDismiss: () => void;
  /** e.g. "Fix in Architecture" — where this particular refusal gets fixed. */
  fixLabel: string;
  onFix: () => void;
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={`flex items-start gap-2 rounded-xl border border-[var(--color-error)] bg-[var(--color-error-light)] px-4 py-3 ${className}`}
    >
      <AlertTriangle className="w-3.5 h-3.5 text-[var(--color-error)] flex-shrink-0 mt-0.5" />
      <div className="flex-1 min-w-0">
        <p className="text-xs font-semibold text-[var(--color-text-primary)]">
          No-AI code generation couldn't run
        </p>
        <p className="mt-1 max-h-48 overflow-y-auto text-xs text-[var(--color-text-secondary)] leading-relaxed whitespace-pre-line">
          {detail}
        </p>
        <button
          onClick={onFix}
          className="mt-2 flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium text-[var(--color-primary)] hover:bg-[var(--color-surface)] transition-colors"
        >
          <Pencil className="w-3 h-3" /> {fixLabel}
        </button>
      </div>
      <button
        onClick={onDismiss}
        title="Dismiss"
        className="p-0.5 rounded text-[var(--color-text-tertiary)] hover:text-[var(--color-text-primary)] flex-shrink-0"
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}
