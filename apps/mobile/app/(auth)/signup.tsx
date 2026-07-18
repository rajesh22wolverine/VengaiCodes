import { useEffect, useState } from "react";
import { Text, View, StyleSheet, Pressable } from "react-native";
import { Link, router } from "expo-router";
import { useForm, Controller } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Eye, EyeOff } from "lucide-react-native";

import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { signupUser, clearError, clearOTPState } from "@/store/slices/authSlice";
import { setTigerExpression } from "@/store/slices/uiSlice";
import ScreenContainer from "@/components/ui/ScreenContainer";
import TextField from "@/components/ui/TextField";
import Button from "@/components/ui/Button";
import { useToast } from "@/components/ui/Toast";
import { useTheme } from "@/theme/useTheme";
import { maskEmail } from "@/lib/format";
import BabyTiger from "@/components/BabyTiger";

// ─── Validation Schema (mirrors backend schemas/auth.py SignupRequest) ───
const signupSchema = z
  .object({
    fullName: z
      .string()
      .min(2, "Full name must be at least 2 characters")
      .max(100, "Full name is too long")
      .regex(/^[a-zA-Z\s.']+$/, "Only letters, spaces, dots and apostrophes allowed"),
    username: z
      .string()
      .min(3, "Username must be at least 3 characters")
      .max(30, "Username cannot exceed 30 characters")
      .regex(
        /^[a-zA-Z0-9][a-zA-Z0-9_-]*[a-zA-Z0-9]$/,
        "Only letters, numbers, underscores and hyphens — cannot start/end with - or _"
      ),
    email: z.string().email("Please enter a valid email address"),
    mobile: z.string().regex(/^[6-9]\d{9}$/, "Enter a valid 10-digit Indian mobile number"),
    password: z
      .string()
      .min(8, "At least 8 characters")
      .regex(/[A-Z]/, "At least one uppercase letter")
      .regex(/[a-z]/, "At least one lowercase letter")
      .regex(/\d/, "At least one number")
      .regex(/[!@#$%^&*(),.?":{}|<>_\-+=[\]\\;'/`~]/, "At least one special character"),
    confirmPassword: z.string(),
    agreeToTerms: z.literal(true, {
      errorMap: () => ({ message: "You must agree to the Terms of Service and Privacy Policy" }),
    }),
  })
  .refine((data) => data.password === data.confirmPassword, {
    message: "Passwords do not match",
    path: ["confirmPassword"],
  });

type SignupFormData = z.infer<typeof signupSchema>;

export default function SignupScreen() {
  const dispatch = useAppDispatch();
  const { isLoading, error } = useAppSelector((state) => state.auth);
  const { colors } = useTheme();
  const { showToast } = useToast();
  const [showPassword, setShowPassword] = useState(false);

  const {
    control,
    handleSubmit,
    formState: { errors },
  } = useForm<SignupFormData>({ resolver: zodResolver(signupSchema), defaultValues: { agreeToTerms: undefined } });

  useEffect(() => {
    dispatch(setTigerExpression("excited"));
  }, [dispatch]);

  useEffect(() => {
    if (error) {
      showToast(error, "error");
      dispatch(setTigerExpression("sad"));
      dispatch(clearError());
    }
  }, [error, dispatch, showToast]);

  const onSubmit = async (data: SignupFormData) => {
    dispatch(setTigerExpression("thinking"));
    const result = await dispatch(
      signupUser({ fullName: data.fullName, email: data.email, mobile: data.mobile, username: data.username, password: data.password })
    );

    if (signupUser.fulfilled.match(result)) {
      dispatch(setTigerExpression("celebrating"));
      showToast("Account created! Let's verify your email 🐯");
      dispatch(clearOTPState());
      router.push({
        pathname: "/(auth)/otp",
        params: { target: data.email, otpType: "email", purpose: "signup", maskedTarget: maskEmail(data.email) },
      });
    }
  };

  return (
    <ScreenContainer>
      <View style={styles.brandRow}>
        <BabyTiger size={32} expression="excited" />
        <Text style={styles.brand}>VengaiCode</Text>
      </View>
      <Text style={[styles.title, { color: colors.textPrimary }]}>Create your account</Text>
      <Text style={[styles.subtitle, { color: colors.textSecondary }]}>Zero coding. Baby Tiger builds it with you.</Text>

      <Controller
        control={control}
        name="fullName"
        render={({ field: { onChange, value } }) => (
          <TextField label="Full Name" placeholder="Kalki Raj" value={value} onChangeText={onChange} error={errors.fullName?.message} />
        )}
      />
      <Controller
        control={control}
        name="username"
        render={({ field: { onChange, value } }) => (
          <TextField
            label="Username"
            placeholder="kalki_builds"
            autoCapitalize="none"
            value={value}
            onChangeText={onChange}
            error={errors.username?.message}
          />
        )}
      />
      <Controller
        control={control}
        name="email"
        render={({ field: { onChange, value } }) => (
          <TextField
            label="Email"
            placeholder="you@example.com"
            autoCapitalize="none"
            keyboardType="email-address"
            value={value}
            onChangeText={onChange}
            error={errors.email?.message}
          />
        )}
      />
      <Controller
        control={control}
        name="mobile"
        render={({ field: { onChange, value } }) => (
          <TextField
            label="Mobile Number"
            placeholder="9876543210"
            keyboardType="phone-pad"
            maxLength={10}
            value={value}
            onChangeText={onChange}
            error={errors.mobile?.message}
          />
        )}
      />
      <Controller
        control={control}
        name="password"
        render={({ field: { onChange, value } }) => (
          <TextField
            label="Password"
            placeholder="At least 8 characters"
            secureTextEntry={!showPassword}
            value={value}
            onChangeText={onChange}
            error={errors.password?.message}
            rightElement={
              <Pressable onPress={() => setShowPassword((p) => !p)}>
                {showPassword ? <EyeOff size={18} color={colors.textTertiary} /> : <Eye size={18} color={colors.textTertiary} />}
              </Pressable>
            }
          />
        )}
      />
      <Controller
        control={control}
        name="confirmPassword"
        render={({ field: { onChange, value } }) => (
          <TextField
            label="Confirm Password"
            placeholder="Re-enter your password"
            secureTextEntry={!showPassword}
            value={value}
            onChangeText={onChange}
            error={errors.confirmPassword?.message}
          />
        )}
      />

      <Controller
        control={control}
        name="agreeToTerms"
        render={({ field: { onChange, value } }) => (
          <Pressable style={styles.checkboxRow} onPress={() => onChange(!value)}>
            <View
              style={[
                styles.checkbox,
                { borderColor: colors.border },
                value ? { backgroundColor: colors.primary, borderColor: colors.primary } : null,
              ]}
            />
            <Text style={{ color: colors.textSecondary, flex: 1, fontSize: 13 }}>
              I agree to the Terms of Service and Privacy Policy
            </Text>
          </Pressable>
        )}
      />
      {errors.agreeToTerms && <Text style={[styles.error, { color: colors.error }]}>{errors.agreeToTerms.message}</Text>}

      <View style={{ height: 8 }} />
      <Button title="Create Account" onPress={handleSubmit(onSubmit)} loading={isLoading} />

      <Link href="/(auth)/login" asChild>
        <Pressable style={styles.footerLink}>
          <Text style={{ color: colors.textSecondary, fontSize: 13 }}>
            Already have an account? <Text style={{ color: colors.primary, fontWeight: "600" }}>Sign in</Text>
          </Text>
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
  checkboxRow: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 4 },
  checkbox: { width: 20, height: 20, borderRadius: 5, borderWidth: 1.5 },
  error: { fontSize: 12, marginBottom: 12 },
  footerLink: { alignItems: "center", marginTop: 20 },
});
