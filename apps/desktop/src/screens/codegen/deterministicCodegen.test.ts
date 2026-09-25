import { AxiosError, InternalAxiosRequestConfig } from "axios";
import { beforeAll, describe, expect, it } from "vitest";
import {
  acceptsDeterministicStatus,
  detailToText,
  deterministicRequestBody,
  findRevisionFile,
  interpretDeterministicResponse,
  isDestructiveLine,
  MigrationsInfo,
  newRevisions,
  parseMigrations,
  refusalFixTarget,
  requestDeterministicCodegen,
  unmatchedDestructiveLines,
} from "./deterministicCodegen";

// The real apiClient's request interceptor reads localStorage, which
// vitest's "node" environment doesn't have (same stub as lib/api.test.ts).
beforeAll(() => {
  const store = new Map<string, string>();
  (globalThis as any).localStorage = {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
    clear: () => store.clear(),
  };
});

const MIGRATIONS = {
  tool: "alembic",
  run_hint: "cd backend && alembic upgrade head",
  revisions: [
    {
      id: "0001",
      filename: "backend/migrations/versions/0001_initial.py",
      summary: ["create table products", "insert 2 seed row(s) into products"],
      destructive: [],
      created_at: "2026-09-24T10:00:00+00:00",
    },
    {
      id: "0002",
      filename: "0002_products_price.py",
      summary: [
        "change products.price: type float → decimal",
        "drop column products.legacy_code (deletes its data)",
        "add column products.sku (string)",
      ],
      destructive: [
        "change products.price: type float → decimal (existing values may not convert)",
        "drop column products.legacy_code (deletes its data)",
      ],
      created_at: null,
    },
  ],
};

describe("parseMigrations", () => {
  it("reads the contract shape", () => {
    const parsed = parseMigrations(MIGRATIONS)!;
    expect(parsed.tool).toBe("alembic");
    expect(parsed.run_hint).toBe("cd backend && alembic upgrade head");
    expect(parsed.revisions.map((r) => r.id)).toEqual(["0001", "0002"]);
    expect(parsed.revisions[1]?.destructive).toHaveLength(2);
    expect(parsed.revisions[1]?.created_at).toBeNull();
  });

  it("is null when there are no migrations", () => {
    expect(parseMigrations(null)).toBeNull();
    expect(parseMigrations(undefined)).toBeNull();
    expect(parseMigrations([])).toBeNull();
    expect(parseMigrations({})).toBeNull();
  });

  it("skips malformed revisions instead of failing", () => {
    const parsed = parseMigrations({
      tool: "migrate-mongo",
      revisions: [null, "x", { id: 3, filename: "0003-add-sku.js", summary: ["ok", 5], destructive: "no" }, {}],
    })!;
    expect(parsed.revisions).toEqual([
      { id: "3", filename: "0003-add-sku.js", summary: ["ok"], destructive: [], created_at: null },
    ]);
    expect(parsed.run_hint).toBe("");
  });
});

describe("destructive highlighting", () => {
  const rev = parseMigrations(MIGRATIONS)!.revisions[1]!;

  it("matches summary lines verbatim or with a parenthesized note", () => {
    expect(isDestructiveLine(rev.summary[0]!, rev.destructive)).toBe(true);
    expect(isDestructiveLine(rev.summary[1]!, rev.destructive)).toBe(true);
    expect(isDestructiveLine(rev.summary[2]!, rev.destructive)).toBe(false);
  });

  it("doesn't let one column's line match a longer column name", () => {
    expect(
      isDestructiveLine("change products.price: type float → decimal", [
        "change products.price_x: type float → decimal (existing values may not convert)",
      ])
    ).toBe(false);
  });

  it("surfaces destructive entries no summary line covers", () => {
    expect(unmatchedDestructiveLines(rev)).toEqual([]);
    expect(unmatchedDestructiveLines({ ...rev, summary: [] })).toEqual(rev.destructive);
  });
});

describe("revisions and files", () => {
  it("lists only the revisions a run added", () => {
    const before: MigrationsInfo = { ...parseMigrations(MIGRATIONS)!, revisions: parseMigrations(MIGRATIONS)!.revisions.slice(0, 1) };
    const after = parseMigrations(MIGRATIONS);
    expect(newRevisions(before, after).map((r) => r.id)).toEqual(["0002"]);
    expect(newRevisions(null, after).map((r) => r.id)).toEqual(["0001", "0002"]);
    expect(newRevisions(after, after)).toEqual([]);
    expect(newRevisions(after, null)).toEqual([]);
  });

  it("finds a revision's file by exact path or by file name", () => {
    const files = [
      { path: "backend/migrations/versions/0001_initial.py" },
      { path: "backend/migrations/versions/0002_products_price.py" },
      { path: "backend/main.py" },
    ];
    expect(findRevisionFile(files, "backend/migrations/versions/0001_initial.py")).toBe(files[0]);
    expect(findRevisionFile(files, "0002_products_price.py")).toBe(files[1]);
    // A bare name must match a whole path segment, not any suffix.
    expect(findRevisionFile(files, "main.py")).toBe(files[2]);
    expect(findRevisionFile(files, "ain.py")).toBeUndefined();
    expect(findRevisionFile(files, "")).toBeUndefined();
  });
});

