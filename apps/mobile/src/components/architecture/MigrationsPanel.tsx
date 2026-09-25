// ─── Database migrations panel (Codegen screen) ───
//
// The versioned migrations the "No AI" generator shipped with this app:
// which tool runs them, every revision so far (newest first) with what it
// changes, and how to run them by hand. The generated backend also runs
// them itself on startup, so this is for review — above all, a revision
// that deletes or converts existing data is highlighted, because it's
// the one change a deployed app can't take back.
//
// Collapsed to one line by default so it doesn't push the file list off
// a phone screen — unless the newest revision is destructive, which
// deserves to be seen without a tap.

import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { AlertTriangle, ChevronDown, ChevronRight, History, Terminal } from "lucide-react-native";

import { useTheme } from "@/theme/useTheme";
import {
  MigrationInfo,
  formatRevisionTime,
  migrationToolLabel,
  revisionsNewestFirst,
} from "@/lib/codegenMigrations";
import { plural } from "@/lib/schemaEditorView";
import { monoFont, tint } from "./controls";

export default function MigrationsPanel({ info }: { info: MigrationInfo }) {
  const { colors } = useTheme();
  const revisions = revisionsNewestFirst(info.revisions);
  const latest = revisions[0];
  const latestDestructive = !!latest && latest.destructive.length > 0;
  const [open, setOpen] = useState(latestDestructive);
  const Chevron = open ? ChevronDown : ChevronRight;

  return (
    <View
      style={[
        styles.panel,
        {
          borderColor: latestDestructive ? colors.error : colors.border,
          backgroundColor: colors.surface,
        },
      ]}
    >
      <Pressable
        onPress={() => setOpen((v) => !v)}
        style={styles.header}
        accessibilityRole="button"
        accessibilityState={{ expanded: open }}
      >
        <History size={16} color={colors.primary} />
        <View style={{ flex: 1 }}>
          <Text style={{ color: colors.textPrimary, fontSize: 13, fontWeight: "700" }}>Database migrations</Text>
          <Text style={{ color: colors.textTertiary, fontSize: 11 }} numberOfLines={1}>
            {migrationToolLabel(info.tool)} · {plural(revisions.length, "revision")}
            {latest ? ` · latest ${latest.filename || latest.id}` : ""}
          </Text>
        </View>
        {latestDestructive && <AlertTriangle size={14} color={colors.error} />}
        <Chevron size={16} color={colors.textTertiary} />
      </Pressable>

      {open && (
        <View style={styles.body}>
          <Text style={{ color: colors.textTertiary, fontSize: 11, lineHeight: 16 }}>
            The generated backend applies these automatically when it starts, so its database always matches
            your Architecture tables. Each regenerate adds a new revision instead of rewriting old ones, so a
            database that's already in use is upgraded in place.
          </Text>

          {!!info.run_hint && (
            <View style={[styles.hint, { borderColor: colors.border, backgroundColor: colors.background }]}>
              <Terminal size={12} color={colors.textTertiary} style={{ marginTop: 2 }} />
              <Text selectable style={[monoFont, { color: colors.textSecondary, fontSize: 11, lineHeight: 16, flex: 1 }]}>
                {info.run_hint}
              </Text>
            </View>
          )}

          {revisions.map((rev, i) => {
            const destructive = rev.destructive.length > 0;
            const when = formatRevisionTime(rev.created_at);
            return (
              <View
                key={`${rev.id}-${rev.filename}-${i}`}
                style={[
                  styles.revision,
                  {
                    borderColor: destructive ? colors.error : colors.border,
                    backgroundColor: destructive ? tint(colors.error) : colors.background,
                  },
                ]}
              >
                <View style={styles.revisionTitleRow}>
                  <Text selectable style={[monoFont, styles.filename, { color: colors.textPrimary }]}>
                    {rev.filename || rev.id}
                  </Text>
                  {i === 0 && (
                    <View style={[styles.latestBadge, { backgroundColor: colors.primaryLight }]}>
                      <Text style={{ color: colors.primary, fontSize: 9, fontWeight: "800" }}>LATEST</Text>
                    </View>
                  )}
                </View>
                <Text style={{ color: colors.textTertiary, fontSize: 10, marginTop: 2 }}>
                  revision <Text style={monoFont}>{rev.id}</Text>
                  {when ? ` · ${when}` : ""}
                </Text>

                {rev.summary.map((line, k) => (
                  <Text key={k} style={[styles.line, { color: colors.textSecondary }]}>
                    • {line}
                  </Text>
                ))}
                {rev.summary.length === 0 && (
                  <Text style={[styles.line, { color: colors.textTertiary }]}>No schema changes.</Text>
                )}

                {destructive && (
                  <View style={styles.destructiveBlock}>
                    <View style={styles.destructiveTitleRow}>
                      <AlertTriangle size={12} color={colors.error} />
                      <Text style={{ color: colors.error, fontSize: 11, fontWeight: "800" }}>
                        Deletes or converts existing data
                      </Text>
                    </View>
                    {rev.destructive.map((line, k) => (
                      <Text key={k} style={[styles.line, { color: colors.error }]}>
                        • {line}
                      </Text>
                    ))}
                  </View>
                )}
              </View>
            );
          })}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  panel: { borderWidth: 1, borderRadius: 12, marginBottom: 12 },
  header: { flexDirection: "row", alignItems: "center", gap: 10, padding: 12 },
  body: { paddingHorizontal: 12, paddingBottom: 12, gap: 8 },
  hint: { flexDirection: "row", gap: 6, borderWidth: 1, borderRadius: 8, padding: 8 },
  revision: { borderWidth: 1, borderRadius: 10, padding: 10 },
  revisionTitleRow: { flexDirection: "row", alignItems: "center", gap: 6 },
  filename: { fontSize: 12, fontWeight: "700", flexShrink: 1 },
  latestBadge: { paddingHorizontal: 5, paddingVertical: 1, borderRadius: 4 },
  line: { fontSize: 12, lineHeight: 17, marginTop: 3 },
  destructiveBlock: { marginTop: 6 },
  destructiveTitleRow: { flexDirection: "row", alignItems: "center", gap: 5 },
});
