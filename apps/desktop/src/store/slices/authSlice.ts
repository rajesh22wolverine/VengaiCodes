import { createSlice, createAsyncThunk, PayloadAction } from "@reduxjs/toolkit";
import apiClient from "@/lib/api";

// ═══════════════════════════════════════════════════════════════
//  Types — mirror apps/backend/app/schemas/auth.py UserResponse
// ═══════════════════════════════════════════════════════════════
export interface User {
  id: string;
  full_name: string;
  username: string;
  email: string;
  mobile?: string | null;
  avatar_url?: string | null;
  tier: "free" | "creator" | "professional" | "studio" | "wl_basic" | "wl_pro" | "wl_full";
  is_admin: boolean;
  is_vip: boolean;
  projects_used: number;
  projects_limit: number;
  projects_remaining: number;
  ai_tokens_used: number;
  ai_tokens_limit: number;
  ai_tokens_remaining: number;
  email_verified: boolean;
  mobile_verified: boolean;
  govt_id_verified: boolean;
  biometric_verified: boolean;
  verification_status: string;
  is_seller: boolean;
  seller_verified: boolean;
  seller_rating: number;
  total_apps_sold: number;
  has_custom_voice: boolean;
  has_custom_character: boolean;
  character_name?: string | null;
  revenue_sharing_agreed: boolean;
  status: string;
  restriction_level: string;
  created_at: string;
  last_login?: string | null;
  preferences: Record<string, unknown>;
}

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  error: string | null;
  otpSent: boolean;
  otpTarget: string | null;
  otpType: "email" | "mobile" | null;
  otpPurpose:
    | "login"
    | "signup"
    | "verify"
    | "password_reset"
    | "licence_recovery"
    | null;
}

const initialState: AuthState = {
  user: null,
  isAuthenticated: false,
  isLoading: false,
  error: null,
  otpSent: false,
  otpTarget: null,
  otpType: null,
  otpPurpose: null,
};

// ═══════════════════════════════════════════════════════════════
//  Async Thunks — call FastAPI backend via apiClient
// ═══════════════════════════════════════════════════════════════

/**
 * Login — POST /auth/login
 * Backend: LoginRequest -> LoginResponse
 */
export const loginUser = createAsyncThunk(
  "auth/login",
  async (
    {
      usernameOrEmail,
      password,
      rememberMe = false,
    }: { usernameOrEmail: string; password: string; rememberMe?: boolean },
    { rejectWithValue }
  ) => {
    try {
      const { data } = await apiClient.post("/auth/login", {
        username_or_email: usernameOrEmail,
        password,
        remember_me: rememberMe,
      });
      // data: { success, message, access_token, refresh_token, expires_in, user, ... }
      localStorage.setItem("vengaicode_token", data.access_token);
      localStorage.setItem("vengaicode_refresh_token", data.refresh_token);
      return data.user as User;
    } catch (error: any) {
      return rejectWithValue(error.message || "Login failed");
    }
  }
);

/**
 * Signup — POST /auth/signup
 * Backend: SignupRequest -> SignupResponse
 * Note: Does NOT return tokens. Returns { user_id, next_step, otp_sent_to }.
 * Caller (SignupScreen) navigates to /otp with the returned info.
 */
export const signupUser = createAsyncThunk(
  "auth/signup",
  async (
    data: {
      fullName: string;
      email: string;
      mobile: string;
      username: string;
      password: string;
    },
    { rejectWithValue }
  ) => {
    try {
      const { data: res } = await apiClient.post("/auth/signup", {
        full_name: data.fullName,
        username: data.username,
        email: data.email,
        mobile: data.mobile,
        password: data.password,
        confirm_password: data.password,
        agree_to_terms: true,
      });
      // res: { success, message, user_id, next_step, otp_sent_to }
      return res as {
        success: boolean;
        message: string;
        user_id: string;
        next_step: string;
        otp_sent_to: string;
      };
    } catch (error: any) {
      return rejectWithValue(error.message || "Signup failed");
    }
  }
);

/**
 * Send OTP — POST /auth/send-otp
 * Backend: SendOTPRequest -> SendOTPResponse
 */
