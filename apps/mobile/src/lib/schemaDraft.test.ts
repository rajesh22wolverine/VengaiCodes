// The same cases as the desktop app's schemaDraft.test.ts: the two
// schemaDraft.ts copies must behave identically, so they're held to one
// spec. Mobile-only view helpers are tested in schemaEditorView.test.ts.
import { describe, expect, it } from "vitest";
import {
  addField,
  autoFieldType,
  draftToPayload,
  emptyDraftTable,
  indexFieldChoices,
  inferFieldType,
  isNoopSpec,
  locateIssue,
  removeField,
  removeTable,
  renameField,
  renameInExpression,
  renameTable,
  seedColumns,
  setFieldLink,
  setFieldRequired,
  setSeedCell,
  slug,
  tableSqlName,
  tableToDraft,
  toggleIndexField,
  upsertFieldSpec,
} from "./schemaDraft";
import { DraftTable } from "./schemaTypes";

function table(patch: Partial<DraftTable>): DraftTable {
  return { ...emptyDraftTable(), ...patch };
}

function unwrap<T>(result: { ok: true; value: T } | { ok: false; error: string }): T {
  if (!result.ok) throw new Error(`expected ok, got: ${result.error}`);
  return result.value;
}

describe("names mirror the backend", () => {
  it("slugs like codegen_shared._slug (blank becomes 'item')", () => {
    expect(slug("Unit Price")).toBe("unit_price");
    expect(slug("  __Order--Items__ ")).toBe("order_items");
    expect(slug("")).toBe("item");
  });

  it("pluralizes like db_schema.table_sql_name", () => {
    expect(tableSqlName("order")).toBe("orders");
    expect(tableSqlName("Orders")).toBe("orders");
  });

  it("infers the same types as db_schema.infer_field_type", () => {
    expect(inferFieldType("email")).toBe("string");
    expect(inferFieldType("price")).toBe("float");
    expect(inferFieldType("stock_count")).toBe("integer");
    expect(inferFieldType("is_active")).toBe("boolean");
    expect(inferFieldType("published_at")).toBe("datetime");
    expect(inferFieldType("description")).toBe("text");
    expect(inferFieldType("title")).toBe("string");
  });
});

describe("field spec emission rule", () => {
  it("emits a spec only when something is non-default", () => {
    const t = table({ key_fields: ["price"] });
    expect(upsertFieldSpec(t, "price", { unique: false }).field_specs).toEqual([]);

    const typed = upsertFieldSpec(t, "price", { type: "decimal" });
    expect(typed.field_specs).toEqual([
      { name: "price", type: "decimal", nullable: true, default: null, unique: false },
    ]);

    // Clearing the only declared thing removes the spec again.
    expect(upsertFieldSpec(typed, "price", { type: null }).field_specs).toEqual([]);
  });

  it("treats a blank default as no default", () => {
    const t = upsertFieldSpec(table({ key_fields: ["title"] }), "title", { default: "   " });
    expect(t.field_specs).toEqual([]);
    expect(isNoopSpec({ name: "x", type: "auto" as never, default: "" })).toBe(true);
  });

  it("keeps the key_fields spelling when a spec is matched by slug", () => {
    const t = table({
      key_fields: ["Unit Price"],
      field_specs: [{ name: "Unit Price", type: "decimal", nullable: true, default: null, unique: false }],
    });
    const next = upsertFieldSpec(t, "unit_price", { nullable: false });
    expect(next.field_specs[0]?.name).toBe("Unit Price");
    expect(next.field_specs[0]?.nullable).toBe(false);
  });

  it("Required moves an ON DELETE SET NULL link to RESTRICT", () => {
    const t = table({
      key_fields: ["customer_id"],
      foreign_keys: [{ field: "customer_id", references_table: "customers", references_field: "id", on_delete: "set_null" }],
    });
    const next = setFieldRequired(t, "customer_id", true);
    expect(next.foreign_keys[0]?.on_delete).toBe("restrict");
    expect(next.field_specs[0]?.nullable).toBe(false);
  });
});

