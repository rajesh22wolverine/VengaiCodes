import { describe, expect, it } from "vitest";
import {
  booleanDefaultChoice,
  booleanDefaultValue,
  countPinned,
  defaultHint,
  defaultPlaceholder,
  detailToText,
  linkChoices,
  onDeleteChoices,
  pinIssues,
  plural,
  schemaNotesTitle,
  seedRowLabels,
  typeChoices,
} from "./schemaEditorView";
import { emptyDraftTable, setFieldLink, setFieldRequired } from "./schemaDraft";
import { DraftTable, SchemaIssue } from "./schemaTypes";

function table(patch: Partial<DraftTable>): DraftTable {
  return { ...emptyDraftTable(), ...patch };
}

function issue(kind: string, index: number | null, message = kind): SchemaIssue {
  return { table: "orders", kind, index, message };
}

describe("detailToText", () => {
  it("keeps the schema editor's multi-line 400 detail intact", () => {
    const detail = "Fix these before saving:\n• orders: price must be a number\n• tags: duplicate field";
    expect(detailToText(detail)).toBe(detail);
  });

  it("joins a 422's list of messages, one per line", () => {
    expect(detailToText([{ msg: "field required" }, { msg: "bad type" }, "plain"])).toBe(
      "field required\nbad type\nplain"
    );
  });

  it("never loses an unexpected shape, and is empty for nothing", () => {
    expect(detailToText({ code: 1 })).toBe('{"code":1}');
    expect(detailToText(undefined)).toBe("");
    expect(detailToText(null)).toBe("");
  });
});

describe("pinIssues", () => {
  const orders = table({
    name: "orders",
    key_fields: ["customer_id", "price"],
    field_specs: [{ name: "price", type: "decimal", nullable: true, default: "abc", unique: false }],
    foreign_keys: [{ field: "customer_id", references_table: "nope", references_field: "id", on_delete: "cascade" }],
    checks: [{ name: "p", expression: "price >" }],
    indexes: [{ fields: [], unique: false }],
    seed_rows: [{}, { price: "x" }],
  });

  it("puts every issue on the row it is about", () => {
    const pinned = pinIssues(
      orders,
      [
        issue("field_spec", 0, "bad default"),
        issue("foreign_key", 0, "no such table"),
        issue("check", 0, "incomplete"),
        issue("index", 0, "no fields"),
        issue("seed_row", 0, "not a number"),
        issue("table", null, "whole table"),
      ],
      [1] // payload seed row 0 is draft row 1 (row 0 is blank)
    );
    expect(pinned.fields.get(1)).toEqual(["bad default"]);
    expect(pinned.fields.get(0)).toEqual(["no such table"]);
    expect(pinned.checks.get(0)).toEqual(["incomplete"]);
    expect(pinned.indexes.get(0)).toEqual(["no fields"]);
    expect(pinned.seeds.get(1)).toEqual(["not a number"]);
    expect(pinned.table).toEqual(["whole table"]);
  });

  it("falls back to table level when an issue points past the draft", () => {
    const pinned = pinIssues(orders, [issue("check", 7), issue("field", 9)]);
    expect(pinned.table).toEqual(["check", "field"]);
    expect(countPinned(pinned.checks)).toBe(0);
  });

  it("counts every message in a row map", () => {
    const pinned = pinIssues(orders, [issue("field", 0, "a"), issue("field", 0, "b"), issue("field", 1, "c")]);
    expect(countPinned(pinned.fields)).toBe(3);
  });
});

describe("type chips", () => {
  it("offers Auto with what it resolves to, then the nine types", () => {
    const choices = typeChoices(null, "float");
    expect(choices[0]).toEqual({ value: null, label: "Auto (float)" });
    expect(choices.slice(1).map((c) => c.value)).toEqual([
      "string", "text", "integer", "float", "decimal", "boolean", "date", "datetime", "json",
    ]);
  });

  it("keeps an unknown declared type visible so it can be fixed", () => {
    const choices = typeChoices("money", "string");
    expect(choices[choices.length - 1]).toEqual({ value: "money", label: "money (not a valid type)", invalid: true });
    expect(typeChoices("decimal", "string")).toHaveLength(10);
  });
});

