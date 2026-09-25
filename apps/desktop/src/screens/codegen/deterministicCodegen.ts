// ─── Deterministic ("No AI") code generation — request + migrations ───
//
// Pure helpers behind CodeGenScreen's "Deterministic" / "Regenerate (No
// AI)" actions, kept out of the component so they can be unit-tested
// (deterministicCodegen.test.ts).
//
// Every deterministic run that changes the database schema also writes a
// new, versioned migration for the generated app (Alembic for FastAPI,
// migrate-mongo for Express). POST /codegen/generate-deterministic can
// therefore answer in three ways, and only one of them is a failure:
//   - 2xx  the code (and any new migration) was written
//   - 409  the new migration would lose data (drop a table/column, change
//          a column's type) — nothing was written; the user decides, and
//          a "yes" retries with allow_destructive_migration: true
//   - 400  the schema can't be generated as it stands (structural issues
//          or a change no migration can apply safely) — the detail lists
//          every problem, one per line, so it needs a readable panel
// The shared axios interceptor (lib/api.ts) turns any non-2xx into a bare
// Error and drops the status, so the request accepts 400/409 as ordinary
// responses and classifies them here instead.

import type { AxiosInstance } from "axios";

export const DETERMINISTIC_ENDPOINT = "/codegen/generate-deterministic";

/** One versioned migration. Revisions are append-only: each regeneration
 *  that changes the schema adds one, and earlier ones never change. */
export interface MigrationRevision {
  id: string;
  filename: string;
  /** One human-readable line per change. */
  summary: string[];
  /** The changes in this revision that can permanently lose data. */
  destructive: string[];
  created_at: string | null;
}

export interface MigrationsInfo {
  tool: string;
  revisions: MigrationRevision[];
  /** How to apply them by hand (the generated app also runs them on startup). */
  run_hint: string;
}

const TOOL_LABELS: Record<string, string> = {
  alembic: "Alembic",
  "migrate-mongo": "migrate-mongo",
};

export function migrationToolLabel(tool: string): string {
  return TOOL_LABELS[tool] ?? tool;
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((v): v is string => typeof v === "string" && v.trim() !== "");
}

function idText(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return "";
}

/** The `migrations` field of GET /codegen/{id} or a generate response, or
 *  null when there is none (AI-generated code, an older backend, or a
 *  project generated before migrations existed). Malformed revisions are
 *  skipped rather than breaking the screen. */
export function parseMigrations(raw: unknown): MigrationsInfo | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const obj = raw as Record<string, unknown>;
  const revisions: MigrationRevision[] = [];
  for (const item of Array.isArray(obj.revisions) ? obj.revisions : []) {
    if (!item || typeof item !== "object") continue;
    const rev = item as Record<string, unknown>;
    const id = idText(rev.id);
    const filename = typeof rev.filename === "string" ? rev.filename.trim() : "";
    if (!id && !filename) continue;
    revisions.push({
      id: id || filename,
      filename,
      summary: stringList(rev.summary),
      destructive: stringList(rev.destructive),
      created_at: typeof rev.created_at === "string" && rev.created_at ? rev.created_at : null,
    });
  }
  const tool = typeof obj.tool === "string" ? obj.tool.trim() : "";
  if (!tool && revisions.length === 0) return null;
  return {
    tool,
    revisions,
    run_hint: typeof obj.run_hint === "string" ? obj.run_hint : "",
  };
}

/** Whether a summary line describes a data-losing change. The backend's
 *  destructive list repeats such a line verbatim, or with a note appended
 *  in parentheses ("… (existing values may not convert)"). The " (" guard
 *  keeps "change orders.price: …" from matching "change orders.price_x: …". */
export function isDestructiveLine(line: string, destructive: string[]): boolean {
  return destructive.some((d) => d === line || d.startsWith(`${line} (`));
}

/** Destructive entries that don't correspond to any summary line — shown
 *  on their own so a warning can never be silently lost. */
export function unmatchedDestructiveLines(rev: MigrationRevision): string[] {
  return rev.destructive.filter(
    (d) => !rev.summary.some((line) => d === line || d.startsWith(`${line} (`))
  );
}

export function revisionCanLoseData(rev: MigrationRevision): boolean {
  return rev.destructive.length > 0;
}