describe("detailToText", () => {
  it("keeps a multi-line string detail intact", () => {
    const detail = "Fix these before generating:\n• one\n• two";
    expect(detailToText(detail)).toBe(detail);
  });

  it("renders lists and objects readably", () => {
    expect(detailToText([{ msg: "field required" }, "plain"])).toBe("• field required\n• plain");
    expect(detailToText({ message: "Would lose data:", changes: ["drop table x"] })).toBe(
      "Would lose data:\n• drop table x"
    );
    expect(detailToText({ odd: 1 })).toBe('{"odd":1}');
    expect(detailToText(undefined)).toBe("");
  });
});

describe("refusalFixTarget", () => {
  it("sends only the unsupported-stack refusal to Stack Selection", () => {
    expect(
      refusalFixTarget(
        "Deterministic (schema-driven, no-AI) code generation currently supports React + FastAPI only. " +
          "Pick one of those combinations in Stack Selection, or use AI-generated code for this project's stack."
      )
    ).toBe("stack");
    expect(refusalFixTarget("Architecture must be approved before generating code.")).toBe("architecture");
    expect(refusalFixTarget('Fix these before generating code:\n• "orders.total" is a new required field')).toBe(
      "architecture"
    );
  });
});

describe("request body and status handling", () => {
  it("only sends allow_destructive_migration after a yes", () => {
    expect(deterministicRequestBody("p1", false)).toEqual({ project_id: "p1" });
    expect(deterministicRequestBody("p1", true)).toEqual({ project_id: "p1", allow_destructive_migration: true });
  });

  it("treats 400 and 409 as answers, everything else non-2xx as errors", () => {
    expect([200, 201, 400, 409].every(acceptsDeterministicStatus)).toBe(true);
    expect([401, 403, 404, 422, 500, 503].some(acceptsDeterministicStatus)).toBe(false);
  });

  it("classifies responses", () => {
    expect(interpretDeterministicResponse(409, { detail: "drop table x" })).toEqual({
      kind: "needs_confirmation",
      detail: "drop table x",
    });
    expect(interpretDeterministicResponse(400, { detail: "Fix these:\n• a" })).toEqual({
      kind: "refused",
      detail: "Fix these:\n• a",
    });
    // An empty detail still produces something to show.
    expect(interpretDeterministicResponse(409, {}).kind).toBe("needs_confirmation");
    expect((interpretDeterministicResponse(400, null) as { detail: string }).detail).not.toBe("");

    const ok = interpretDeterministicResponse(200, { codegen: { files: [] }, migrations: MIGRATIONS });
    expect(ok.kind).toBe("generated");
    expect(ok.kind === "generated" && ok.migrations?.revisions).toHaveLength(2);
    const noMigrations = interpretDeterministicResponse(200, { codegen: { files: [] }, migrations: null });
    expect(noMigrations.kind === "generated" && noMigrations.migrations).toBeNull();
  });
});

// Through the app's real apiClient, so the interaction with its error
// interceptor (which turns every rejection into a status-less Error) is
// exercised for real. The adapter settles like axios's own adapters do:
// resolve when config.validateStatus accepts the status, else reject.
describe("requestDeterministicCodegen via the real apiClient", () => {
  async function clientAnswering(status: number, data: unknown) {
    const { apiClient } = await import("@/lib/api");
    const sent: { url?: string; body: any }[] = [];
    apiClient.defaults.adapter = async (config: InternalAxiosRequestConfig) => {
      sent.push({ url: config.url, body: config.data ? JSON.parse(config.data as string) : undefined });
      const response = { data, status, statusText: "", headers: {}, config, request: {} };
      if (!config.validateStatus || config.validateStatus(status)) return response as any;
      throw new AxiosError(
        `Request failed with status code ${status}`,
        AxiosError.ERR_BAD_RESPONSE,
        config,
        {},
        response as any
      );
    };
    return { apiClient, sent };
  }

  it("turns a 409 into a confirmation, then retries with the flag", async () => {
    const { apiClient, sent } = await clientAnswering(409, {
      detail: "This migration would:\n• drop column products.legacy_code (deletes its data)",
    });
    const first = await requestDeterministicCodegen(apiClient, "p1");
    expect(first).toEqual({
      kind: "needs_confirmation",
      detail: "This migration would:\n• drop column products.legacy_code (deletes its data)",
    });
    expect(sent[0]).toEqual({ url: "/codegen/generate-deterministic", body: { project_id: "p1" } });

    const { apiClient: retryClient, sent: retrySent } = await clientAnswering(200, {
      success: true,
      codegen: { summary: "", files: [] },
      migrations: MIGRATIONS,
    });
    const second = await requestDeterministicCodegen(retryClient, "p1", true);
    expect(second.kind).toBe("generated");
    expect(retrySent[0]?.body).toEqual({ project_id: "p1", allow_destructive_migration: true });
  });

  it("keeps a 400's full multi-line detail", async () => {
    const detail = "Fix these before generating code:\n• Table \"orders\" has a blank field name.\n• Check \"p\" on \"orders\": bad";
    const { apiClient } = await clientAnswering(400, { detail });
    expect(await requestDeterministicCodegen(apiClient, "p1")).toEqual({ kind: "refused", detail });
  });

  it("still rejects other errors with the interceptor's message", async () => {
    const { apiClient } = await clientAnswering(404, { detail: "Project not found." });
    await expect(requestDeterministicCodegen(apiClient, "p1")).rejects.toThrow("Project not found.");
  });
});
