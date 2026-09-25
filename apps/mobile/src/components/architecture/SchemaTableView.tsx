// ─── Read-only view of one database table ───
//
// Shows what code generation will actually build for the table — the
// backend's resolved schema (GET /architecture → resolved_tables), not a
// re-derivation here — so a type, key or default shown on this card is
// exactly what the generated model and migration contain. A declared
// type gets a solid badge; a type still inferred from the field's name
// gets a muted dashed "auto" one, so it's obvious which parts were
// decided and which are a best guess worth checking.
//
// Falls back to the plain field-name pills this screen always showed
// when there's no resolved table (an older backend, or a table whose own
// name is invalid and so can't be resolved).

import { StyleSheet, Text, View } from "react-native";
import { AlertTriangle, Database, KeyRound, Link2, ListChecks, Rows3, ShieldCheck } from "lucide-react-native";

import { useTheme } from "@/theme/useTheme";
import { DatabaseTable, ON_DELETE_LABELS, OnDeleteRule, ResolvedColumn, ResolvedTable } from "@/lib/schemaTypes";
import { describeDefault, isImplicitField, sameField } from "@/lib/schemaDraft";
import { ACCENT_COLOR, INFO_COLOR, WARNING_COLOR, controlStyles, monoFont, tint } from "./controls";

export function TypeBadge({ type, declared }: { type: string; declared: boolean }) {
  const { colors } = useTheme();
  if (declared) {
    return (
      <View style={[controlStyles.badge, { backgroundColor: colors.primaryLight }]}>
        <Text style={[controlStyles.badgeText, { color: colors.primary }]}>{type}</Text>
      </View>
    );
  }
  return (
    <View
      style={[controlStyles.badge, { borderWidth: 1, borderStyle: "dashed", borderColor: colors.border }]}
      accessibilityLabel={`${type}, inferred from the field's name`}
    >
      <Text style={[controlStyles.badgeText, { color: colors.textTertiary }]}>
        {type} <Text style={{ fontWeight: "400" }}>auto</Text>
      </Text>
    </View>
  );
}

export function Badge({ label, color, icon: Icon }: { label: string; color: string; icon?: React.ElementType }) {
  return (
    <View style={[controlStyles.badge, styles.iconBadge, { backgroundColor: tint(color) }]}>
      {Icon ? <Icon size={10} color={color} /> : null}
      <Text style={[controlStyles.badgeText, { color }]}>{label}</Text>
    </View>
  );
}

function ColumnBadges({ col }: { col: ResolvedColumn }) {
  const { colors } = useTheme();
  const rule = ON_DELETE_LABELS[col.fk?.on_delete as OnDeleteRule] ?? col.fk?.on_delete;
  return (
    <>
      {col.fk && (
        <Badge
          icon={Link2}
          color={INFO_COLOR}
          label={`FK → ${col.fk.table}${col.fk.column !== "id" ? `.${col.fk.column}` : ""} · ${rule}`}
        />
      )}
      {col.unique && <Badge label="UQ" color={ACCENT_COLOR} />}
      {!col.nullable && (
        <View style={[controlStyles.badge, { borderWidth: 1, borderColor: colors.border }]}>
          <Text style={{ color: colors.textSecondary, fontSize: 10, fontWeight: "600" }}>required</Text>
        </View>
      )}
      {col.default !== null && col.default !== undefined && (
        <Text style={[monoFont, { color: colors.textTertiary, fontSize: 10 }]} numberOfLines={1}>
          = {describeDefault(col.default, col.type)}
        </Text>
      )}
    </>
  );
}