describe("rename propagation", () => {
  const customers = table({ name: "customers", key_fields: ["email"] });
  const orders = table({
    name: "orders",
    key_fields: ["customer_id", "price", "status"],
    field_specs: [{ name: "price", type: "decimal", nullable: false, default: null, unique: false }],
    foreign_keys: [{ field: "customer_id", references_table: "customers", references_field: "id", on_delete: "cascade" }],
    checks: [{ name: "non_negative", expression: "price >= 0 AND status <> 'price' AND LENGTH(status) > 0" }],
    indexes: [{ fields: ["price", "created_at"], unique: false }],
    seed_rows: [{ price: "9.99", status: "paid" }],
  });

  it("renaming a field updates its spec, index entries, seed keys and checks", () => {
    const [, next] = unwrap(renameField([customers, orders], 1, 1, "unit_price"));
    expect(next!.key_fields).toEqual(["customer_id", "unit_price", "status"]);
    expect(next!.field_specs[0]?.name).toBe("unit_price");
    expect(next!.indexes[0]?.fields).toEqual(["unit_price", "created_at"]);
    expect(next!.seed_rows[0]).toEqual({ unit_price: "9.99", status: "paid" });
    // Only the bare identifier changes — never the quoted text.
    expect(next!.checks[0]?.expression).toBe(
      "unit_price >= 0 AND status <> 'price' AND LENGTH(status) > 0"
    );
  });

  it("renaming a linked field moves its foreign key with it", () => {
    const [, next] = unwrap(renameField([customers, orders], 1, 0, "buyer_id"));
    expect(next!.foreign_keys[0]?.field).toBe("buyer_id");
  });

  it("renaming a unique target field repoints foreign keys that use it", () => {
    const tickets = table({
      name: "tickets",
      key_fields: ["customer_email"],
      foreign_keys: [
        { field: "customer_email", references_table: "customers", references_field: "email", on_delete: "cascade" },
      ],
    });
    const [, , nextTickets] = unwrap(renameField([customers, orders, tickets], 0, 0, "contact_email"));
    expect(nextTickets!.foreign_keys[0]?.references_field).toBe("contact_email");
  });

  it("refuses a rename that would duplicate another field or blank it", () => {
    expect(renameField([customers, orders], 1, 1, "Status").ok).toBe(false);
    expect(renameField([customers, orders], 1, 1, "   ").ok).toBe(false);
  });

  it("renaming a table updates foreign keys that reference it", () => {
    const [renamed, nextOrders] = unwrap(renameTable([customers, orders], 0, "clients"));
    expect(renamed!.name).toBe("clients");
    expect(nextOrders!.foreign_keys[0]?.references_table).toBe("clients");
  });

  it("refuses a table rename that lands on another table's database name", () => {
    // "order" and "orders" would both be stored in the "orders" table.
    expect(renameTable([customers, orders], 0, "order").ok).toBe(false);
  });

  it("removing a table unlinks the fields that pointed at it", () => {
    const [onlyOrders] = removeTable([customers, orders], 0);
    expect(onlyOrders!.foreign_keys).toEqual([]);
    expect(onlyOrders!.key_fields).toContain("customer_id");
  });
});

describe("check expression renames", () => {
  it("leaves keywords, functions and quoted text alone", () => {
    expect(renameInExpression("status IN ('status', 'x') OR NOT status", "status", "state")).toBe(
      "state IN ('status', 'x') OR NOT state"
    );
    expect(renameInExpression("length(length) > 0", "length", "size")).toBe("length(size) > 0");
    expect(renameInExpression("note <> 'it''s status'", "status", "state")).toBe("note <> 'it''s status'");
  });

  it("matches identifiers by slug, as the backend binds them", () => {
    expect(renameInExpression("End_Date >= start_date", "end date", "finish date")).toBe(
      "finish_date >= start_date"
    );
  });
});

describe("removing a field", () => {
  it("drops its spec, link, index entries and seed values — but keeps checks", () => {
    const t = table({
      name: "orders",
      key_fields: ["customer_id", "price"],
      field_specs: [{ name: "price", type: "decimal", nullable: true, default: null, unique: true }],
      foreign_keys: [{ field: "customer_id", references_table: "customers", references_field: "id", on_delete: "cascade" }],
      checks: [{ name: "p", expression: "price >= 0" }],
      indexes: [
        { fields: ["price"], unique: false },
        { fields: ["price", "id"], unique: false },
        { fields: [], unique: false },
      ],
      seed_rows: [{ price: "1.00" }],
    });
    const next = removeField(t, 1);
    expect(next.key_fields).toEqual(["customer_id"]);
    expect(next.field_specs).toEqual([]);
    expect(next.foreign_keys).toHaveLength(1);
    // An index emptied by the removal goes; one the user hasn't filled in yet stays.
    expect(next.indexes).toEqual([
      { fields: ["id"], unique: false },
      { fields: [], unique: false },
    ]);
    expect(next.seed_rows).toEqual([{}]);
    expect(next.checks).toHaveLength(1);
  });
});

