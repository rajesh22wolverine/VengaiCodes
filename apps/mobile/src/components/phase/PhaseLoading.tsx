import { ActivityIndicator, StyleSheet, Text, View } from "react-native";
import { useTheme } from "@/theme/useTheme";
import BabyTiger from "@/components/BabyTiger";

export default function PhaseLoading({ message }: { message: string }) {
  const { colors } = useTheme();
  return (
    <View style={[styles.container, { backgroundColor: colors.background }]}>
      <BabyTiger size={64} expression="thinking" />
      <ActivityIndicator color={colors.primary} />
      <Text style={[styles.message, { color: colors.textSecondary }]}>{message}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, alignItems: "center", justifyContent: "center", gap: 12, padding: 24 },
  message: { fontSize: 13, textAlign: "center" },
});
