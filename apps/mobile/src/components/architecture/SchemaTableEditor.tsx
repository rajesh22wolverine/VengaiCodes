// ─── Typed editor for one database table (touch) ───
//
// One card per table: name + purpose, one expandable row per field (type
// chips / Required / Unique / default / "links to" + on-delete), then
// check constraints, indexes and seed rows. The desktop editor lays
// fields out as a wide grid; a phone can't, so each field collapses to a
// one-line summary (its type and key badges) and opens into the full set
// of controls when tapped.
//
// Every edit goes through a pure helper in src/lib/schemaDraft.ts — the
// same file, line for line, the desktop editor uses — so cross-references
// stay consistent the same way in both apps (renaming a field renames it
// in its spec, foreign key, indexes, seed rows and check expressions) and
// field specs are only emitted when a field actually declares something.
//
// Names (table and field) are committed when editing ends, not per
// keystroke — see CommitTextInput.tsx for why, and for how a rename still
// in progress is flushed before a save.
//
// Validation is the backend's job (POST /architecture/{id}/validate, run
// by the screen); this card only places the returned issues next to the
// row they're about. A problem is never hidden: a field row shows its
// messages even when collapsed, and a sub-section holding one stays open.

import { useState } from "react";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { ChevronDown, ChevronRight, KeyRound, Link2, ListChecks, Rows3, ShieldCheck, Trash2 } from "lucide-react-native";

import { useTheme } from "@/theme/useTheme";
import { DraftTable, FieldType, ResolvedTable, SchemaIssue } from "@/lib/schemaTypes";
import {
  addCheck,
  addField,
  addIndex,
  addSeedRow,
  autoFieldType,
  findFk,
  findSpec,
  indexFieldChoices,
  isImplicitField,
  removeCheck,
  removeField,
  removeIndex,
  removeSeedRow,
  sameField,
  seedCell,
  seedColumns,
  setFieldLink,
  setFieldOnDelete,
  setFieldRequired,
  setSeedCell,
  toggleIndexField,
  updateCheck,
  updateIndex,
  upsertFieldSpec,
  valueToText,
} from "@/lib/schemaDraft";
import {
  BooleanDefaultChoice,
  booleanDefaultChoice,
  booleanDefaultValue,
  countPinned,
  defaultHint,
  defaultPlaceholder,
  linkChoices,
  onDeleteChoices,
  pinIssues,
  seedRowLabels,
  typeChoices,
} from "@/lib/schemaEditorView";
import CommitTextInput from "./CommitTextInput";
import {
  ACCENT_COLOR,
  AddButton,
  Chip,
  ChipScroller,
  FieldLabel,
  INFO_COLOR,
  InlineIssues,
  RemoveButton,
  SubSection,
  SwitchRow,
  WARNING_COLOR,
  controlStyles,
  monoFont,
} from "./controls";
import { Badge, TypeBadge } from "./SchemaTableView";

const CHECK_EXAMPLES = ["price >= 0", "status IN ('draft','paid')", "LENGTH(name) > 0", "end_date >= start_date"];

const BOOLEAN_DEFAULTS: { choice: BooleanDefaultChoice; label: string }[] = [
  { choice: "none", label: "No default" },
  { choice: "true", label: "true" },
  { choice: "false", label: "false" },
];

// Identifiers and expressions: never auto-capitalized or "corrected".
const CODE_INPUT = { autoCapitalize: "none", autoCorrect: false, spellCheck: false } as const;

type Update = (fn: (table: DraftTable) => DraftTable) => void;

