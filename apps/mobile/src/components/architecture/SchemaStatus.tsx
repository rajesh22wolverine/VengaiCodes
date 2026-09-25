// ─── Schema status banners for the Architecture screen ───
//
// Two kinds of news about the database schema, kept visually distinct
// (the same split as the desktop app):
//   - notes:  what the backend dropped from (or adjusted in) the AI's
//             proposal because it didn't validate — informational, the
//             saved schema is already consistent.
//   - issues: problems in the schema as it stands. These block the
//             "No AI" deterministic code generator (it refuses to build
//             from a schema it can't resolve), so they're a warning.
// Plus the one-line state of the editor's live check.

import { useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, CloudOff, Info, Pencil } from "lucide-react-native";

import { useTheme } from "@/theme/useTheme";
import { SchemaIssue } from "@/lib/schemaTypes";
import { groupIssuesByTable } from "@/lib/schemaDraft";
import { plural, schemaNotesTitle } from "@/lib/schemaEditorView";
import { INFO_COLOR, WARNING_COLOR, monoFont, tint } from "./controls";

export function SchemaNotesBanner({ notes }: { notes: string[] }) {
  const { colors } = useTheme();
  const [open, setOpen] = useState(false);
  if (notes.length === 0) return null;
  const Chevron = open ? ChevronDown : ChevronRight;

  return (
    <View style={[styles.banner, { borderColor: colors.border, backgroundColor: tint(INFO_COLOR) }]}>
      <Pressable onPress={() => setOpen((v) => !v)} style={styles.bannerHeader} accessibilityRole="button">
        <Info size={14} color={INFO_COLOR} style={{ marginTop: 1 }} />
        <Text style={[styles.bannerTitle, { color: colors.textPrimary, fontWeight: "600" }]}>
          {schemaNotesTitle(notes)}
        </Text>
        <Chevron size={14} color={colors.textTertiary} style={{ marginTop: 1 }} />
      </Pressable>
      {open && (
        <View style={styles.list}>
          {notes.map((note, i) => (
            <Text key={i} style={[styles.bullet, { color: colors.textSecondary }]}>
              • {note}
            </Text>
          ))}
        </View>
      )}
    </View>
  );
}

/** Every issue, grouped under the table it belongs to. */
export function SchemaIssuesPanel({
  issues,
  title,
  onEdit,
}: {
  issues: SchemaIssue[];
  title: string;
  onEdit?: () => void;
}) {
  const { colors } = useTheme();
  if (issues.length === 0) return null;
  const groups = groupIssuesByTable(issues);

  return (
    <View style={[styles.banner, { borderColor: WARNING_COLOR, backgroundColor: tint(WARNING_COLOR) }]}>
      <View style={styles.bannerHeader}>
        <AlertTriangle size={14} color={WARNING_COLOR} style={{ marginTop: 1 }} />
        <Text style={[styles.bannerTitle, { color: colors.textPrimary, fontWeight: "700" }]}>{title}</Text>
        {onEdit && (
          <Pressable onPress={onEdit} hitSlop={8} style={styles.fixButton} accessibilityRole="button">
            <Pencil size={12} color={colors.primary} />
            <Text style={{ color: colors.primary, fontSize: 12, fontWeight: "700" }}>Fix</Text>
          </Pressable>
        )}
      </View>
      <View style={styles.list}>
        {groups.map(([table, list]) => (
          <View key={table || "__general__"} style={{ marginBottom: 6 }}>
            <Text style={[monoFont, { color: colors.textPrimary, fontSize: 12, fontWeight: "700" }]}>
              {table || "General"}
            </Text>
            {list.map((issue, i) => (
              <Text key={i} selectable style={[styles.bullet, { color: colors.textSecondary }]}>
                • {issue.message}
              </Text>
            ))}
          </View>
        ))}
      </View>
    </View>
  );
}

export interface LiveCheckState {
  isValidating: boolean;
  /** The last request failed (offline, older backend…). */
  unavailable: boolean;
  /** Issue count of the last answer, or null before the first one. */
  issueCount: number | null;
}

/** "Checking…" / "Schema checks out." / "N problems — show". */
export function LiveValidationStatus({ state, onShowIssues }: { state: LiveCheckState; onShowIssues?: () => void }) {
  const { colors } = useTheme();
  const { isValidating, unavailable, issueCount } = state;

  if (isValidating || (issueCount === null && !unavailable)) {
    return (
      <View style={styles.statusRow}>
        <ActivityIndicator size="small" color={colors.textTertiary} />
        <Text style={[styles.statusText, { color: colors.textTertiary }]}>Checking the schema…</Text>
      </View>
    );
  }
  if (unavailable) {
    return (
      <View style={styles.statusRow}>
        <CloudOff size={13} color={colors.textTertiary} />
        <Text style={[styles.statusText, { color: colors.textTertiary }]}>
          Live checking is unavailable — Save will still check everything.
        </Text>
      </View>
    );
  }
  if (!issueCount) {
    return (
      <View style={styles.statusRow}>
        <CheckCircle2 size={13} color={colors.success} />
        <Text style={[styles.statusText, { color: colors.success }]}>Schema checks out.</Text>
      </View>
    );
  }
  return (
    <Pressable onPress={onShowIssues} disabled={!onShowIssues} style={styles.statusRow} hitSlop={6}>
      <AlertTriangle size={13} color={WARNING_COLOR} />
      <Text style={[styles.statusText, { color: WARNING_COLOR, fontWeight: "700" }]}>
        {plural(issueCount, "problem")}
        {onShowIssues ? " — show" : ""}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  banner: { borderWidth: 1, borderRadius: 12, paddingHorizontal: 12, paddingVertical: 10, marginBottom: 10 },
  bannerHeader: { flexDirection: "row", alignItems: "flex-start", gap: 8 },
  bannerTitle: { flex: 1, fontSize: 12, lineHeight: 17 },
  fixButton: { flexDirection: "row", alignItems: "center", gap: 4 },
  list: { marginTop: 8, marginLeft: 22 },
  bullet: { fontSize: 12, lineHeight: 17, marginTop: 2 },
  statusRow: { flexDirection: "row", alignItems: "center", gap: 6, flexShrink: 1 },
  statusText: { fontSize: 12, flexShrink: 1 },
});