export default function SchemaTableView({
  table,
  resolved,
  issueCount,
}: {
  table: DatabaseTable;
  resolved?: ResolvedTable;
  issueCount: number;
}) {
  const { colors } = useTheme();
  const ownFields = table.key_fields.filter((f) => !isImplicitField(f));

  return (
    <View style={[styles.card, { backgroundColor: colors.background, borderColor: colors.border }]}>
      <View style={styles.headerRow}>
        <Database size={13} color={colors.primary} />
        <Text style={[monoFont, styles.tableName, { color: colors.textPrimary }]} numberOfLines={1}>
          {table.name}
        </Text>
        {resolved && resolved.sql_name !== table.name && (
          <Text style={[monoFont, { color: colors.textTertiary, fontSize: 10 }]} numberOfLines={1}>
            ({resolved.sql_name})
          </Text>
        )}
        {issueCount > 0 && (
          <View style={styles.issueCount} accessibilityLabel={`${issueCount} schema problems`}>
            <AlertTriangle size={12} color={WARNING_COLOR} />
            <Text style={{ color: WARNING_COLOR, fontSize: 11, fontWeight: "700" }}>{issueCount}</Text>
          </View>
        )}
      </View>
      {!!table.purpose && (
        <Text style={[styles.purpose, { color: colors.textSecondary }]}>{table.purpose}</Text>
      )}

      {resolved ? (
        <>
          <View style={styles.columnRow}>
            <Text style={[monoFont, styles.columnName, { color: colors.textPrimary }]}>id</Text>
            <TypeBadge type="integer" declared />
            <Badge icon={KeyRound} label="PK" color={WARNING_COLOR} />
          </View>
          {ownFields.map((field, j) => {
            const col = resolved.columns.find((c) => sameField(c.name, field));
            return (
              <View key={j} style={styles.columnRow}>
                <Text style={[monoFont, styles.columnName, { color: colors.textPrimary }]}>{field}</Text>
                {col ? (
                  <>
                    <TypeBadge type={col.type} declared={col.declared} />
                    <ColumnBadges col={col} />
                  </>
                ) : (
                  <Badge label="not generated" color={WARNING_COLOR} />
                )}
              </View>
            );
          })}
          <Text style={{ color: colors.textTertiary, fontSize: 10, marginTop: 4 }}>
            + created_at, updated_at (set automatically)
          </Text>

          {resolved.checks.length > 0 && (
            <View style={styles.block}>
              <View style={styles.blockTitleRow}>
                <ShieldCheck size={12} color={colors.textTertiary} />
                <Text style={[styles.blockTitle, { color: colors.textTertiary }]}>Checks</Text>
              </View>
              {resolved.checks.map((chk, k) => (
                <Text key={k} style={{ fontSize: 11, lineHeight: 16, color: colors.textSecondary }}>
                  <Text style={{ fontWeight: "600" }}>{chk.name}: </Text>
                  <Text selectable style={[monoFont, { color: colors.textPrimary }]}>
                    {chk.sql}
                  </Text>
                </Text>
              ))}
            </View>
          )}

          {resolved.indexes.length > 0 && (
            <View style={styles.block}>
              <View style={styles.blockTitleRow}>
                <ListChecks size={12} color={colors.textTertiary} />
                <Text style={[styles.blockTitle, { color: colors.textTertiary }]}>Indexes</Text>
              </View>
              <View style={styles.wrapRow}>
                {resolved.indexes.map((ix, k) => (
                  <View
                    key={k}
                    style={[styles.indexPill, { borderColor: colors.border, backgroundColor: colors.surface }]}
                    accessibilityLabel={ix.name}
                  >
                    <Text style={[monoFont, { color: colors.textSecondary, fontSize: 11 }]}>
                      ({ix.columns.join(", ")})
                    </Text>
                    {ix.unique && <Badge label="UNIQUE" color={ACCENT_COLOR} />}
                  </View>
                ))}
              </View>
            </View>
          )}

          {resolved.seed_row_count > 0 && (
            <View style={[styles.blockTitleRow, { marginTop: 10 }]}>
              <Rows3 size={12} color={colors.textTertiary} />
              <Text style={{ color: colors.textTertiary, fontSize: 11 }}>
                {resolved.seed_row_count} starter row{resolved.seed_row_count === 1 ? "" : "s"} (seed data)
              </Text>
            </View>
          )}
        </>
      ) : (
        <View style={styles.wrapRow}>
          {table.key_fields.map((field, j) => (
            <View key={j} style={[styles.fieldPill, { backgroundColor: colors.surface, borderColor: colors.border }]}>
              <Text style={[monoFont, { color: colors.textTertiary, fontSize: 11 }]}>{field}</Text>
            </View>
          ))}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { borderWidth: 1, borderRadius: 12, padding: 12, marginBottom: 10 },
  headerRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  tableName: { fontWeight: "700", flexShrink: 1 },
  issueCount: { flexDirection: "row", alignItems: "center", gap: 3, marginLeft: "auto" },
  purpose: { fontSize: 13, lineHeight: 19, marginTop: 6 },
  columnRow: { flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 6, marginTop: 6 },
  columnName: { fontSize: 12 },
  iconBadge: { flexDirection: "row", alignItems: "center", gap: 3 },
  block: { marginTop: 10 },
  blockTitleRow: { flexDirection: "row", alignItems: "center", gap: 4, marginBottom: 4 },
  blockTitle: { fontSize: 10, fontWeight: "700", textTransform: "uppercase", letterSpacing: 0.5 },
  wrapRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 8 },
  indexPill: { flexDirection: "row", alignItems: "center", gap: 4, borderWidth: 1, borderRadius: 8, paddingHorizontal: 8, paddingVertical: 4 },
  fieldPill: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 8, borderWidth: 1 },
});