/** Revisions in `next` that weren't in `prev` — what this run added. */
export function newRevisions(prev: MigrationsInfo | null, next: MigrationsInfo | null): MigrationRevision[] {
  if (!next) return [];
  const known = new Set((prev?.revisions ?? []).map((r) => r.id));
  return next.revisions.filter((r) => !known.has(r.id));
}

/** The generated file a revision lives in. `filename` may be a bare file
 *  name or a path; an exact path match wins over a suffix match. */
export function findRevisionFile<F extends { path: string }>(files: F[], filename: string): F | undefined {
  const name = filename.trim().replace(/\\/g, "/");
  if (!name) return undefined;
  return files.find((f) => f.path === name) ?? files.find((f) => f.path.endsWith(`/${name.replace(/^\/+/, "")}`));
}

/** FastAPI's `detail` as readable text: a string as-is, a 422-style list
 *  one entry per line, an object by its message plus any listed changes
 *  (never "[object Object]"). */
export function detailToText(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        if (typeof d === "string") return `• ${d}`;
        if (d && typeof d === "object" && "msg" in d) return `• ${String((d as { msg: unknown }).msg)}`;
        return `• ${JSON.stringify(d)}`;
      })
      .join("\n");
  }
  if (detail && typeof detail === "object") {
    const d = detail as { message?: unknown; changes?: unknown; destructive?: unknown; issues?: unknown };
    const list = [d.changes, d.destructive, d.issues].find(Array.isArray) as unknown[] | undefined;
    const head = typeof d.message === "string" ? d.message : "";
    const lines = (list ?? []).map((c) => `• ${typeof c === "string" ? c : JSON.stringify(c)}`);
    const text = [head, ...lines].filter(Boolean).join("\n");
    return text || JSON.stringify(detail);
  }
  return "";
}

/** Where a refused (400) run gets fixed. Only the unsupported-stack
 *  refusal points at Stack Selection (its message says so); everything
 *  else — not approved yet, no tables, schema problems, a change no
 *  migration can apply — is fixed in Architecture. */
export function refusalFixTarget(detail: string): "stack" | "architecture" {
  return /stack selection/i.test(detail) ? "stack" : "architecture";
}

export function deterministicRequestBody(
  projectId: string,
  allowDestructiveMigration: boolean
): { project_id: string; allow_destructive_migration?: true } {
  // Only sent when the user said yes, so a plain run never carries it.
  return allowDestructiveMigration
    ? { project_id: projectId, allow_destructive_migration: true }
    : { project_id: projectId };
}

/** 400 and 409 are answers, not failures — see the header. */
export function acceptsDeterministicStatus(status: number): boolean {
  return (status >= 200 && status < 300) || status === 400 || status === 409;
}

export type DeterministicOutcome =
  | { kind: "generated"; data: any; migrations: MigrationsInfo | null }
  | { kind: "needs_confirmation"; detail: string }
  | { kind: "refused"; detail: string };

const CONFIRM_FALLBACK =
  "This regeneration's database migration would delete or convert data that may already exist.";
const REFUSED_FALLBACK = "The code couldn't be generated from this project's schema.";

export function interpretDeterministicResponse(status: number, data: unknown): DeterministicOutcome {
  const detail = detailToText((data as { detail?: unknown } | null)?.detail);
  if (status === 409) return { kind: "needs_confirmation", detail: detail || CONFIRM_FALLBACK };
  if (status === 400) return { kind: "refused", detail: detail || REFUSED_FALLBACK };
  const body = (data ?? {}) as { migrations?: unknown };
  return { kind: "generated", data, migrations: parseMigrations(body.migrations) };
}

/** Runs one deterministic generation. Anything other than 2xx/400/409
 *  (network down, 404, 500…) still rejects with the interceptor's
 *  normalized Error, exactly like every other call in the app. */
export async function requestDeterministicCodegen(
  client: Pick<AxiosInstance, "post">,
  projectId: string,
  allowDestructiveMigration = false
): Promise<DeterministicOutcome> {
  const response = await client.post(
    DETERMINISTIC_ENDPOINT,
    deterministicRequestBody(projectId, allowDestructiveMigration),
    { validateStatus: acceptsDeterministicStatus }
  );
  return interpretDeterministicResponse(response.status, response.data);
}
