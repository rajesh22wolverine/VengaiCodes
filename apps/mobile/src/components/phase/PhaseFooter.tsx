import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";
import { useTheme } from "@/theme/useTheme";

interface SecondaryAction {
  label: string;
  icon: React.ElementType;
  onPress: () => void;
  loading?: boolean;
}

interface PhaseFooterProps {
  note: string;
  secondaryActions?: SecondaryAction[];
  primaryLabel: string;
  primaryIcon: React.ElementType;
  onPrimaryPress: () => void;
  primaryLoading?: boolean;
  primaryDisabled?: boolean;
}

export default function PhaseFooter({
  note,
  secondaryActions,
  primaryLabel,
  primaryIcon: PrimaryIcon,
  onPrimaryPress,
  primaryLoading,
  primaryDisabled,
}: PhaseFooterProps) {
  const { colors } = useTheme();

  return (
    <View style={[styles.container, { borderTopColor: colors.border, backgroundColor: colors.surface }]}>
      <Text style={[styles.note, { color: colors.textTertiary }]}>{note}</Text>
      <View style={styles.buttonRow}>
        {secondaryActions?.map((action) => {
          const Icon = action.icon;
          return (
            <Pressable
              key={action.label}
              onPress={action.onPress}
              disabled={action.loading}
              style={[styles.secondaryButton, { borderColor: colors.border }, action.loading && { opacity: 0.6 }]}
            >
              {action.loading ? <ActivityIndicator size="small" color={colors.textPrimary} /> : <Icon size={15} color={colors.textPrimary} />}
              <Text style={{ color: colors.textPrimary, fontWeight: "600", fontSize: 13 }}>{action.label}</Text>
            </Pressable>
          );
        })}
        <Pressable
          onPress={onPrimaryPress}
          disabled={primaryLoading || primaryDisabled}
          style={[styles.primaryButton, { backgroundColor: colors.primary }, (primaryLoading || primaryDisabled) && { opacity: 0.6 }]}
        >
          {primaryLoading ? <ActivityIndicator size="small" color="#fff" /> : <PrimaryIcon size={15} color="#fff" />}
          <Text style={styles.primaryText}>{primaryLabel}</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { borderTopWidth: StyleSheet.hairlineWidth, padding: 16, gap: 10 },
  note: { fontSize: 11 },
  buttonRow: { flexDirection: "row", gap: 10, flexWrap: "wrap" },
  secondaryButton: { flexDirection: "row", alignItems: "center", gap: 6, borderWidth: 1, borderRadius: 12, paddingHorizontal: 14, paddingVertical: 10 },
  primaryButton: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, borderRadius: 12, paddingVertical: 12, minWidth: 160 },
  primaryText: { color: "#fff", fontWeight: "700", fontSize: 13 },
});
