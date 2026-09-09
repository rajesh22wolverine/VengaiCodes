// ─── Long-running AI generation, as a job to watch ───
//
// UI/UX design and code generation both make one AI call per screen (and
// per database table, for codegen), so how long they take grows with the
// project. They used to run inside a single POST that the client waited
// on, which meant a big project could never finish before something —
// the client's own timeout, a proxy, a dropped wifi connection — cut the
// request, and every file already generated was thrown away with it.
//
// The backend now runs them as a background job (POST /{phase}/start)
// that saves after every step. This module starts one and follows it
// with cheap polls, so nothing depends on holding a socket open, and a
// user who closes the app mid-run finds the work waiting when they
// come back.

import apiClient from "@/lib/api";

export type GenerationPhase = "codegen" | "uiux";

export type GenerationJobStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled";

export interface GenerationJob {
  id: string;
  phase: string;
  status: GenerationJobStatus;
  /** The run's worker died (a backend restart) rather than the run
   *  itself failing — starting again resumes where it stopped. */
  interrupted?: boolean;
  total_steps: number;
  completed_steps: number;
  current_step: string | null;
  error: string | null;
  cancel_requested: boolean;
}

/** Thrown when the run stopped because someone asked it to. */
export class GenerationCancelled extends Error {
  constructor(message = "Generation was cancelled.") {
    super(message);
    this.name = "GenerationCancelled";
  }
}

const POLL_INTERVAL_MS = 2500;
// A poll failing is not the run failing — the run is on the server. Ride
// out a blip (a sleeping laptop, a dropped connection) rather than
// reporting a failure for a job that is still working.
const MAX_CONSECUTIVE_POLL_FAILURES = 10;
// A backend redeploy mid-run kills the worker. Restarting picks up from
// the last finished step, so do it for the user instead of making them
// leave the screen and come back — but only a couple of times, so a run
// that dies on the same step forever surfaces as the error it is.
const MAX_AUTO_RESUMES = 2;

const TERMINAL: GenerationJobStatus[] = ["succeeded", "failed", "cancelled"];

export function isTerminal(job: GenerationJob | null): boolean {
  return !!job && TERMINAL.includes(job.status);
}

/** 0–100, or null before the step count is known. */
export function jobProgressPercent(job: GenerationJob | null): number | null {
  if (!job || !job.total_steps) return null;
  return Math.min(100, Math.round((job.completed_steps / job.total_steps) * 100));
}

export async function fetchGenerationJob(
  phase: GenerationPhase,
  projectId: string
): Promise<GenerationJob | null> {
  const { data } = await apiClient.get(`/${phase}/${projectId}/job`);
  return data.job ?? null;
}

export async function cancelGenerationJob(
  phase: GenerationPhase,
  projectId: string
): Promise<GenerationJob | null> {
  const { data } = await apiClient.post(`/${phase}/cancel`, { project_id: projectId });
  return data.job ?? null;
}

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

interface RunOptions {
  phase: GenerationPhase;
  projectId: string;
  /** Called with every progress update, including the first. */
  onProgress?: (job: GenerationJob) => void;
  /** Return true to stop polling silently (the screen unmounted). */
  isAbandoned?: () => boolean;
}

/**
 * Start (or rejoin, or resume) the run and follow it to the end.
 *
 * Starting is idempotent on the server: if a run is already going for
 * this project it returns that one, and if an earlier attempt died
 * partway it picks up from the last finished step instead of paying for
 * those AI calls again.
 */
export async function runGenerationJob({
  phase,
  projectId,
  onProgress,
  isAbandoned,
}: RunOptions): Promise<GenerationJob> {
  let resumes = 0;

  for (;;) {
    const { data } = await apiClient.post(`/${phase}/start`, { project_id: projectId });
    let job: GenerationJob = data.job;
    onProgress?.(job);

    let consecutiveFailures = 0;

    while (!isTerminal(job)) {
      await delay(POLL_INTERVAL_MS);
      if (isAbandoned?.()) return job;

      try {
        const polled = await fetchGenerationJob(phase, projectId);
        consecutiveFailures = 0;
        if (polled) {
          job = polled;
          onProgress?.(job);
        }
      } catch (error) {
        consecutiveFailures += 1;
        if (consecutiveFailures >= MAX_CONSECUTIVE_POLL_FAILURES) throw error;
      }
    }

    if (job.status === "cancelled") throw new GenerationCancelled();

    if (job.status === "failed") {
      if (job.interrupted && resumes < MAX_AUTO_RESUMES) {
        resumes += 1;
        continue; // start again — the server resumes from the last step
      }
      throw new Error(job.error || "Generation failed. Please try again.");
    }

    return job;
  }
}
