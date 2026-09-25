// ─── Codegen — database migrations info ───
//
// The deterministic ("No AI") generator ships real, versioned database
// migrations with every app it builds: Alembic for React + FastAPI,
// migrate-mongo for Vue + Express. Each regenerate diffs the schema
// against the last one it built and adds a new revision rather than
// rewriting history, so a deployed app's database can be upgraded in
// place. POST /codegen/generate-deterministic and GET /codegen/{id}
// describe those revisions in a "migrations" block (the backend's
// migrations_gen.public_migration_info()).
//
// A revision that would lose data (dropping a table/column, changing a
// column's type) is refused with a 409 until the user confirms it — the
// confirm is a retry with allow_destructive_migration: true. The helpers
// below turn the raw responses into what the Codegen screen shows; they
// are pure so they can be unit-tested (codegenMigrations.test.ts).

import { detailToText } from "./schemaEditorView";

export type MigrationTool = "alembic" | "migrate-mongo";

export interface MigrationRevision {
  id: string;
  filename: string;
  /** One line per change, e.g. "Create table orders". */
  summary: string[];
  /** The data-losing subset of the changes (empty = safe). */
  destructive: string[];
  created_at: string | null;
}

export interface MigrationInfo {
  tool: MigrationTool | string;
  revisions: MigrationRevision[];
  /** How to run them by hand, e.g. "cd backend && alembic upgrade head". */
  run_hint: string;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}

/** Reads the "migrations" block defensively: null on an older backend
 *  (no block at all) or an AI-generated project (null), and never throws
 *  on a partial shape — this is display-only information. */
export function parseMigrationInfo(raw: unknown): MigrationInfo | null {
  if (!raw || typeof raw !== "object") return null;
  const data = raw as Record<string, unknown>;
  const revisions: MigrationRevision[] = (Array.isArray(data.revisions) ? data.revisions : [])
    .filter((r): r is Record<string, unknown> => !!r && typeof r === "object")
    .map((r) => ({
      id: typeof r.id === "string" ? r.id : String(r.id ?? ""),
      filename: typeof r.filename === "string" ? r.filename : "",
      summary: stringList(r.summary),
      destructive: stringList(r.destructive),
      created_at: typeof r.created_at === "string" ? r.created_at : null,
    }));
  return {
    tool: typeof data.tool === "string" ? data.tool : "",
    revisions,
    run_hint: typeof data.run_hint === "string" ? data.run_hint : "",
  };
}

export function migrationToolLabel(tool: string): string {
  if (tool === "alembic") return "Alembic (SQLAlchemy)";
  if (tool === "migrate-mongo") return "migrate-mongo (MongoDB)";
  return tool || "Migrations";
}

/** Newest first. Revision files are numbered with a zero-padded prefix
 *  (0001_…, 0002-…), so the filename orders them regardless of the order
 *  the list arrived in; the id breaks any tie. */
export function revisionsNewestFirst(revisions: MigrationRevision[]): MigrationRevision[] {
  return [...revisions].sort((a, b) => {
    const byFile = b.filename.localeCompare(a.filename);
    return byFile !== 0 ? byFile : b.id.localeCompare(a.id);
  });
}

/** "2026-09-24 21:30" from an ISO timestamp (the stored clock time) — or the
 *  raw text if it isn't one, or "" for none. */
export function formatRevisionTime(iso: string | null): string {
  if (!iso) return "";
  const m = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})/.exec(iso);
  return m ? `${m[1]} ${m[2]}` : iso;
}

// ─── POST /codegen/generate-deterministic outcomes ───

export type DeterministicOutcome =
  | { kind: "ok"; data: any }
  /** 409: the new migration would lose data — ask, then retry with
   *  allow_destructive_migration: true. */
  | { kind: "confirm-destructive"; message: string }
  /** 400 (schema issues, unsupported stack, migration blockers) or any
   *  other refusal — shown in full, it's often a multi-line list. */
  | { kind: "error"; message: string };

export function interpretDeterministicResponse(status: number, data: any): DeterministicOutcome {
  if (status >= 200 && status < 300) return { kind: "ok", data };
  const message = detailToText(data?.detail);
  if (status === 409) {
    return {
      kind: "confirm-destructive",
      message: message || "This regeneration's database migration would delete or convert existing data.",
    };
  }
  return { kind: "error", message: message || "Couldn't generate code deterministically." };
}
