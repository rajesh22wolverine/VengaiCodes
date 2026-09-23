import { StyleSheet, Text, View } from "react-native";
import { useTheme } from "@/theme/useTheme";

interface SectionProps {
  icon: React.ElementType;
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}

export default function Section({ icon: Icon, title, action, children }: SectionProps) {
  const { colors } = useTheme();
  return (
    <View style={[styles.card, { borderColor: colors.border, backgroundColor: colors.surface }]}>
      <View style={styles.header}>
        <View style={styles.headerLeft}>
          <Icon size={16} color={colors.primary} />
          <Text style={[styles.title, { color: colors.textPrimary }]}>{title}</Text>
        </View>
        {action}
      </View>
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { borderWidth: 1, borderRadius: 16, padding: 16, marginBottom: 16 },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 8, marginBottom: 10 },
  headerLeft: { flexDirection: "row", alignItems: "center", gap: 8 },
  title: { fontSize: 14, fontWeight: "700" },
});
