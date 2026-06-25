import { useState, useEffect, useRef, KeyboardEvent, ClipboardEvent } from "react";
import { useLocation, useNavigate, Navigate } from "react-router-dom";
import { useDispatch, useSelector } from "react-redux";
import { motion } from "framer-motion";
import { Loader2, RotateCw, ArrowLeft } from "lucide-react";
import toast from "react-hot-toast";

import { AppDispatch, RootState } from "@/store";
import { sendOTP, verifyOTP, clearError } from "@/store/slices/authSlice";
import { setTigerExpression } from "@/store/slices/uiSlice";
import BabyTiger from "@/components/baby-tiger/BabyTiger";
import ThemeToggle from "@/components/ui/ThemeToggle";

// State passed via navigate() from SignupScreen / LoginScreen / ForgotPasswordScreen
interface OTPLocationState {
  target: string; // email or mobile (unmasked — needed for verify call)
  otpType: "email" | "mobile";
  purpose: "signup" | "verify" | "login" | "password_reset" | "licence_recovery";
  maskedTarget: string; // for display
}

const OTP_LENGTH = 6;
const RESEND_COOLDOWN_SECONDS = 60;

export default function OTPScreen() {
  const navigate = useNavigate();
  const location = useLocation();
  const dispatch = useDispatch<AppDispatch>();
  const { isLoading, error, isAuthenticated } = useSelector((state: RootState) => state.auth);

  const state = location.state as OTPLocationState | null;

  const [digits, setDigits] = useState<string[]>(Array(OTP_LENGTH).fill(""));
  const [cooldown, setCooldown] = useState(RESEND_COOLDOWN_SECONDS);
  const [isResending, setIsResending] = useState(false);
  const inputRefs = useRef<(HTMLInputElement | null)[]>([]);

  // Redirect if no state was passed (e.g. direct navigation to /otp)
  if (!state?.target || !state?.otpType || !state?.purpose) {
    return <Navigate to="/login" replace />;
  }

  useEffect(() => {
    dispatch(setTigerExpression("excited"));
    inputRefs.current[0]?.focus();
  }, [dispatch]);

  // Countdown timer for resend
  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setInterval(() => setCooldown((c) => Math.max(0, c - 1)), 1000);
    return () => clearInterval(timer);
  }, [cooldown]);

  useEffect(() => {
    if (isAuthenticated) {
      navigate("/home", { replace: true });
    }
  }, [isAuthenticated, navigate]);

  useEffect(() => {
    if (error) {
      toast.error(error);
      dispatch(setTigerExpression("sad"));
      dispatch(clearError());
      // Clear OTP inputs on error to let user retry
      setDigits(Array(OTP_LENGTH).fill(""));
      inputRefs.current[0]?.focus();
    }
  }, [error, dispatch]);

  const handleChange = (index: number, value: string) => {
    if (!/^\d*$/.test(value)) return; // Only digits

    const newDigits = [...digits];
    newDigits[index] = value.slice(-1); // Only last char if pasted/typed fast
    setDigits(newDigits);

    // Auto-advance to next field
    if (value && index < OTP_LENGTH - 1) {
      inputRefs.current[index + 1]?.focus();
    }

    // Auto-submit when all filled
    if (newDigits.every((d) => d !== "") && newDigits.join("").length === OTP_LENGTH) {
      handleVerify(newDigits.join(""));
    }
  };

  const handleKeyDown = (index: number, e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Backspace" && !digits[index] && index > 0) {
      inputRefs.current[index - 1]?.focus();
    }
  };

  const handlePaste = (e: ClipboardEvent<HTMLInputElement>) => {
    e.preventDefault();
    const pasted = e.clipboardData.getData("text").replace(/\D/g, "").slice(0, OTP_LENGTH);
    if (!pasted) return;

    const newDigits = Array(OTP_LENGTH).fill("");
    pasted.split("").forEach((char, i) => {
      newDigits[i] = char;
    });
    setDigits(newDigits);

    if (pasted.length === OTP_LENGTH) {
      handleVerify(pasted);
    } else {
      inputRefs.current[pasted.length]?.focus();
    }
  };

  const handleVerify = async (otp: string) => {
    dispatch(setTigerExpression("thinking"));

    const result = await dispatch(
      verifyOTP({
        target: state.target,
        otp,
        type: state.otpType,
        purpose: state.purpose,
      })
    );

    if (verifyOTP.fulfilled.match(result)) {
      const payload = result.payload as { verified: boolean };
      if (payload.verified) {
        dispatch(setTigerExpression("celebrating"));
        toast.success("Verified! Welcome to VengaiCode 🐯");
        // authSlice sets isAuthenticated=true on success — useEffect above
        // will redirect to /home automatically
      }
    }
  };

  const handleResend = async () => {
    if (cooldown > 0 || isResending) return;
    setIsResending(true);
    dispatch(setTigerExpression("thinking"));

    const result = await dispatch(
      sendOTP({ target: state.target, type: state.otpType, purpose: state.purpose })
    );

    if (sendOTP.fulfilled.match(result)) {
      toast.success("New code sent! Check your " + (state.otpType === "email" ? "inbox" : "messages") + " 🐯");
      setDigits(Array(OTP_LENGTH).fill(""));
      inputRefs.current[0]?.focus();
      setCooldown(RESEND_COOLDOWN_SECONDS);
      dispatch(setTigerExpression("excited"));
    }
    setIsResending(false);
  };

  const isComplete = digits.every((d) => d !== "");

  return (
    <div className="h-full w-full flex flex-col bg-[var(--color-background)]">
      {/* Top bar */}
      <div className="flex items-center justify-between p-6">
        <button
          onClick={() => navigate(-1)}
          className="flex items-center gap-2 text-sm text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)] transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          Back
        </button>
        <ThemeToggle />
      </div>

      {/* Centered content */}
      <div className="flex-1 flex items-center justify-center px-6 pb-12">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="w-full max-w-md text-center"
        >
          {/* Baby Tiger */}
          <motion.div
            initial={{ scale: 0, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ type: "spring", duration: 0.6, bounce: 0.4 }}
            className="flex justify-center mb-6"
          >
            <BabyTiger size={120} expression="excited" />
          </motion.div>

          <h2 className="text-3xl font-bold text-[var(--color-text-primary)] mb-2">
            Verify your {state.otpType === "email" ? "email" : "mobile number"}
          </h2>
          <p className="text-[var(--color-text-secondary)] mb-1">
            Baby Tiger sent a 6-digit code to
          </p>
          <p className="text-[var(--color-text-primary)] font-semibold mb-8">
            {state.maskedTarget}
          </p>

          {/* OTP Input Boxes */}
          <div className="flex justify-center gap-2 sm:gap-3 mb-6" onPaste={handlePaste}>
            {digits.map((digit, index) => (
              <input
                key={index}
                ref={(el) => (inputRefs.current[index] = el)}
                type="text"
                inputMode="numeric"
                autoComplete={index === 0 ? "one-time-code" : "off"}
                maxLength={1}
                value={digit}
                onChange={(e) => handleChange(index, e.target.value)}
                onKeyDown={(e) => handleKeyDown(index, e)}
                disabled={isLoading}
                className="w-12 h-14 sm:w-14 sm:h-16 text-center text-2xl font-bold rounded-xl border-2 bg-[var(--color-surface)] text-[var(--color-text-primary)] border-[var(--color-border)] focus:ring-2 focus:ring-[var(--color-primary)] focus:border-[var(--color-primary)] outline-none transition-all disabled:opacity-50"
              />
            ))}
          </div>

          {/* Verify button (manual, in case auto-submit didn't fire) */}
          <button
            onClick={() => handleVerify(digits.join(""))}
            disabled={!isComplete || isLoading}
            className="w-full py-2.5 rounded-xl bg-[var(--color-primary)] hover:bg-[var(--color-primary-hover)] text-white font-semibold transition-all disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center gap-2 shadow-md hover:shadow-lg mb-4"
          >
            {isLoading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Verifying...
              </>
            ) : (
              "Verify"
            )}
          </button>

          {/* Resend */}
          <div className="text-sm text-[var(--color-text-secondary)]">
            Didn't receive the code?{" "}
            {cooldown > 0 ? (
              <span className="text-[var(--color-text-tertiary)]">
                Resend in {cooldown}s
              </span>
            ) : (
              <button
                onClick={handleResend}
                disabled={isResending}
                className="text-[var(--color-primary)] font-medium hover:text-[var(--color-primary-hover)] inline-flex items-center gap-1 disabled:opacity-60"
              >
                {isResending ? (
                  <RotateCw className="w-3 h-3 animate-spin" />
                ) : (
                  <RotateCw className="w-3 h-3" />
                )}
                Resend code
              </button>
            )}
          </div>
        </motion.div>
      </div>
    </div>
  );
}