export default function SchemaTableEditor({
  tables,
  tableIndex,
  resolved,
  issues,
  seedIndexMap,
  onUpdate,
  onRenameTable,
  onRenameField,
  onRemove,
  onError,
}: {
  tables: DraftTable[];
  tableIndex: number;
  /** This table as the live validation resolved it (authoritative types). */
  resolved?: ResolvedTable;
  /** Live-validation issues for this table. */
  issues: SchemaIssue[];
  seedIndexMap?: number[];
  onUpdate: Update;
  /** `expected` is the name the input was showing: a commit that arrives
   *  after the table changed under it is refused rather than misapplied. */
  onRenameTable: (expected: string, name: string) => boolean;
  onRenameField: (fieldIndex: number, expected: string, name: string) => boolean;
  onRemove: () => void;
  onError: (message: string) => void;
}) {
  const { colors } = useTheme();
  const table = tables[tableIndex]!;
  // Which field rows are open, by key_fields position.
  const [expanded, setExpanded] = useState<Set<number>>(() => new Set());

  const pinned = pinIssues(table, issues, seedIndexMap);
  const seedCols = seedColumns(table);
  const seedLabels = seedRowLabels(table.seed_rows);
  const indexChoices = indexFieldChoices(table);
  const inputColors = { color: colors.textPrimary, borderColor: colors.border, backgroundColor: colors.surface };

  const toggleField = (fi: number) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(fi)) next.delete(fi);
      else next.add(fi);
      return next;
    });

  const removeFieldAt = (fi: number) => {
    onUpdate((t) => removeField(t, fi));
    // Rows below move up one, and take their open/closed state with them.
    setExpanded((prev) => new Set([...prev].filter((i) => i !== fi).map((i) => (i > fi ? i - 1 : i))));
  };

  const commitNewField = (text: string): boolean => {
    if (!text.trim()) return true;
    const check = addField(table, text);
    if (!check.ok) {
      onError(check.error);
      return false;
    }
    onUpdate((t) => {
      const r = addField(t, text);
      return r.ok ? r.value : t;
    });
    // Open the new field straight away — picking its type is the next step.
    const newIndex = table.key_fields.length;
    setExpanded((prev) => new Set(prev).add(newIndex));
    return true;
  };

  return (
    <View
      style={[
        styles.card,
        { backgroundColor: colors.background, borderColor: issues.length > 0 ? WARNING_COLOR : colors.border },
      ]}
    >
      {/* Name + purpose */}
      <View style={styles.row}>
        <CommitTextInput
          value={table.name}
          onCommit={(name) => onRenameTable(table.name, name)}
          placeholder="table_name"
          placeholderTextColor={colors.textTertiary}
          accessibilityLabel="Table name"
          style={[controlStyles.input, monoFont, inputColors, styles.tableNameInput]}
        />
        <RemoveButton onPress={onRemove} label="Remove table" />
      </View>
      {resolved && resolved.sql_name !== table.name.trim() && (
        <Text style={[styles.subtle, { color: colors.textTertiary }]}>
          Stored in the database as <Text style={monoFont}>{resolved.sql_name}</Text>
        </Text>
      )}
      <TextInput
        value={table.purpose}
        onChangeText={(v) => onUpdate((t) => ({ ...t, purpose: v }))}
        placeholder="What this table is for"
        placeholderTextColor={colors.textTertiary}
        style={[controlStyles.input, inputColors, { color: colors.textSecondary, marginTop: 8 }]}
      />
      <InlineIssues messages={pinned.table} />

      {/* Fields */}
      <FieldLabel>Fields ({table.key_fields.length})</FieldLabel>
      <View style={[styles.idRow, { borderColor: colors.border }]}>
        <KeyRound size={12} color={WARNING_COLOR} />
        <Text style={[monoFont, { color: colors.textSecondary, fontSize: 12 }]}>id</Text>
        <Text style={[styles.subtle, { color: colors.textTertiary, flex: 1, marginTop: 0 }]}>
          integer primary key, plus created_at / updated_at timestamps — all created automatically
        </Text>
      </View>

      {table.key_fields.map((field, fi) => (
        <FieldRow
          // Keyed by name as well as position: a row must never be
          // re-pointed at a different field while its name is being edited.
          key={`${fi}:${field}`}
          tables={tables}
          tableIndex={tableIndex}
          field={field}
          fieldIndex={fi}
          resolved={resolved}
          messages={pinned.fields.get(fi) ?? []}
          expanded={expanded.has(fi)}
          onToggle={() => toggleField(fi)}
          onUpdate={onUpdate}
          onRename={(name) => onRenameField(fi, field, name)}
          onRemove={() => removeFieldAt(fi)}
        />
      ))}

      <CommitTextInput
        value=""
        clearOnCommit
        onCommit={commitNewField}
        blurOnSubmit={false}
        returnKeyType="done"
        placeholder="+ add field"
        placeholderTextColor={colors.textTertiary}
        accessibilityLabel="New field name"
        style={[controlStyles.input, monoFont, styles.addFieldInput, { color: colors.textSecondary, borderColor: colors.border }]}
      />

      {/* Checks */}
      <SubSection
        icon={ShieldCheck}
        title="Checks"
        count={table.checks.length}
        issueCount={countPinned(pinned.checks)}
        defaultOpen={table.checks.length > 0}
      >
        <Text style={[controlStyles.help, { color: colors.textTertiary }]}>
          A rule every row must pass, enforced by the database. Compare fields and values with = &lt;&gt; &lt;
          &lt;= &gt; &gt;=, IS [NOT] NULL, [NOT] IN (…), [NOT] BETWEEN … AND …, [NOT] LIKE '…' or LENGTH(field),
          joined with AND / OR / NOT. Text goes in 'single quotes'. For example:{" "}
          <Text style={[monoFont, { color: colors.textSecondary }]}>{CHECK_EXAMPLES.join("  ·  ")}</Text>
        </Text>
        {table.checks.map((chk, ci) => {
          const messages = pinned.checks.get(ci) ?? [];
          return (
            <View
              key={ci}
              style={[styles.itemCard, { borderColor: messages.length > 0 ? colors.error : colors.border }]}
            >
              <View style={styles.row}>
                <TextInput
                  {...CODE_INPUT}
                  value={chk.name}
                  onChangeText={(v) => onUpdate((t) => updateCheck(t, ci, { name: v }))}
                  placeholder="rule_name"
                  placeholderTextColor={colors.textTertiary}
                  accessibilityLabel="Check name"
                  style={[controlStyles.input, monoFont, inputColors, { flex: 1 }]}
                />
                <RemoveButton onPress={() => onUpdate((t) => removeCheck(t, ci))} label="Remove check" />
              </View>
              <TextInput
                {...CODE_INPUT}
                value={chk.expression}
                onChangeText={(v) => onUpdate((t) => updateCheck(t, ci, { expression: v }))}
                placeholder="price >= 0"
                placeholderTextColor={colors.textTertiary}
                accessibilityLabel="Check expression"
                multiline
                style={[controlStyles.input, monoFont, inputColors, { marginTop: 6 }]}
              />
              <InlineIssues messages={messages} />
            </View>
          );
        })}
        <AddButton label="Add check" onPress={() => onUpdate(addCheck)} />
      </SubSection>

      {/* Indexes */}
      <SubSection
        icon={ListChecks}
        title="Indexes"
        count={table.indexes.length}
        issueCount={countPinned(pinned.indexes)}
        defaultOpen={table.indexes.length > 0}
      >
        <Text style={[controlStyles.help, { color: colors.textTertiary }]}>
          Speeds up searching, filtering or sorting on the chosen fields. Tap fields in order — a combined
          index uses them in the order you pick. Unique also stops two rows sharing the same combination.
        </Text>
        {table.indexes.map((ix, ii) => {
          const messages = pinned.indexes.get(ii) ?? [];
          const stale = ix.fields.filter((f) => !indexChoices.some((c) => sameField(c, f)));
          return (
            <View
              key={ii}
              style={[styles.itemCard, { borderColor: messages.length > 0 ? colors.error : colors.border }]}
            >
              <View style={styles.row}>
                <Text style={[styles.itemTitle, { color: colors.textSecondary }]}>Index {ii + 1}</Text>
                <RemoveButton onPress={() => onUpdate((t) => removeIndex(t, ii))} label="Remove index" />
              </View>
              <View style={styles.chipWrap}>
                {indexChoices.map((choice) => {
                  const pos = ix.fields.findIndex((f) => sameField(f, choice));
                  return (
                    <Chip
                      key={choice}
                      label={choice}
                      mono
                      selected={pos >= 0}
                      badge={pos >= 0 ? String(pos + 1) : undefined}
                      onPress={() => onUpdate((t) => toggleIndexField(t, ii, choice))}
                    />
                  );
                })}
                {/* Fields the index still names but the table no longer has */}
                {stale.map((f) => (
                  <Chip
                    key={`stale-${f}`}
                    label={f}
                    mono
                    strike
                    selected
                    tone={colors.error}
                    onPress={() => onUpdate((t) => toggleIndexField(t, ii, f))}
                  />
                ))}
              </View>
              {stale.length > 0 && (
                <Text style={[styles.subtle, { color: colors.textTertiary }]}>
                  Crossed-out fields aren't in this table any more — tap to take them out.
                </Text>
              )}
              <SwitchRow
                label="Unique"
                hint="No two rows may share this combination"
                value={!!ix.unique}
                onValueChange={(v) => onUpdate((t) => updateIndex(t, ii, { unique: v }))}
              />
              <InlineIssues messages={messages} />
            </View>
          );
        })}
        <AddButton label="Add index" onPress={() => onUpdate(addIndex)} />
      </SubSection>

      {/* Seed rows */}
      <SubSection
        icon={Rows3}
        title="Seed rows"
        count={seedLabels.filter((l) => l !== "—").length}
        issueCount={countPinned(pinned.seeds)}
        defaultOpen={false}
      >
        <Text style={[controlStyles.help, { color: colors.textTertiary }]}>
          Starter rows the first database migration inserts (lookup values, categories, a demo record…).
          Blank cells are left out; a completely blank row is ignored. Links to another table's id can't be
          seeded — the database assigns ids.
        </Text>
        {seedCols.length === 0 ? (
          <Text style={{ color: colors.textTertiary, fontSize: 12 }}>
            This table has no fields that can take seed values.
          </Text>
        ) : (
          table.seed_rows.map((row, ri) => {
            const messages = pinned.seeds.get(ri) ?? [];
            const blank = seedLabels[ri] === "—";
            return (
              <View
                key={ri}
                style={[styles.itemCard, { borderColor: messages.length > 0 ? colors.error : colors.border }]}
              >
                <View style={styles.row}>
                  <Text style={[styles.itemTitle, monoFont, { color: blank ? colors.textTertiary : colors.textSecondary }]}>
                    {blank ? "Blank row — ignored" : `Row ${seedLabels[ri]}`}
                  </Text>
                  <RemoveButton onPress={() => onUpdate((t) => removeSeedRow(t, ri))} label="Remove row" />
                </View>
                {seedCols.map((col) => {
                  const spec = findSpec(table, col);
                  const type = spec?.type || autoFieldType(tables, tableIndex, col, resolved);
                  const mustFill = spec?.nullable === false && (spec.default === null || spec.default === undefined);
                  return (
                    <View key={col} style={{ marginTop: 6 }}>
                      <Text style={{ fontSize: 11, color: colors.textSecondary }}>
                        <Text style={[monoFont, { fontWeight: "700" }]}>{col}</Text>
                        {mustFill && <Text style={{ color: colors.error }}> *</Text>}
                        <Text style={{ color: colors.textTertiary }}>  {type}</Text>
                      </Text>
                      <TextInput
                        {...CODE_INPUT}
                        value={seedCell(row, col)}
                        onChangeText={(v) => onUpdate((t) => setSeedCell(t, ri, col, v))}
                        accessibilityLabel={`Seed value for ${col}`}
                        style={[controlStyles.input, monoFont, inputColors, { marginTop: 3 }]}
                      />
                    </View>
                  );
                })}
                <InlineIssues messages={messages} />
              </View>
            );
          })
        )}
        <AddButton label="Add row" onPress={() => onUpdate(addSeedRow)} disabled={seedCols.length === 0} />
      </SubSection>
    </View>
  );
}

