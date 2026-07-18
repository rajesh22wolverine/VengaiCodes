import { useState } from "react";
import { Text, View, StyleSheet, Pressable } from "react-native";
import { router } from "expo-router";
import { ArrowLeft, Eye, EyeOff } from "lucide-react-native";

import apiClient from "@/lib/api";
import ScreenContainer from "@/components/ui/ScreenContainer";
import TextField from "@/components/ui/TextField";
import Button from "@/components/ui/Button";
import { useToast } from "@/components/ui/Toast";
import { useTheme } from "@/theme/useTheme";

type Step = "email" | "reset";

export default function ForgotPasswordScreen() {
  const { colors } = useTheme();
  const { showToast } = useToast();

  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState("");
  const [otp, setOtp] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);

  const handleSendCode = async () => {
    if (!email.trim()) {
      showToast("Enter your email address first! 🐯", "error");
      return;
    }
    setIsLoading(true);
    try {
      await apiClient.post("/auth/forgot-password", { email: email.trim() });
      showToast("If an account exists, a reset code has been sent! 🐯");
      setStep("reset");
    } catch (error: any) {
      showToast(error.message || "Something went wrong. Try again!", "error");
    } finally {
      setIsLoading(false);
    }
  };

  const handleResetPassword = async () => {
    if (!otp.trim() || otp.length !== 6) {
      showToast("Enter the 6-digit code from your email.", "error");
      return;
    }
    if (newPassword.length < 8) {
      showToast("Password must be at least 8 characters.", "error");
      return;
    }
    if (newPassword !== confirmPassword) {
      showToast("Passwords don't match!", "error");
      return;
    }

    setIsLoading(true);
    try {
      await apiClient.post("/auth/reset-password", {
        email: email.trim(),
        otp: otp.trim(),
        new_password: newPassword,
        confirm_new_password: confirmPassword,
      });
      showToast("Password reset! Please sign in with your new password 🐯");
      router.replace("/(auth)/login");
    } catch (error: any) {
      showToast(error.message || "Failed to reset password. Check your code and try again.", "error");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <ScreenContainer>
      <Pressable onPress={() => (step === "reset" ? setStep("email") : router.back())} style={styles.backRow}>
        <ArrowLeft size={16} color={colors.textSecondary} />
        <Text style={{ color: colors.textSecondary, fontSize: 13 }}>Back</Text>
      </Pressable>

      <Text style={[styles.title, { color: colors.textPrimary }]}>
        {step === "email" ? "Forgot your password?" : "Reset your password"}
      </Text>
      <Text style={[styles.subtitle, { color: colors.textSecondary }]}>
        {step === "email"
          ? "No worries! Enter your email and we'll send you a reset code 🐯"
          : `Enter the code sent to ${email} and choose a new password`}
      </Text>

      {step === "email" ? (
        <>
          <TextField
            label="Email Address"
            placeholder="you@example.com"
            autoCapitalize="none"
            keyboardType="email-address"
            value={email}
            onChangeText={setEmail}
          />
          <Button title="Send Reset Code" onPress={handleSendCode} loading={isLoading} />
        </>
      ) : (
        <>
          <TextField
            label="6-Digit Code"
            placeholder="123456"
            keyboardType="number-pad"
            maxLength={6}
            value={otp}
            onChangeText={(v) => setOtp(v.replace(/\D/g, ""))}
          />
          <TextField
            label="New Password"
            placeholder="At least 8 characters"
            secureTextEntry={!showPassword}
            value={newPassword}
            onChangeText={setNewPassword}
            rightElement={
              <Pressable onPress={() => setShowPassword((p) => !p)}>
                {showPassword ? <EyeOff size={18} color={colors.textTertiary} /> : <Eye size={18} color={colors.textTertiary} />}
              </Pressable>
            }
          />
          <TextField
            label="Confirm New Password"
            placeholder="Re-enter your new password"
            secureTextEntry={!showPassword}
            value={confirmPassword}
            onChangeText={setConfirmPassword}
          />
          <Button title="Reset Password" onPress={handleResetPassword} loading={isLoading} />
          <Pressable onPress={handleSendCode} disabled={isLoading} style={styles.resendLink}>
            <Text style={{ color: colors.textTertiary, fontSize: 12 }}>Didn't get a code? Resend</Text>
          </Pressable>
        </>
      )}
    </ScreenContainer>
  );
}

const styles = StyleSheet.create({
  backRow: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 24 },
  title: { fontSize: 22, fontWeight: "700", marginBottom: 8 },
  subtitle: { fontSize: 13, marginBottom: 24 },
  resendLink: { alignItems: "center", marginTop: 14 },
});
