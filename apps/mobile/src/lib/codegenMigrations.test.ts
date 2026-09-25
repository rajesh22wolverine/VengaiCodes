import { describe, expect, it } from "vitest";
import {
  formatRevisionTime,
  interpretDeterministicResponse,
  migrationToolLabel,
  parseMigrationInfo,
  revisionsNewestFirst,
} from "./codegenMigrations";

describe("parseMigrationInfo", () => {
  it("is null when there are no migrations (older backend or AI mode)", () => {
    expect(parseMigrationInfo(undefined)).toBeNull();
    expect(parseMigrationInfo(null)).toBeNull();
  });

  it("reads the backend's public_migration_info shape", () => {
    const info = parseMigrationInfo({
      tool: "alembic",
      revisions: [
        {
          id: "0001",
          filename: "0001_initial.py",
          summary: ["Create table customers", "Create table orders"],
          destructive: [],
          created_at: "2026-09-24T10:00:00+00:00",
        },
      ],
      run_hint: "cd backend && alembic upgrade head",
    });
    expect(info).toEqual({
      tool: "alembic",
      revisions: [
        {
          id: "0001",
          filename: "0001_initial.py",
          summary: ["Create table customers", "Create table orders"],
          destructive: [],
          created_at: "2026-09-24T10:00:00+00:00",
        },
      ],
      run_hint: "cd backend && alembic upgrade head",
    });
  });

  it("tolerates a partial shape instead of throwing", () => {
    const info = parseMigrationInfo({ tool: "migrate-mongo", revisions: [null, { id: 2, summary: "x" }] });
    expect(info?.revisions).toEqual([{ id: "2", filename: "", summary: [], destructive: [], created_at: null }]);
    expect(info?.run_hint).toBe("");
  });
});

describe("revision display", () => {
  it("orders newest first by the numbered filename", () => {
    const revs = ["0002-add-tags.js", "0010-drop-notes.js", "0001-initial.js"].map((filename, i) => ({
      id: String(i),
      filename,
      summary: [],
      destructive: [],
      created_at: null,
    }));
    expect(revisionsNewestFirst(revs).map((r) => r.filename)).toEqual([
      "0010-drop-notes.js",
      "0002-add-tags.js",
      "0001-initial.js",
    ]);
    // The input is left alone.
    expect(revs[0]?.filename).toBe("0002-add-tags.js");
  });

  it("names the tool and formats times", () => {
    expect(migrationToolLabel("alembic")).toBe("Alembic (SQLAlchemy)");
    expect(migrationToolLabel("migrate-mongo")).toBe("migrate-mongo (MongoDB)");
    expect(formatRevisionTime("2026-09-24T21:30:12.123456+00:00")).toBe("2026-09-24 21:30");
    expect(formatRevisionTime(null)).toBe("");
    expect(formatRevisionTime("yesterday")).toBe("yesterday");
  });
});

describe("interpretDeterministicResponse", () => {
  it("passes a success through", () => {
    const data = { codegen: { files: [] } };
    expect(interpretDeterministicResponse(200, data)).toEqual({ kind: "ok", data });
  });

  it("turns a 409 into a confirmation carrying the listed changes", () => {
    const detail = "This migration would:\n• drop column orders.notes";
    expect(interpretDeterministicResponse(409, { detail })).toEqual({ kind: "confirm-destructive", message: detail });
    expect(interpretDeterministicResponse(409, {}).kind).toBe("confirm-destructive");
  });

  it("shows a 400's full multi-line detail", () => {
    const detail = "Fix these before generating:\n• orders: bad check\n• tags: duplicate field";
    expect(interpretDeterministicResponse(400, { detail })).toEqual({ kind: "error", message: detail });
    expect(interpretDeterministicResponse(400, null)).toEqual({
      kind: "error",
      message: "Couldn't generate code deterministically.",
    });
  });
});
