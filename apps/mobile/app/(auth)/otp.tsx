import { useEffect, useRef, useState } from "react";
import { Text, View, StyleSheet, TextInput, Pressable, NativeSyntheticEvent, TextInputKeyPressEventData } from "react-native";
import { Redirect, router, useLocalSearchParams } from "expo-router";
import { ArrowLeft, RotateCw } from "lucide-react-native";

import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { sendOTP, verifyOTP, clearError } from "@/store/slices/authSlice";
import { setTigerExpression } from "@/store/slices/uiSlice";
import ScreenContainer from "@/components/ui/ScreenContainer";
import Button from "@/components/ui/Button";
import { useToast } from "@/components/ui/Toast";
import { useTheme } from "@/theme/useTheme";
import BabyTiger from "@/components/BabyTiger";

const OTP_LENGTH = 6;
const RESEND_COOLDOWN_SECONDS = 60;

type OtpPurpose = "login" | "signup" | "verify" | "password_reset" | "licence_recovery";

export default function OTPScreen() {
  const params = useLocalSearchParams<{
    target?: string;
    otpType?: "email" | "mobile";
    purpose?: OtpPurpose;
    maskedTarget?: string;
  }>();
  const dispatch = useAppDispatch();
  const { isLoading, error } = useAppSelector((state) => state.auth);
  const { colors } = useTheme();
  const { showToast } = useToast();

  const [digits, setDigits] = useState<string[]>(Array(OTP_LENGTH).fill(""));
  const [cooldown, setCooldown] = useState(RESEND_COOLDOWN_SECONDS);
  const [isResending, setIsResending] = useState(false);
  const inputRefs = useRef<(TextInput | null)[]>([]);

  if (!params.target || !params.otpType || !params.purpose) {
    return <Redirect href="/(auth)/login" />;
  }
  const { target, otpType, purpose, maskedTarget } = params as {
    target: string;
    otpType: "email" | "mobile";
    purpose: OtpPurpose;
    maskedTarget: string;
  };

  useEffect(() => {
    dispatch(setTigerExpression("excited"));
  }, [dispatch]);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setInterval(() => setCooldown((c) => Math.max(0, c - 1)), 1000);
    return () => clearInterval(timer);
  }, [cooldown]);

  useEffect(() => {
    if (error) {
      showToast(error, "error");
      dispatch(setTigerExpression("sad"));
      dispatch(clearError());
      setDigits(Array(OTP_LENGTH).fill(""));
      inputRefs.current[0]?.focus();
    }
  }, [error, dispatch, showToast]);

  const handleVerify = async (otp: string) => {
    dispatch(setTigerExpression("thinking"));
    const result = await dispatch(verifyOTP({ target, otp, type: otpType, purpose }));
    if (verifyOTP.fulfilled.match(result)) {
      const payload = result.payload as { verified: boolean };
      if (payload.verified) {
        dispatch(setTigerExpression("celebrating"));
        showToast("Verified! Welcome to VengaiCode 🐯");
        if (purpose === "password_reset" || purpose === "licence_recovery") {
          router.replace("/(auth)/login");
        } else {
          router.replace("/(app)/(tabs)/home");
        }
      }
    }
  };

  const handleChange = (index: number, value: string) => {
    const digit = value.replace(/\D/g, "").slice(-1);
    const newDigits = [...digits];
    newDigits[index] = digit;
    setDigits(newDigits);

    if (digit && index < OTP_LENGTH - 1) {
      inputRefs.current[index + 1]?.focus();
    }
    if (newDigits.every((d) => d !== "")) {
      handleVerify(newDigits.join(""));
    }
  };

  const handleKeyPress = (index: number, e: NativeSyntheticEvent<TextInputKeyPressEventData>) => {
    if (e.nativeEvent.key === "Backspace" && !digits[index] && index > 0) {
      inputRefs.current[index - 1]?.focus();
    }
  };

  const handleResend = async () => {
    if (cooldown > 0 || isResending) return;
    setIsResending(true);
    dispatch(setTigerExpression("thinking"));
    const result = await dispatch(sendOTP({ target, type: otpType, purpose }));
    if (sendOTP.fulfilled.match(result)) {
      showToast(`New code sent! Check your ${otpType === "email" ? "inbox" : "messages"} 🐯`);
      setDigits(Array(OTP_LENGTH).fill(""));
      inputRefs.current[0]?.focus();
      setCooldown(RESEND_COOLDOWN_SECONDS);
      dispatch(setTigerExpression("excited"));
    }
    setIsResending(false);
  };

  const isComplete = digits.every((d) => d !== "");

  return (
    <ScreenContainer scroll={false}>
      <Pressable onPress={() => router.back()} style={styles.backRow}>
        <ArrowLeft size={16} color={colors.textSecondary} />
        <Text style={{ color: colors.textSecondary, fontSize: 13 }}>Back</Text>
      </Pressable>

      <View style={styles.centered}>
        <BabyTiger size={80} expression="excited" style={styles.brand} />
        <Text style={[styles.title, { color: colors.textPrimary }]}>
          Verify your {otpType === "email" ? "email" : "mobile number"}
        </Text>
        <Text style={[styles.subtitle, { color: colors.textSecondary }]}>Baby Tiger sent a 6-digit code to</Text>
        <Text style={[styles.target, { color: colors.textPrimary }]}>{maskedTarget}</Text>

        <View style={styles.otpRow}>
          {digits.map((digit, index) => (
            <TextInput
              key={index}
              ref={(el) => {
                inputRefs.current[index] = el;
              }}
              style={[
                styles.otpBox,
                { color: colors.textPrimary, backgroundColor: colors.surface, borderColor: colors.border },
              ]}
              keyboardType="number-pad"
              maxLength={1}
              value={digit}
              editable={!isLoading}
              onChangeText={(value) => handleChange(index, value)}
              onKeyPress={(e) => handleKeyPress(index, e)}
            />
          ))}
        </View>

        <Button title="Verify" onPress={() => handleVerify(digits.join(""))} loading={isLoading} disabled={!isComplete} />

        <View style={styles.resendRow}>
          <Text style={{ color: colors.textSecondary, fontSize: 13 }}>Didn't receive the code? </Text>
          {cooldown > 0 ? (
            <Text style={{ color: colors.textTertiary, fontSize: 13 }}>Resend in {cooldown}s</Text>
          ) : (
            <Pressable onPress={handleResend} disabled={isResending} style={styles.resendButton}>
              <RotateCw size={13} color={colors.primary} />
              <Text style={{ color: colors.primary, fontSize: 13, fontWeight: "600" }}>Resend code</Text>
            </Pressable>
          )}
        </View>
      </View>
    </ScreenContainer>
  );
}

const styles = StyleSheet.create({
  backRow: { flexDirection: "row", alignItems: "center", gap: 6, padding: 24, paddingBottom: 0 },
  centered: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24 },
  brand: { fontSize: 48, marginBottom: 16 },
  title: { fontSize: 22, fontWeight: "700", textAlign: "center", marginBottom: 8 },
  subtitle: { fontSize: 14, marginBottom: 2 },
  target: { fontSize: 15, fontWeight: "600", marginBottom: 28 },
  otpRow: { flexDirection: "row", gap: 10, marginBottom: 24 },
  otpBox: {
    width: 44,
    height: 54,
    borderWidth: 2,
    borderRadius: 12,
    textAlign: "center",
    fontSize: 22,
    fontWeight: "700",
  },
  resendRow: { flexDirection: "row", alignItems: "center", marginTop: 16 },
  resendButton: { flexDirection: "row", alignItems: "center", gap: 4 },
});
