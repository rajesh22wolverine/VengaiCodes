import { Pressable, StyleSheet, Text, View } from "react-native";
import { router } from "expo-router";
import { ArrowLeft } from "lucide-react-native";
import { useTheme } from "@/theme/useTheme";
import BabyTiger from "@/components/BabyTiger";

interface PhaseHeaderProps {
  title: string;
  subtitle: string;
}

export default function PhaseHeader({ title, subtitle }: PhaseHeaderProps) {
  const { colors } = useTheme();
  return (
    <View style={[styles.row, { borderBottomColor: colors.border, backgroundColor: colors.surface }]}>
      <Pressable onPress={() => router.push("/(app)/(tabs)/home")} hitSlop={8}>
        <ArrowLeft size={18} color={colors.textSecondary} />
      </Pressable>
      <BabyTiger size={28} expression="happy" />
      <View style={{ flex: 1 }}>
        <Text style={[styles.title, { color: colors.textPrimary }]}>{title}</Text>
        <Text style={[styles.subtitle, { color: colors.textTertiary }]}>{subtitle}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", gap: 12, paddingHorizontal: 16, paddingVertical: 12, borderBottomWidth: StyleSheet.hairlineWidth },
  title: { fontSize: 14, fontWeight: "700" },
  subtitle: { fontSize: 11 },
});
