import { Loader2, XCircle } from "lucide-react";

import BabyTiger, { type TigerExpression } from "@/components/baby-tiger/BabyTiger";
import { GenerationJob, jobProgressPercent } from "@/lib/generationJob";

interface Props {
  message: string;
  job: GenerationJob | null;
  expression?: TigerExpression;
  onCancel?: () => void;
  isCancelling?: boolean;
}

/**
 * What a long generation looks like while it runs.
 *
 * These runs make one AI call per screen (and per table, for code), so
 * on a big project they take minutes and there is nothing useful to say
 * with a lone spinner. The job reports which step it is on, so show
 * that — and a way out, since the alternative to cancelling used to be
 * closing the app.
 */
export default function GenerationProgress({
  message,
  job,
  expression = "thinking",
  onCancel,
  isCancelling,
}: Props) {
  const percent = jobProgressPercent(job);
  const isRunning = job?.status === "running" || job?.status === "queued";

  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-4 bg-[var(--color-background)] px-6">
      <BabyTiger size={100} expression={expression} />
      <p className="text-[var(--color-text-secondary)] text-sm text-center">{message}</p>

      {job && job.total_steps > 0 && (
        <div className="w-full max-w-sm flex flex-col gap-2">
          <div className="h-1.5 w-full rounded-full bg-[var(--color-surface-raised)] overflow-hidden">
            <div
              className="h-full rounded-full bg-[var(--color-primary)] transition-[width] duration-500 ease-out"
              style={{ width: `${percent ?? 0}%` }}
            />
          </div>
          <div className="flex items-center justify-between gap-3 text-xs text-[var(--color-text-tertiary)]">
            <span className="truncate">{job.current_step || "Getting started…"}</span>
            <span className="flex-shrink-0 font-mono">
              {job.completed_steps}/{job.total_steps}
            </span>
          </div>
        </div>
      )}

      {job && (
        <p className="text-xs text-[var(--color-text-tertiary)] text-center max-w-sm">
          This keeps going if you close the app — reopen this screen to pick it back up.
        </p>
      )}

      {onCancel && isRunning && (
        <button
          onClick={onCancel}
          disabled={isCancelling || job?.cancel_requested}
          className="flex items-center gap-2 px-4 py-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] text-[var(--color-text-secondary)] text-xs font-medium hover:bg-[var(--color-surface-raised)] transition-colors disabled:opacity-60"
        >
          {isCancelling || job?.cancel_requested ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <XCircle className="w-3.5 h-3.5" />
          )}
          {job?.cancel_requested ? "Stopping after this step…" : "Stop"}
        </button>
      )}
    </div>
  );
}
