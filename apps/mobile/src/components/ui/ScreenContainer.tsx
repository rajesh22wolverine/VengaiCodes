import { KeyboardAvoidingView, Platform, ScrollView, StyleSheet, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTheme } from "@/theme/useTheme";

interface ScreenContainerProps {
  children: React.ReactNode;
  scroll?: boolean;
}

export default function ScreenContainer({ children, scroll = true }: ScreenContainerProps) {
  const { colors } = useTheme();
  const Content = scroll ? ScrollView : View;

  return (
    <SafeAreaView style={[styles.safe, { backgroundColor: colors.background }]}>
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <Content
          style={styles.flex}
          contentContainerStyle={scroll ? styles.scrollContent : styles.flex}
          keyboardShouldPersistTaps="handled"
        >
          {children}
        </Content>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1 },
  flex: { flex: 1 },
  scrollContent: { flexGrow: 1, padding: 24 },
});