describe("link chips", () => {
  const customers = table({ name: "customers", key_fields: ["email"] });
  const blank = table({ name: "  " });

  it("offers none plus every named table, marking this one", () => {
    const orders = table({ name: "orders", key_fields: ["customer_id"] });
    const choices = linkChoices([customers, orders, blank], 1, undefined);
    expect(choices.map((c) => c.label)).toEqual(["None", "customers", "orders (this table)"]);
    expect(choices[0]?.selected).toBe(true);
  });

  it("selects the linked table by slug/plural match and shows a non-id target", () => {
    const orders = table({
      name: "orders",
      key_fields: ["customer_email"],
      foreign_keys: [
        { field: "customer_email", references_table: "customer", references_field: "email", on_delete: "cascade" },
      ],
    });
    const choices = linkChoices([customers, orders], 1, orders.foreign_keys[0]);
    const selected = choices.filter((c) => c.selected);
    expect(selected).toEqual([{ value: "customers", label: "customers.email", selected: true }]);
  });

  it("keeps a link to a table that no longer exists visible as missing", () => {
    const orders = setFieldLink(table({ name: "orders", key_fields: ["vendor_id"] }), "vendor_id", { table: "vendors" });
    const choices = linkChoices([customers, orders], 1, orders.foreign_keys[0]);
    expect(choices[choices.length - 1]).toEqual({
      value: "vendors",
      label: "vendors (missing)",
      selected: true,
      missing: true,
    });
  });

  it("disables SET NULL on a required link and reflects the current rule", () => {
    let orders = setFieldLink(table({ name: "orders", key_fields: ["customer_id"] }), "customer_id", {
      table: "customers",
      onDelete: "set_null",
    });
    expect(onDeleteChoices(orders.foreign_keys[0], false).find((c) => c.selected)?.rule).toBe("set_null");
    orders = setFieldRequired(orders, "customer_id", true);
    const choices = onDeleteChoices(orders.foreign_keys[0], true);
    expect(choices.find((c) => c.rule === "set_null")?.disabled).toBe(true);
    expect(choices.find((c) => c.selected)?.rule).toBe("restrict");
    expect(choices.map((c) => c.label)).toEqual(["Cascade", "Set null", "Restrict"]);
  });
});

describe("defaults", () => {
  it("reads a boolean default from either a boolean or its text", () => {
    expect(booleanDefaultChoice(true)).toBe("true");
    expect(booleanDefaultChoice("false")).toBe("false");
    expect(booleanDefaultChoice(null)).toBe("none");
    expect(booleanDefaultChoice("maybe")).toBe("none");
    expect(booleanDefaultValue("true")).toBe(true);
    expect(booleanDefaultValue("false")).toBe(false);
    expect(booleanDefaultValue("none")).toBeNull();
  });

  it("gives type-aware placeholders and explains now/today", () => {
    expect(defaultPlaceholder("datetime")).toBe("now, or 2024-01-31T09:00");
    expect(defaultPlaceholder("string")).toBe("No default");
    expect(defaultHint("date")).toContain('"today"');
    expect(defaultHint("integer")).toBeNull();
  });
});

describe("seed row labels", () => {
  it("numbers only rows that will be sent, like the backend does", () => {
    expect(seedRowLabels([{ a: "1" }, {}, { a: "  " }, { a: "2" }])).toEqual(["#1", "—", "—", "#2"]);
  });
});

describe("banner titles", () => {
  it("distinguishes dropped suggestions from other fixes", () => {
    expect(schemaNotesTitle(["Dropped check x", "Dropped index y", "Renamed z"])).toBe(
      "Baby Tiger dropped 2 suggestions that didn't validate and made 1 other fix"
    );
    expect(schemaNotesTitle(["Renamed z"])).toBe("Baby Tiger adjusted 1 of its suggestion so they validate");
    expect(plural(1, "problem")).toBe("1 problem");
    expect(plural(3, "problem")).toBe("3 problems");
  });
});