/** One field: a one-line summary that opens into its controls. */
function FieldRow({
  tables,
  tableIndex,
  field,
  fieldIndex,
  resolved,
  messages,
  expanded,
  onToggle,
  onUpdate,
  onRename,
  onRemove,
}: {
  tables: DraftTable[];
  tableIndex: number;
  field: string;
  fieldIndex: number;
  resolved?: ResolvedTable;
  messages: string[];
  expanded: boolean;
  onToggle: () => void;
  onUpdate: Update;
  onRename: (name: string) => boolean;
  onRemove: () => void;
}) {
  const { colors } = useTheme();
  const table = tables[tableIndex]!;
  const automatic = isImplicitField(field);
  const unnamed = !field.trim();

  const spec = findSpec(table, field);
  const fk = findFk(table, field);
  const required = spec?.nullable === false;
  const declaredType = spec?.type ?? null;
  const auto = automatic || unnamed ? "" : autoFieldType(tables, tableIndex, field, resolved);
  const effectiveType = declaredType || auto;
  const defaultText = valueToText(spec?.default);
  const hint = defaultHint(effectiveType);
  const Chevron = expanded ? ChevronDown : ChevronRight;
  const inputColors = { color: colors.textPrimary, borderColor: colors.border, backgroundColor: colors.surface };

  return (
    <View
      style={[
        styles.fieldRow,
        { borderColor: messages.length > 0 ? colors.error : colors.border, backgroundColor: colors.surface },
      ]}
    >
      <Pressable
        onPress={onToggle}
        style={styles.fieldHeader}
        accessibilityRole="button"
        accessibilityState={{ expanded }}
        accessibilityLabel={`Field ${field || "without a name"}`}
      >
        <Chevron size={14} color={colors.textTertiary} />
        <Text
          style={[
            monoFont,
            styles.fieldName,
            { color: unnamed ? colors.textTertiary : colors.textPrimary },
            unnamed && { fontStyle: "italic" },
          ]}
          numberOfLines={1}
        >
          {unnamed ? "(no name)" : field}
        </Text>
        {automatic ? (
          <Text style={{ color: colors.textTertiary, fontSize: 10 }}>automatic</Text>
        ) : unnamed ? null : (
          <>
            <TypeBadge type={effectiveType} declared={!!declaredType} />
            {fk && <Badge icon={Link2} color={INFO_COLOR} label={`→ ${fk.references_table}`} />}
            {spec?.unique && <Badge label="UQ" color={ACCENT_COLOR} />}
            {required && (
              <View style={[controlStyles.badge, { borderWidth: 1, borderColor: colors.border }]}>
                <Text style={{ color: colors.textSecondary, fontSize: 10, fontWeight: "600" }}>required</Text>
              </View>
            )}
            {defaultText !== "" && (
              <Text style={[monoFont, { color: colors.textTertiary, fontSize: 10, flexShrink: 1 }]} numberOfLines={1}>
                = {defaultText}
              </Text>
            )}
          </>
        )}
      </Pressable>
      <InlineIssues messages={messages} />

      {expanded && (
        <View style={styles.fieldBody}>
          <FieldLabel>Name</FieldLabel>
          <CommitTextInput
            value={field}
            onCommit={onRename}
            placeholder="field_name"
            placeholderTextColor={colors.textTertiary}
            accessibilityLabel="Field name"
            style={[controlStyles.input, monoFont, inputColors]}
          />

          {automatic || unnamed ? (
            <Text style={[styles.subtle, { color: colors.textTertiary }]}>
              {automatic ? "Created automatically — nothing to set here." : "Give this field a name."}
            </Text>
          ) : (
            <>
              <FieldLabel>Type</FieldLabel>
              <ChipScroller>
                {typeChoices(declaredType, auto).map((choice) => (
                  <Chip
                    key={choice.value ?? "__auto__"}
                    label={choice.label}
                    mono={choice.value !== null}
                    selected={(choice.value ?? null) === declaredType}
                    tone={choice.invalid ? colors.error : undefined}
                    onPress={() =>
                      onUpdate((t) => upsertFieldSpec(t, field, { type: choice.value as FieldType | null }))
                    }
                  />
                ))}
              </ChipScroller>

              <SwitchRow
                label="Required"
                hint="Every row must have a value"
                value={required}
                onValueChange={(v) => onUpdate((t) => setFieldRequired(t, field, v))}
              />
              <SwitchRow
                label="Unique"
                hint="No two rows may share a value"
                value={!!spec?.unique}
                onValueChange={(v) => onUpdate((t) => upsertFieldSpec(t, field, { unique: v }))}
              />

              <FieldLabel>Default</FieldLabel>
              {effectiveType === "boolean" ? (
                <ChipScroller>
                  {BOOLEAN_DEFAULTS.map(({ choice, label }) => (
                    <Chip
                      key={choice}
                      label={label}
                      mono={choice !== "none"}
                      selected={booleanDefaultChoice(spec?.default) === choice}
                      onPress={() => onUpdate((t) => upsertFieldSpec(t, field, { default: booleanDefaultValue(choice) }))}
                    />
                  ))}
                </ChipScroller>
              ) : (
                <>
                  <TextInput
                    {...CODE_INPUT}
                    value={defaultText}
                    onChangeText={(v) => onUpdate((t) => upsertFieldSpec(t, field, { default: v }))}
                    placeholder={defaultPlaceholder(effectiveType)}
                    placeholderTextColor={colors.textTertiary}
                    accessibilityLabel={`Default for ${field}`}
                    multiline={effectiveType === "json" || effectiveType === "text"}
                    style={[controlStyles.input, monoFont, inputColors]}
                  />
                  {hint && <Text style={[styles.subtle, { color: colors.textTertiary }]}>{hint}</Text>}
                </>
              )}

              <FieldLabel>Links to</FieldLabel>
              <ChipScroller>
                {linkChoices(tables, tableIndex, fk).map((choice, k) => (
                  <Chip
                    key={`${choice.value ?? "__none__"}-${k}`}
                    label={choice.label}
                    mono={choice.value !== null}
                    selected={choice.selected}
                    tone={choice.missing ? colors.error : undefined}
                    onPress={() =>
                      onUpdate((t) => setFieldLink(t, field, choice.value ? { table: choice.value } : null))
                    }
                  />
                ))}
              </ChipScroller>

              {fk && (
                <>
                  <FieldLabel>When the linked row is deleted</FieldLabel>
                  <ChipScroller>
                    {onDeleteChoices(fk, required).map((choice) => (
                      <Chip
                        key={choice.rule}
                        label={choice.label}
                        selected={choice.selected}
                        disabled={choice.disabled}
                        onPress={() => onUpdate((t) => setFieldOnDelete(t, field, choice.rule))}
                      />
                    ))}
                  </ChipScroller>
                  {required && (
                    <Text style={[styles.subtle, { color: colors.textTertiary }]}>
                      "Set null" needs a field that isn't Required.
                    </Text>
                  )}
                </>
              )}
            </>
          )}

          <Pressable
            onPress={onRemove}
            style={styles.removeFieldButton}
            accessibilityRole="button"
            accessibilityLabel={`Remove field ${field}`}
            hitSlop={6}
          >
            <Trash2 size={13} color={colors.error} />
            <Text style={{ color: colors.error, fontSize: 12, fontWeight: "600" }}>Remove field</Text>
          </Pressable>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { borderWidth: 1, borderRadius: 12, padding: 12, marginBottom: 12 },
  row: { flexDirection: "row", alignItems: "center", gap: 8 },
  tableNameInput: { flex: 1, fontSize: 13, fontWeight: "700" },
  subtle: { fontSize: 11, lineHeight: 15, marginTop: 4 },
  idRow: { flexDirection: "row", alignItems: "center", gap: 6, paddingVertical: 6 },
  fieldRow: { borderWidth: 1, borderRadius: 10, paddingHorizontal: 10, paddingVertical: 8, marginTop: 6 },
  fieldHeader: { flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 6, minHeight: 28 },
  fieldName: { fontSize: 12, fontWeight: "700", flexShrink: 1 },
  fieldBody: { marginTop: 4 },
  removeFieldButton: { flexDirection: "row", alignItems: "center", gap: 6, alignSelf: "flex-start", marginTop: 12, paddingVertical: 4 },
  addFieldInput: { borderStyle: "dashed", marginTop: 8 },
  itemCard: { borderWidth: 1, borderRadius: 10, padding: 10, marginBottom: 8 },
  itemTitle: { flex: 1, fontSize: 12, fontWeight: "700" },
  chipWrap: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 8 },
});