export const sendOTP = createAsyncThunk(
  "auth/sendOTP",
  async (
    {
      target,
      type,
      purpose = "login",
    }: {
      target: string;
      type: "email" | "mobile";
      purpose?: "login" | "signup" | "verify" | "password_reset" | "licence_recovery";
    },
    { rejectWithValue }
  ) => {
    try {
      const { data } = await apiClient.post("/auth/send-otp", {
        target,
        otp_type: type,
        purpose,
      });
      // data: { success, message, otp_sent_to, expires_in_minutes, resend_after_seconds }
      return { target, type, purpose, otpSentTo: data.otp_sent_to as string };
    } catch (error: any) {
      return rejectWithValue(error.message || "Failed to send OTP");
    }
  }
);

/**
 * Verify OTP — POST /auth/verify-otp
 * Backend: VerifyOTPRequest -> VerifyOTPResponse
 * On success for signup/verify/login purposes, returns tokens + user.
 * On success for password_reset/licence_recovery, returns only verified:true.
 */
export const verifyOTP = createAsyncThunk(
  "auth/verifyOTP",
  async (
    {
      target,
      otp,
      type,
      purpose = "signup",
    }: {
      target: string;
      otp: string;
      type: "email" | "mobile";
      purpose?: "login" | "signup" | "verify" | "password_reset" | "licence_recovery";
    },
    { rejectWithValue }
  ) => {
    try {
      const { data } = await apiClient.post("/auth/verify-otp", {
        target,
        otp,
        otp_type: type,
        purpose,
      });
      // data: { success, message, verified, access_token?, refresh_token?, expires_in?, user? }
      if (data.access_token) {
        localStorage.setItem("vengaicode_token", data.access_token);
        localStorage.setItem("vengaicode_refresh_token", data.refresh_token);
      }
      return data as {
        success: boolean;
        message: string;
        verified: boolean;
        access_token?: string;
        refresh_token?: string;
        expires_in?: number;
        user?: User;
      };
    } catch (error: any) {
      return rejectWithValue(error.message || "OTP verification failed");
    }
  }
);

/**
 * Forgot Password — POST /auth/forgot-password
 */
export const forgotPassword = createAsyncThunk(
  "auth/forgotPassword",
  async ({ email }: { email: string }, { rejectWithValue }) => {
    try {
      const { data } = await apiClient.post("/auth/forgot-password", { email });
      return { otpSentTo: data.otp_sent_to as string };
    } catch (error: any) {
      return rejectWithValue(error.message || "Failed to send reset code");
    }
  }
);

/**
 * Reset Password — POST /auth/reset-password
 */
export const resetPassword = createAsyncThunk(
  "auth/resetPassword",
  async (
    {
      email,
      otp,
      newPassword,
    }: { email: string; otp: string; newPassword: string },
    { rejectWithValue }
  ) => {
    try {
      const { data } = await apiClient.post("/auth/reset-password", {
        email,
        otp,
        new_password: newPassword,
        confirm_new_password: newPassword,
      });
      return data;
    } catch (error: any) {
      return rejectWithValue(error.message || "Failed to reset password");
    }
  }
);

/**
 * Verify Session — GET /auth/verify-session
 * Called on app startup to restore session from stored token.
 */
export const checkSession = createAsyncThunk(
  "auth/checkSession",
  async (_, { rejectWithValue }) => {
    try {
      const token = localStorage.getItem("vengaicode_token");
      if (!token) throw new Error("No session found");

      const { data } = await apiClient.get("/auth/verify-session");
      // data: { success, valid, user }
      if (!data.valid || !data.user) throw new Error("Session invalid");
      return data.user as User;
    } catch (error: any) {
      localStorage.removeItem("vengaicode_token");
      localStorage.removeItem("vengaicode_refresh_token");
      return rejectWithValue(error.message || "Session expired");
    }
  }
);

/**
 * Logout — POST /auth/logout
 */
export const logoutUser = createAsyncThunk("auth/logout", async () => {
  try {
    await apiClient.post("/auth/logout");
  } catch {
    // Ignore errors — clear local session regardless
  } finally {
    localStorage.removeItem("vengaicode_token");
    localStorage.removeItem("vengaicode_refresh_token");
  }
});

