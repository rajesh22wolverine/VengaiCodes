import { useState, useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useDispatch, useSelector } from "react-redux";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { motion } from "framer-motion";
import { Eye, EyeOff, Mail, Lock, User, Phone, Loader2, Check } from "lucide-react";
import toast from "react-hot-toast";

import { AppDispatch, RootState } from "@/store";
import { signupUser, clearError, clearOTPState } from "@/store/slices/authSlice";
import { setTigerExpression } from "@/store/slices/uiSlice";
import BabyTiger from "@/components/baby-tiger/BabyTiger";
import ThemeToggle from "@/components/ui/ThemeToggle";

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
    mobile: z
      .string()
      .regex(/^[6-9]\d{9}$/, "Enter a valid 10-digit Indian mobile number"),
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

// ─── Password Strength Helper ───
function getPasswordStrength(password: string): { score: number; label: string; color: string } {
  let score = 0;
  if (password.length >= 8) score++;
  if (/[A-Z]/.test(password)) score++;
  if (/[a-z]/.test(password)) score++;
  if (/\d/.test(password)) score++;
  if (/[!@#$%^&*(),.?":{}|<>_\-+=[\]\\;'/`~]/.test(password)) score++;

  if (score <= 2) return { score, label: "Weak", color: "var(--color-error)" };
  if (score <= 4) return { score, label: "Good", color: "var(--color-accent)" };
  return { score, label: "Strong", color: "var(--color-success)" };
}

export default function SignupScreen() {
  const navigate = useNavigate();
  const dispatch = useDispatch<AppDispatch>();
  const { isLoading, error } = useSelector((state: RootState) => state.auth);
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);

  const {
    register,
    handleSubmit,
    watch,
    formState: { errors },
    setFocus,
  } = useForm<SignupFormData>({
    resolver: zodResolver(signupSchema),
    mode: "onBlur",
  });

  const passwordValue = watch("password") || "";
  const strength = getPasswordStrength(passwordValue);

  useEffect(() => {
    setFocus("fullName");
    dispatch(setTigerExpression("excited"));
  }, [setFocus, dispatch]);

  useEffect(() => {
    if (error) {
      toast.error(error);
      dispatch(setTigerExpression("sad"));
      dispatch(clearError());
    }
  }, [error, dispatch]);

  const onSubmit = async (data: SignupFormData) => {
    dispatch(setTigerExpression("thinking"));

    const result = await dispatch(
      signupUser({
        fullName: data.fullName,
        email: data.email,
        mobile: data.mobile,
        username: data.username,
        password: data.password,
      })
    );

    if (signupUser.fulfilled.match(result)) {
      dispatch(setTigerExpression("celebrating"));
      toast.success("Account created! Let's verify your email 🐯");
      dispatch(clearOTPState());
      // Navigate to OTP screen with context for email verification
      navigate("/otp", {
        state: {
          target: data.email,
          otpType: "email",
          purpose: "signup",
          maskedTarget: maskEmail(data.email),
        },
      });
    }
  };

  return (
    <div className="h-full w-full flex overflow-hidden">
      {/* ═══════════════════════════════════ */}
      {/* Left Panel — Animated Brand Section */}
      {/* ═══════════════════════════════════ */}
      <div className="hidden lg:flex lg:w-1/2 animated-bg relative items-center justify-center overflow-hidden">
        {Array.from({ length: 12 }).map((_, i) => (
          <div
            key={i}
            className="particle"
            style={
              {
                width: `${20 + Math.random() * 60}px`,
                height: `${20 + Math.random() * 60}px`,
                left: `${Math.random() * 100}%`,
                top: `${Math.random() * 100}%`,
                "--duration": `${4 + Math.random() * 6}s`,
                "--delay": `${Math.random() * 4}s`,
              } as React.CSSProperties
            }
          />
        ))}

        <div className="relative z-10 text-center px-12">
          <motion.div
            initial={{ scale: 0, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ type: "spring", duration: 0.8, bounce: 0.4 }}
            className="mb-8 flex justify-center"
          >
            <BabyTiger size={180} expression="excited" />
          </motion.div>

          <motion.h1
            initial={{ y: 20, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ delay: 0.3, duration: 0.5 }}
            className="text-5xl font-extrabold text-white mb-3 tracking-tight"
          >
            Join VengaiCode
          </motion.h1>

          <motion.p
            initial={{ y: 20, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ delay: 0.45, duration: 0.5 }}
            className="text-white/90 text-lg mb-2"
          >
            Your first app is completely free 🐯
          </motion.p>

          <motion.p
            initial={{ y: 20, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ delay: 0.6, duration: 0.5 }}
            className="text-white/70 text-sm max-w-md mx-auto mb-8"
          >
            Describe your idea in plain English. Baby Tiger asks a few smart
            questions. VengaiCode builds the complete app — Web, Mobile,
            Desktop — in under 30 minutes.
          </motion.p>

          {/* What you get */}
          <motion.div
            initial={{ y: 20, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ delay: 0.75, duration: 0.5 }}
            className="space-y-2 text-left max-w-sm mx-auto"
          >
            {[
              "1 free project — all features unlocked",
              "Web + Mobile + Desktop generated together",
              "Complete SDLC docs — FRD, SRS, BRD, UML",
              "100% open-source — you own everything",
            ].map((item) => (
              <div key={item} className="flex items-center gap-2 text-white/90 text-sm">
                <span className="flex-shrink-0 w-5 h-5 rounded-full bg-white/20 flex items-center justify-center">
                  <Check className="w-3 h-3" />
                </span>
                {item}
              </div>
            ))}
          </motion.div>
        </div>
      </div>

      {/* ═══════════════════════════════════ */}
      {/* Right Panel — Signup Form */}
      {/* ═══════════════════════════════════ */}
      <div className="flex-1 flex flex-col bg-[var(--color-background)] overflow-y-auto">
        <div className="flex justify-end p-6">
          <ThemeToggle />
        </div>

        <div className="flex-1 flex items-center justify-center px-6 pb-12">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4 }}
            className="w-full max-w-md"
          >
            <div className="lg:hidden flex justify-center mb-6">
              <BabyTiger size={80} expression="excited" />
            </div>

            <div className="mb-6 text-center lg:text-left">
              <h2 className="text-3xl font-bold text-[var(--color-text-primary)] mb-2">
                Create your account
              </h2>
              <p className="text-[var(--color-text-secondary)]">
                Start building with Baby Tiger — it's free 🐯
              </p>
            </div>

            <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
              {/* Full Name */}
              <div>
                <label htmlFor="fullName" className="block text-sm font-medium text-[var(--color-text-primary)] mb-1.5">
                  Full Name
                </label>
                <div className="relative">
                  <User className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--color-text-tertiary)]" />
                  <input
                    {...register("fullName")}
                    type="text"
                    id="fullName"
                    autoComplete="name"
                    placeholder="Kalki Kumar"
                    className={`w-full pl-10 pr-4 py-2.5 rounded-xl border bg-[var(--color-surface)] text-[var(--color-text-primary)] placeholder:text-[var(--color-text-tertiary)] focus:ring-2 focus:ring-[var(--color-primary)] focus:border-[var(--color-primary)] outline-none transition-all ${
                      errors.fullName ? "border-[var(--color-error)]" : "border-[var(--color-border)]"
                    }`}
                  />
                </div>
                {errors.fullName && <p className="mt-1.5 text-xs text-[var(--color-error)]">{errors.fullName.message}</p>}
              </div>

              {/* Username */}
              <div>
                <label htmlFor="username" className="block text-sm font-medium text-[var(--color-text-primary)] mb-1.5">
                  Username
                </label>
                <div className="relative">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-text-tertiary)] text-sm">@</span>
                  <input
                    {...register("username")}
                    type="text"
                    id="username"
                    autoComplete="username"
                    placeholder="kalki_builds"
                    className={`w-full pl-8 pr-4 py-2.5 rounded-xl border bg-[var(--color-surface)] text-[var(--color-text-primary)] placeholder:text-[var(--color-text-tertiary)] focus:ring-2 focus:ring-[var(--color-primary)] focus:border-[var(--color-primary)] outline-none transition-all ${
                      errors.username ? "border-[var(--color-error)]" : "border-[var(--color-border)]"
                    }`}
                  />
                </div>
                {errors.username && <p className="mt-1.5 text-xs text-[var(--color-error)]">{errors.username.message}</p>}
              </div>

              {/* Email */}
              <div>
                <label htmlFor="email" className="block text-sm font-medium text-[var(--color-text-primary)] mb-1.5">
                  Email Address
                </label>
                <div className="relative">
                  <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--color-text-tertiary)]" />
                  <input
                    {...register("email")}
                    type="email"
                    id="email"
                    autoComplete="email"
                    placeholder="kalki@example.com"
                    className={`w-full pl-10 pr-4 py-2.5 rounded-xl border bg-[var(--color-surface)] text-[var(--color-text-primary)] placeholder:text-[var(--color-text-tertiary)] focus:ring-2 focus:ring-[var(--color-primary)] focus:border-[var(--color-primary)] outline-none transition-all ${
                      errors.email ? "border-[var(--color-error)]" : "border-[var(--color-border)]"
                    }`}
                  />
                </div>
                {errors.email && <p className="mt-1.5 text-xs text-[var(--color-error)]">{errors.email.message}</p>}
              </div>

              {/* Mobile */}
              <div>
                <label htmlFor="mobile" className="block text-sm font-medium text-[var(--color-text-primary)] mb-1.5">
                  Mobile Number
                </label>
                <div className="relative">
                  <Phone className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--color-text-tertiary)]" />
                  <span className="absolute left-10 top-1/2 -translate-y-1/2 text-sm text-[var(--color-text-secondary)]">+91</span>
                  <input
                    {...register("mobile")}
                    type="tel"
                    id="mobile"
                    autoComplete="tel-national"
                    maxLength={10}
                    placeholder="9876543210"
                    className={`w-full pl-[4.5rem] pr-4 py-2.5 rounded-xl border bg-[var(--color-surface)] text-[var(--color-text-primary)] placeholder:text-[var(--color-text-tertiary)] focus:ring-2 focus:ring-[var(--color-primary)] focus:border-[var(--color-primary)] outline-none transition-all ${
                      errors.mobile ? "border-[var(--color-error)]" : "border-[var(--color-border)]"
                    }`}
                  />
                </div>
                {errors.mobile && <p className="mt-1.5 text-xs text-[var(--color-error)]">{errors.mobile.message}</p>}
              </div>

              {/* Password */}
              <div>
                <label htmlFor="password" className="block text-sm font-medium text-[var(--color-text-primary)] mb-1.5">
                  Password
                </label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--color-text-tertiary)]" />
                  <input
                    {...register("password")}
                    type={showPassword ? "text" : "password"}
                    id="password"
                    autoComplete="new-password"
                    placeholder="••••••••"
                    className={`w-full pl-10 pr-11 py-2.5 rounded-xl border bg-[var(--color-surface)] text-[var(--color-text-primary)] placeholder:text-[var(--color-text-tertiary)] focus:ring-2 focus:ring-[var(--color-primary)] focus:border-[var(--color-primary)] outline-none transition-all ${
                      errors.password ? "border-[var(--color-error)]" : "border-[var(--color-border)]"
                    }`}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((p) => !p)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--color-text-tertiary)] hover:text-[var(--color-text-secondary)]"
                    tabIndex={-1}
                  >
                    {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>

                {/* Password strength indicator */}
                {passwordValue && (
                  <div className="mt-2">
                    <div className="flex gap-1 mb-1">
                      {[0, 1, 2, 3, 4].map((i) => (
                        <div
                          key={i}
                          className="h-1 flex-1 rounded-full transition-colors"
                          style={{
                            backgroundColor:
                              i < strength.score ? strength.color : "var(--color-border)",
                          }}
                        />
                      ))}
                    </div>
                    <p className="text-xs" style={{ color: strength.color }}>
                      Password strength: {strength.label}
                    </p>
                  </div>
                )}
                {errors.password && <p className="mt-1.5 text-xs text-[var(--color-error)]">{errors.password.message}</p>}
              </div>

              {/* Confirm Password */}
              <div>
                <label htmlFor="confirmPassword" className="block text-sm font-medium text-[var(--color-text-primary)] mb-1.5">
                  Confirm Password
                </label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--color-text-tertiary)]" />
                  <input
                    {...register("confirmPassword")}
                    type={showConfirmPassword ? "text" : "password"}
                    id="confirmPassword"
                    autoComplete="new-password"
                    placeholder="••••••••"
                    className={`w-full pl-10 pr-11 py-2.5 rounded-xl border bg-[var(--color-surface)] text-[var(--color-text-primary)] placeholder:text-[var(--color-text-tertiary)] focus:ring-2 focus:ring-[var(--color-primary)] focus:border-[var(--color-primary)] outline-none transition-all ${
                      errors.confirmPassword ? "border-[var(--color-error)]" : "border-[var(--color-border)]"
                    }`}
                  />
                  <button
                    type="button"
                    onClick={() => setShowConfirmPassword((p) => !p)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--color-text-tertiary)] hover:text-[var(--color-text-secondary)]"
                    tabIndex={-1}
                  >
                    {showConfirmPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
                {errors.confirmPassword && <p className="mt-1.5 text-xs text-[var(--color-error)]">{errors.confirmPassword.message}</p>}
              </div>

              {/* Terms agreement */}
              <div>
                <div className="flex items-start gap-2">
                  <input
                    {...register("agreeToTerms")}
                    type="checkbox"
                    id="agreeToTerms"
                    className="mt-0.5 w-4 h-4 rounded border-[var(--color-border)] text-[var(--color-primary)] focus:ring-[var(--color-primary)]"
                  />
                  <label htmlFor="agreeToTerms" className="text-sm text-[var(--color-text-secondary)] cursor-pointer">
                    I agree to VengaiCode's{" "}
                    <a href="#" className="text-[var(--color-primary)] underline hover:text-[var(--color-primary-hover)]">
                      Terms of Service
                    </a>{" "}
                    and{" "}
                    <a href="#" className="text-[var(--color-primary)] underline hover:text-[var(--color-primary-hover)]">
                      Privacy Policy
                    </a>
                  </label>
                </div>
                {errors.agreeToTerms && <p className="mt-1.5 text-xs text-[var(--color-error)]">{errors.agreeToTerms.message}</p>}
              </div>

              {/* Submit */}
              <button
                type="submit"
                disabled={isLoading}
                className="w-full py-2.5 rounded-xl bg-[var(--color-primary)] hover:bg-[var(--color-primary-hover)] text-white font-semibold transition-all disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center gap-2 shadow-md hover:shadow-lg"
              >
                {isLoading ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Creating your account...
                  </>
                ) : (
                  "Create Account"
                )}
              </button>
            </form>

            <div className="my-6 flex items-center gap-3">
              <div className="flex-1 h-px bg-[var(--color-border)]" />
              <span className="text-xs text-[var(--color-text-tertiary)]">Already have an account?</span>
              <div className="flex-1 h-px bg-[var(--color-border)]" />
            </div>

            <Link
              to="/login"
              className="w-full block text-center py-2.5 rounded-xl border border-[var(--color-border)] hover:border-[var(--color-primary)] text-[var(--color-text-primary)] font-medium transition-all hover:bg-[var(--color-primary-light)]"
            >
              Sign in instead
            </Link>
          </motion.div>
        </div>
      </div>
    </div>
  );
}

// ─── Helper — mirrors backend mask_email() ───
function maskEmail(email: string): string {
  const [local, domain] = email.split("@");
  if (!local || !domain) return email;
  const masked = local.length <= 2 ? local[0] + "*" : local.slice(0, 2) + "*".repeat(local.length - 2);
  return `${masked}@${domain}`;
}
