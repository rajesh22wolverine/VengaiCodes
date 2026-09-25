// ─── Small touch controls for the schema editor ───
//
// What the desktop editor does with <select>, checkboxes and hover
// buttons, adapted to a phone: chip rows (tap to pick, scroll sideways
// when there are many), labelled Switches, collapsible sub-sections and
// generously hit-slopped icon buttons. Pure JS on top of react-native's
// own primitives — no new native dependency, so the Android bundle is
// unaffected.

import { useState } from "react";
import { Pressable, ScrollView, StyleSheet, Switch, Text, View } from "react-native";
import { AlertTriangle, ChevronDown, ChevronRight, Plus, X } from "lucide-react-native";
import { useTheme } from "@/theme/useTheme";

// The theme has no warning/info/accent tokens (only error/success), so
// these stay fixed across light and dark — the same amber the Codegen
// screen already uses for its fallback warning. "22" = a light tint.
export const WARNING_COLOR = "#eab308";
export const INFO_COLOR = "#38bdf8";
export const ACCENT_COLOR = "#a855f7";
export const tint = (color: string) => `${color}22`;

export const monoFont = { fontFamily: "monospace" } as const;

/** One pickable chip. `tone` colours a selected chip (default primary). */
export function Chip({
  label,
  selected,
  disabled,
  onPress,
  mono,
  badge,
  strike,
  tone,
}: {
  label: string;
  selected?: boolean;
  disabled?: boolean;
  onPress: () => void;
  mono?: boolean;
  /** Small leading marker, e.g. a column's position in an index. */
  badge?: string;
  /** Struck-through (a stale reference, tap to remove). */
  strike?: boolean;
  tone?: string;
}) {
  const { colors } = useTheme();
  const accent = tone ?? colors.primary;
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      hitSlop={4}
      accessibilityRole="button"
      accessibilityState={{ selected: !!selected, disabled: !!disabled }}
      style={[
        styles.chip,
        { borderColor: colors.border, backgroundColor: colors.background },
        selected && { borderColor: accent, backgroundColor: tint(accent) },
        disabled && { opacity: 0.4 },
      ]}
    >
      {badge ? <Text style={[styles.chipBadge, { color: accent }]}>{badge}</Text> : null}
      <Text
        style={[
          styles.chipText,
          mono && monoFont,
          { color: selected ? accent : colors.textSecondary },
          selected && { fontWeight: "700" },
          strike && { textDecorationLine: "line-through" },
        ]}
      >
        {label}
      </Text>
    </Pressable>
  );
}

/** A single sideways-scrolling line of chips (type / link / rule pickers),
 *  so a long list never pushes the card wider than the screen. */
export function ChipScroller({ children }: { children: React.ReactNode }) {
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      keyboardShouldPersistTaps="handled"
      contentContainerStyle={styles.chipScroller}
    >
      {children}
    </ScrollView>
  );
}

export function FieldLabel({ children }: { children: React.ReactNode }) {
  const { colors } = useTheme();
  return <Text style={[styles.fieldLabel, { color: colors.textTertiary }]}>{children}</Text>;
}

export function SwitchRow({
  label,
  hint,
  value,
  onValueChange,
  disabled,
}: {
  label: string;
  hint?: string;
  value: boolean;
  onValueChange: (next: boolean) => void;
  disabled?: boolean;
}) {
  const { colors } = useTheme();
  return (
    <View style={styles.switchRow}>
      <View style={{ flex: 1 }}>
        <Text style={{ color: colors.textPrimary, fontSize: 12, fontWeight: "600" }}>{label}</Text>
        {hint ? <Text style={{ color: colors.textTertiary, fontSize: 11 }}>{hint}</Text> : null}
      </View>
      <Switch
        value={value}
        onValueChange={onValueChange}
        disabled={disabled}
        trackColor={{ true: colors.primary, false: colors.border }}
        accessibilityLabel={label}
      />
    </View>
  );
}

export function RemoveButton({ onPress, label }: { onPress: () => void; label: string }) {
  const { colors } = useTheme();
  return (
    <Pressable onPress={onPress} hitSlop={10} accessibilityRole="button" accessibilityLabel={label} style={styles.removeButton}>
      <X size={16} color={colors.textTertiary} />
    </Pressable>
  );
}