// ═══════════════════════════════════════════════════════════════
//  Slice
// ═══════════════════════════════════════════════════════════════
const authSlice = createSlice({
  name: "auth",
  initialState,
  reducers: {
    clearError: (state) => {
      state.error = null;
    },
    clearOTPState: (state) => {
      state.otpSent = false;
      state.otpTarget = null;
      state.otpType = null;
      state.otpPurpose = null;
    },
    updateUser: (state, action: PayloadAction<Partial<User>>) => {
      if (state.user) {
        state.user = { ...state.user, ...action.payload };
      }
    },
  },
  extraReducers: (builder) => {
    // ── Login ──
    builder
      .addCase(loginUser.pending, (state) => {
        state.isLoading = true;
        state.error = null;
      })
      .addCase(loginUser.fulfilled, (state, action) => {
        state.isLoading = false;
        state.user = action.payload;
        state.isAuthenticated = true;
      })
      .addCase(loginUser.rejected, (state, action) => {
        state.isLoading = false;
        state.error = action.payload as string;
      });

    // ── Signup ──
    builder
      .addCase(signupUser.pending, (state) => {
        state.isLoading = true;
        state.error = null;
      })
      .addCase(signupUser.fulfilled, (state) => {
        state.isLoading = false;
        // No tokens yet — user must verify OTP next
      })
      .addCase(signupUser.rejected, (state, action) => {
        state.isLoading = false;
        state.error = action.payload as string;
      });

    // ── Send OTP ──
    builder
      .addCase(sendOTP.pending, (state) => {
        state.isLoading = true;
        state.error = null;
      })
      .addCase(sendOTP.fulfilled, (state, action) => {
        state.isLoading = false;
        state.otpSent = true;
        state.otpTarget = action.payload.target;
        state.otpType = action.payload.type;
        state.otpPurpose = action.payload.purpose;
      })
      .addCase(sendOTP.rejected, (state, action) => {
        state.isLoading = false;
        state.error = action.payload as string;
      });

    // ── Verify OTP ──
    builder
      .addCase(verifyOTP.pending, (state) => {
        state.isLoading = true;
        state.error = null;
      })
      .addCase(verifyOTP.fulfilled, (state, action) => {
        state.isLoading = false;
        if (action.payload.user) {
          state.user = action.payload.user;
          state.isAuthenticated = true;
        }
        state.otpSent = false;
      })
      .addCase(verifyOTP.rejected, (state, action) => {
        state.isLoading = false;
        state.error = action.payload as string;
      });

    // ── Forgot Password ──
    builder
      .addCase(forgotPassword.pending, (state) => {
        state.isLoading = true;
        state.error = null;
      })
      .addCase(forgotPassword.fulfilled, (state) => {
        state.isLoading = false;
        state.otpSent = true;
        state.otpPurpose = "password_reset";
      })
      .addCase(forgotPassword.rejected, (state, action) => {
        state.isLoading = false;
        state.error = action.payload as string;
      });

    // ── Reset Password ──
    builder
      .addCase(resetPassword.pending, (state) => {
        state.isLoading = true;
        state.error = null;
      })
      .addCase(resetPassword.fulfilled, (state) => {
        state.isLoading = false;
        state.otpSent = false;
        state.otpPurpose = null;
      })
      .addCase(resetPassword.rejected, (state, action) => {
        state.isLoading = false;
        state.error = action.payload as string;
      });

    // ── Check Session ──
    builder
      .addCase(checkSession.pending, (state) => {
        state.isLoading = true;
      })
      .addCase(checkSession.fulfilled, (state, action) => {
        state.isLoading = false;
        state.user = action.payload;
        state.isAuthenticated = true;
      })
      .addCase(checkSession.rejected, (state) => {
        state.isLoading = false;
        state.user = null;
        state.isAuthenticated = false;
      });

    // ── Logout ──
    builder.addCase(logoutUser.fulfilled, (state) => {
      state.user = null;
      state.isAuthenticated = false;
      state.error = null;
      state.otpSent = false;
      state.otpTarget = null;
      state.otpType = null;
      state.otpPurpose = null;
    });
  },
});

export const { clearError, clearOTPState, updateUser } = authSlice.actions;
export default authSlice.reducer;
