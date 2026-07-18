import { useEffect, useState } from "react";
import { Text, View, StyleSheet, Pressable } from "react-native";
import { Link, router } from "expo-router";
import { useForm, Controller } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Eye, EyeOff } from "lucide-react-native";

import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { loginUser, clearError } from "@/store/slices/authSlice";
import { setTigerExpression } from "@/store/slices/uiSlice";
import ScreenContainer from "@/components/ui/ScreenContainer";
import TextField from "@/components/ui/TextField";
import Button from "@/components/ui/Button";
import { useToast } from "@/components/ui/Toast";
import { useTheme } from "@/theme/useTheme";
import BabyTiger from "@/components/BabyTiger";

const loginSchema = z.object({
  usernameOrEmail: z.string().min(1, "Please enter your username or email"),
  password: z.string().min(1, "Please enter your password"),
});

type LoginFormData = z.infer<typeof loginSchema>;

export default function LoginScreen() {
  const dispatch = useAppDispatch();
  const { isLoading, error } = useAppSelector((state) => state.auth);
  const { colors } = useTheme();
  const { showToast } = useToast();
  const [showPassword, setShowPassword] = useState(false);

  const {
    control,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginFormData>({ resolver: zodResolver(loginSchema) });

  useEffect(() => {
    dispatch(setTigerExpression("waving"));
  }, [dispatch]);

  useEffect(() => {
    if (error) {
      showToast(error, "error");
      dispatch(setTigerExpression("sad"));
      dispatch(clearError());
    }
  }, [error, dispatch, showToast]);

  const onSubmit = async (data: LoginFormData) => {
    dispatch(setTigerExpression("thinking"));
    const result = await dispatch(loginUser({ usernameOrEmail: data.usernameOrEmail, password: data.password }));
    if (loginUser.fulfilled.match(result)) {
      dispatch(setTigerExpression("celebrating"));
      showToast("Welcome back! Baby Tiger missed you! 🐯");
      router.replace("/(app)/(tabs)/home");
    }
  };

  return (
    <ScreenContainer>
      <View style={styles.brandRow}>
        <BabyTiger size={32} expression="waving" />
        <Text style={styles.brand}>VengaiCode</Text>
      </View>
      <Text style={[styles.title, { color: colors.textPrimary }]}>Welcome back!</Text>
      <Text style={[styles.subtitle, { color: colors.textSecondary }]}>
        Sign in to continue building with Baby Tiger 🐯
      </Text>

      <Controller
        control={control}
        name="usernameOrEmail"
        render={({ field: { onChange, value } }) => (
          <TextField
            label="Username or Email"
            placeholder="kalki_builds or kalki@example.com"
            autoCapitalize="none"
            value={value}
            onChangeText={onChange}
            error={errors.usernameOrEmail?.message}
          />
        )}
      />

      <Controller
        control={control}
        name="password"
        render={({ field: { onChange, value } }) => (
          <TextField
            label="Password"
            placeholder="••••••••"
            secureTextEntry={!showPassword}
            value={value}
            onChangeText={onChange}
            error={errors.password?.message}
            rightElement={
              <Pressable onPress={() => setShowPassword((p) => !p)}>
                {showPassword ? (
                  <EyeOff size={18} color={colors.textTertiary} />
                ) : (
                  <Eye size={18} color={colors.textTertiary} />
                )}
              </Pressable>
            }
          />
        )}
      />

      <Link href="/(auth)/forgot-password" style={[styles.link, { color: colors.primary }]}>
        Forgot password?
      </Link>

      <View style={{ height: 8 }} />
      <Button title="Sign In" onPress={handleSubmit(onSubmit)} loading={isLoading} />

      <View style={styles.dividerRow}>
        <View style={[styles.divider, { backgroundColor: colors.border }]} />
        <Text style={{ color: colors.textTertiary, fontSize: 12 }}>New to VengaiCode?</Text>
        <View style={[styles.divider, { backgroundColor: colors.border }]} />
      </View>

      <Link href="/(auth)/signup" asChild>
        <Pressable style={[styles.outlineButton, { borderColor: colors.border }]}>
          <Text style={{ color: colors.textPrimary, fontWeight: "600" }}>Create your account — it's free 🐯</Text>
        </Pressable>
      </Link>
    </ScreenContainer>
  );
}

const styles = StyleSheet.create({
  brandRow: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, marginBottom: 24 },
  brand: { fontSize: 20, fontWeight: "700" },
  title: { fontSize: 26, fontWeight: "700", marginBottom: 6 },
  subtitle: { fontSize: 14, marginBottom: 28 },
  link: { alignSelf: "flex-end", fontSize: 12, fontWeight: "600", marginBottom: 16, marginTop: -8 },
  dividerRow: { flexDirection: "row", alignItems: "center", gap: 10, marginVertical: 20 },
  divider: { flex: 1, height: 1 },
  outlineButton: { borderWidth: 1, borderRadius: 12, paddingVertical: 14, alignItems: "center" },
});