export function AddButton({ label, onPress, disabled }: { label: string; onPress: () => void; disabled?: boolean }) {
  const { colors } = useTheme();
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      accessibilityRole="button"
      style={[styles.addButton, { borderColor: colors.border }, disabled && { opacity: 0.5 }]}
    >
      <Plus size={13} color={colors.textSecondary} />
      <Text style={{ color: colors.textSecondary, fontSize: 12, fontWeight: "600" }}>{label}</Text>
    </Pressable>
  );
}

/** Messages under the row they're about. */
export function InlineIssues({ messages }: { messages: string[] }) {
  const { colors } = useTheme();
  if (messages.length === 0) return null;
  return (
    <View style={styles.inlineIssues}>
      {messages.map((m, i) => (
        <View key={i} style={styles.inlineIssueRow}>
          <AlertTriangle size={11} color={colors.error} style={{ marginTop: 2 }} />
          <Text style={{ color: colors.error, fontSize: 11, lineHeight: 15, flex: 1 }}>{m}</Text>
        </View>
      ))}
    </View>
  );
}

/** Checks / Indexes / Seed rows: collapsed until there's something in
 *  them — but a section holding a problem is always open, because a
 *  problem inside a collapsed section must never be hidden. */
export function SubSection({
  icon: Icon,
  title,
  count,
  issueCount,
  defaultOpen,
  children,
}: {
  icon: React.ElementType;
  title: string;
  count: number;
  issueCount: number;
  defaultOpen: boolean;
  children: React.ReactNode;
}) {
  const { colors } = useTheme();
  const [open, setOpen] = useState(defaultOpen);
  const isOpen = open || issueCount > 0;
  const Chevron = isOpen ? ChevronDown : ChevronRight;
  return (
    <View style={[styles.subSection, { borderColor: colors.border, backgroundColor: colors.surface }]}>
      <Pressable
        onPress={() => setOpen(!isOpen)}
        style={styles.subSectionHeader}
        accessibilityRole="button"
        accessibilityState={{ expanded: isOpen }}
      >
        <Chevron size={14} color={colors.textTertiary} />
        <Icon size={14} color={colors.primary} />
        <Text style={{ color: colors.textPrimary, fontSize: 12, fontWeight: "700" }}>{title}</Text>
        <Text style={{ color: colors.textTertiary, fontSize: 11 }}>({count})</Text>
        {issueCount > 0 && (
          <Text style={{ color: colors.error, fontSize: 11, fontWeight: "700", marginLeft: "auto" }}>
            {issueCount} problem{issueCount === 1 ? "" : "s"}
          </Text>
        )}
      </Pressable>
      {isOpen && <View style={styles.subSectionBody}>{children}</View>}
    </View>
  );
}

export const controlStyles = StyleSheet.create({
  input: { borderWidth: 1, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 8, fontSize: 12 },
  help: { fontSize: 11, lineHeight: 16, marginBottom: 8 },
  badge: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 5 },
  badgeText: { fontSize: 10, fontWeight: "700", fontFamily: "monospace" },
});

const styles = StyleSheet.create({
  chip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 6,
    minHeight: 32,
  },
  chipText: { fontSize: 12 },
  chipBadge: { fontSize: 10, fontWeight: "800" },
  chipScroller: { gap: 6, paddingVertical: 2, paddingRight: 8 },
  fieldLabel: { fontSize: 10, fontWeight: "700", textTransform: "uppercase", letterSpacing: 0.5, marginTop: 10, marginBottom: 5 },
  switchRow: { flexDirection: "row", alignItems: "center", gap: 10, marginTop: 8 },
  removeButton: { padding: 4 },
  addButton: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    borderWidth: 1,
    borderStyle: "dashed",
    borderRadius: 8,
    paddingVertical: 9,
    marginTop: 8,
  },
  inlineIssues: { gap: 3, marginTop: 6 },
  inlineIssueRow: { flexDirection: "row", gap: 5 },
  subSection: { borderWidth: 1, borderRadius: 10, marginTop: 10 },
  subSectionHeader: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 10, paddingVertical: 10 },
  subSectionBody: { paddingHorizontal: 10, paddingBottom: 10 },
});
