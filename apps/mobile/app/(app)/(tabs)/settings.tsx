import { Pressable, StyleSheet, Text, View } from "react-native";
import { router } from "expo-router";
import { LogOut, Moon, Sun } from "lucide-react-native";

import ScreenContainer from "@/components/ui/ScreenContainer";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { logoutUser } from "@/store/slices/authSlice";
import { toggleTheme } from "@/store/slices/uiSlice";
import { useTheme } from "@/theme/useTheme";

export default function SettingsScreen() {
  const dispatch = useAppDispatch();
  const { colors, theme } = useTheme();
  const { user } = useAppSelector((state) => state.auth);

  const handleLogout = async () => {
    await dispatch(logoutUser());
    router.replace("/(auth)/login");
  };

  return (
    <ScreenContainer>
      <Text style={[styles.title, { color: colors.textPrimary }]}>Settings</Text>

      {user && (
        <View style={[styles.profileCard, { borderColor: colors.border, backgroundColor: colors.surface }]}>
          <View style={[styles.avatar, { backgroundColor: colors.primaryLight }]}>
            <Text style={{ color: colors.primary, fontWeight: "700", fontSize: 18 }}>
              {user.full_name.charAt(0).toUpperCase()}
            </Text>
          </View>
          <View style={{ flex: 1 }}>
            <Text style={[styles.name, { color: colors.textPrimary }]}>{user.full_name}</Text>
            <Text style={[styles.tier, { color: colors.textTertiary }]}>{user.tier} tier</Text>
          </View>
        </View>
      )}

      <Pressable
        onPress={() => dispatch(toggleTheme())}
        style={[styles.row, { borderColor: colors.border, backgroundColor: colors.surface }]}
      >
        {theme === "dark" ? <Moon size={18} color={colors.textPrimary} /> : <Sun size={18} color={colors.textPrimary} />}
        <Text style={{ color: colors.textPrimary, fontSize: 14, flex: 1 }}>
          {theme === "dark" ? "Dark theme" : "Light theme"}
        </Text>
        <Text style={{ color: colors.textTertiary, fontSize: 12 }}>Tap to switch</Text>
      </Pressable>

      <View style={[styles.comingSoonCard, { borderColor: colors.border, backgroundColor: colors.surface }]}>
        <Text style={{ color: colors.textSecondary, fontSize: 13, textAlign: "center" }}>
          More settings — Coming Soon 🐯
        </Text>
      </View>

      <Pressable onPress={handleLogout} style={[styles.row, { borderColor: colors.error, backgroundColor: colors.surface }]}>
        <LogOut size={18} color={colors.error} />
        <Text style={{ color: colors.error, fontSize: 14, fontWeight: "600" }}>Logout</Text>
      </Pressable>
    </ScreenContainer>
  );
}

const styles = StyleSheet.create({
  title: { fontSize: 22, fontWeight: "700", marginBottom: 20 },
  profileCard: { flexDirection: "row", alignItems: "center", gap: 12, borderWidth: 1, borderRadius: 14, padding: 14, marginBottom: 16 },
  avatar: { width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center" },
  name: { fontSize: 15, fontWeight: "700" },
  tier: { fontSize: 12, textTransform: "capitalize" },
  row: { flexDirection: "row", alignItems: "center", gap: 10, borderWidth: 1, borderRadius: 12, padding: 14, marginBottom: 12 },
  comingSoonCard: { borderWidth: 1, borderRadius: 12, padding: 20, marginBottom: 12, alignItems: "center" },
});