describe("links", () => {
  it("linking to an id clears a conflicting declared type and seed values", () => {
    let t = table({ name: "orders", key_fields: ["customer_id"], seed_rows: [{ customer_id: "3" }] });
    t = upsertFieldSpec(t, "customer_id", { type: "string" });
    const next = setFieldLink(t, "customer_id", { table: "customers" });
    expect(next.foreign_keys).toEqual([
      { field: "customer_id", references_table: "customers", references_field: "id", on_delete: "cascade" },
    ]);
    expect(next.field_specs).toEqual([]);
    expect(next.seed_rows).toEqual([{}]);
    expect(seedColumns(next)).toEqual([]);
    expect(autoFieldType([next], 0, "customer_id")).toBe("integer");
  });

  it("unlinking removes the foreign key", () => {
    const t = setFieldLink(table({ key_fields: ["a_id"] }), "a_id", { table: "a" });
    expect(setFieldLink(t, "a_id", null).foreign_keys).toEqual([]);
  });
});

describe("indexes", () => {
  it("offers id first and the timestamps last, and keeps pick order", () => {
    const t = table({ key_fields: ["id", "title", "status"], indexes: [{ fields: [], unique: false }] });
    expect(indexFieldChoices(t)).toEqual(["id", "title", "status", "created_at", "updated_at"]);
    let next = toggleIndexField(t, 0, "status");
    next = toggleIndexField(next, 0, "title");
    expect(next.indexes[0]?.fields).toEqual(["status", "title"]);
    expect(toggleIndexField(next, 0, "status").indexes[0]?.fields).toEqual(["title"]);
  });
});

describe("draft <-> payload", () => {
  it("drops blank seed cells and fully blank rows, and maps issue positions back", () => {
    let t = table({ name: "tags", key_fields: ["label", "weight"], seed_rows: [{}, {}, {}] });
    t = setSeedCell(t, 1, "label", "red");
    t = setSeedCell(t, 1, "weight", "  ");
    t = setSeedCell(t, 2, "label", "blue");
    const { tables, seedIndexMaps } = draftToPayload([t]);
    expect(tables[0]?.seed_rows).toEqual([{ label: "red" }, { label: "blue" }]);
    expect(seedIndexMaps[0]).toEqual([1, 2]);

    // The backend's "Seed row 2" (index 1) is the editor's third row.
    const loc = locateIssue(t, { table: "tags", kind: "seed_row", index: 1, message: "" }, seedIndexMaps[0]);
    expect(loc).toEqual({ area: "seed", index: 2 });
  });

  it("opens a saved table with text inputs and without no-op specs", () => {
    const draft = tableToDraft(
      {
        name: "settings",
        purpose: "",
        key_fields: ["theme", "limits", "is_on"],
        field_specs: [
          { name: "theme", type: null, nullable: true, default: null, unique: false },
          { name: "limits", type: "json", nullable: true, default: { max: 3 }, unique: false },
          { name: "is_on", type: "boolean", nullable: true, default: true, unique: false },
        ],
        seed_rows: [{ limits: "plain", is_on: false }],
      },
      {
        name: "settings",
        sql_name: "settings",
        columns: [
          { name: "theme", column: "theme", type: "string", declared: false, nullable: true, unique: false, default: null, fk: null },
          { name: "limits", column: "limits", type: "json", declared: true, nullable: true, unique: false, default: null, fk: null },
          { name: "is_on", column: "is_on", type: "boolean", declared: true, nullable: true, unique: false, default: true, fk: null },
        ],
        checks: [],
        indexes: [],
        seed_row_count: 1,
      }
    );
    expect(draft.field_specs.map((s) => s.name)).toEqual(["limits", "is_on"]);
    expect(draft.field_specs[0]?.default).toBe('{"max":3}');
    expect(draft.field_specs[1]?.default).toBe(true);
    // A stored JSON *string* goes back quoted so the backend's json.loads keeps it a string.
    expect(draft.seed_rows[0]).toEqual({ limits: '"plain"', is_on: "false" });
    expect(draft.foreign_keys).toEqual([]);
  });

  it("pins field_spec and foreign_key issues to the field row they belong to", () => {
    const t = table({
      name: "orders",
      key_fields: ["customer_id", "price"],
      field_specs: [{ name: "price", type: "decimal", nullable: true, default: "abc", unique: false }],
      foreign_keys: [{ field: "customer_id", references_table: "nope", references_field: "id", on_delete: "cascade" }],
    });
    expect(locateIssue(t, { table: "orders", kind: "field_spec", index: 0, message: "" })).toEqual({ area: "field", field: 1 });
    expect(locateIssue(t, { table: "orders", kind: "foreign_key", index: 0, message: "" })).toEqual({ area: "field", field: 0 });
    expect(locateIssue(t, { table: "orders", kind: "check", index: 4, message: "" })).toEqual({ area: "table" });
  });

  it("refuses to add a field whose name collides by slug", () => {
    const t = table({ key_fields: ["Unit Price"] });
    expect(addField(t, "unit_price").ok).toBe(false);
    expect(unwrap(addField(t, " sku ")).key_fields).toEqual(["Unit Price", "sku"]);
  });
});
