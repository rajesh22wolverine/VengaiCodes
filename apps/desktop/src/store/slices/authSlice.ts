import { createSlice, createAsyncThunk, PayloadAction } from "@reduxjs/toolkit";
import { invoke } from "@tauri-apps/api/tauri";
 
// Types
export interface User {
  id: string;
  username: string;
  email: string;
  mobile: string;
  fullName: string;
  avatar?: string;
  tier: "free" | "creator" | "professional" | "studio" | "enterprise";
  isVip: boolean;
  projectsUsed: number;
  projectsLimit: number;
  createdAt: string;
}
 
interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  error: string | null;
  otpSent: boolean;
  otpTarget: string | null;
  otpType: "email" | "mobile" | null;
  passwordResetRequested: boolean;
}
 
const initialState: AuthState = {
  user: null,
  isAuthenticated: false,
  isLoading: false,
  error: null,
  otpSent: false,
  otpTarget: null,
  otpType: null,
  passwordResetRequested: false,
};
 
// Async thunks
export const loginUser = createAsyncThunk(
  "auth/login",
  async ({ username, password }: { username: string; password: string }, { rejectWithValue }) => {
    try {
      const result = await invoke<{ user: User; token: string }>("login", { username, password });
      // Save token to secure storage
      localStorage.setItem("vengaicode_token", result.token);
      return result.user;
    } catch (error: any) {
      return rejectWithValue(error.message || "Login failed");
    }
  }
);
 
export const signupUser = createAsyncThunk(
  "auth/signup",
  async (
    data: { fullName: string; email: string; mobile: string; username: string; password: string },
    { rejectWithValue }
  ) => {
    try {
      const result = await invoke<{ userId: string; message: string }>("signup", data);
      return result;
    } catch (error: any) {
      return rejectWithValue(error.message || "Signup failed");
    }
  }
);
 
export const sendOTP = createAsyncThunk(
  "auth/sendOTP",
  async (
    { target, type }: { target: string; type: "email" | "mobile" },
    { rejectWithValue }
  ) => {
    try {
      await invoke("send_otp", { target, otpType: type });
      return { target, type };
    } catch (error: any) {
      return rejectWithValue(error.message || "Failed to send OTP");
    }
  }
);
 
export const verifyOTP = createAsyncThunk(
  "auth/verifyOTP",
  async (
    { target, otp, type }: { target: string; otp: string; type: "email" | "mobile" },
    { rejectWithValue }
  ) => {
    try {
      const result = await invoke<{ verified: boolean; token?: string; user?: User }>(
        "verify_otp",
        { target, otp, otpType: type }
      );
      if (result.token) {
        localStorage.setItem("vengaicode_token", result.token);
      }
      return result;
    } catch (error: any) {
      return rejectWithValue(error.message || "OTP verification failed");
    }
  }
);
 
export const checkSession = createAsyncThunk(
  "auth/checkSession",
  async (_, { rejectWithValue }) => {
    try {
      const token = localStorage.getItem("vengaicode_token");
      if (!token) throw new Error("No session found");
      const user = await invoke<User>("verify_session", { token });
      return user;
    } catch (error: any) {
      localStorage.removeItem("vengaicode_token");
      return rejectWithValue(error.message || "Session expired");
    }
  }
);
 
export const logoutUser = createAsyncThunk("auth/logout", async () => {
  localStorage.removeItem("vengaicode_token");
  await invoke("logout").catch(() => {});
});
 
// Slice
const authSlice = createSlice({
  name: "auth",
  initialState,
  reducers: {
    clearError: (state) => { state.error = null; },
    clearOTPState: (state) => {
      state.otpSent = false;
      state.otpTarget = null;
      state.otpType = null;
    },
    updateUser: (state, action: PayloadAction<Partial<User>>) => {
      if (state.user) {
        state.user = { ...state.user, ...action.payload };
      }
    },
  },
  extraReducers: (builder) => {
    // Login
    builder
      .addCase(loginUser.pending, (state) => { state.isLoading = true; state.error = null; })
      .addCase(loginUser.fulfilled, (state, action) => {
        state.isLoading = false;
        state.user = action.payload;
        state.isAuthenticated = true;
      })
      .addCase(loginUser.rejected, (state, action) => {
        state.isLoading = false;
        state.error = action.payload as string;
      });
 
    // Signup
    builder
      .addCase(signupUser.pending, (state) => { state.isLoading = true; state.error = null; })
      .addCase(signupUser.fulfilled, (state) => { state.isLoading = false; })
      .addCase(signupUser.rejected, (state, action) => {
        state.isLoading = false;
        state.error = action.payload as string;
      });
 
    // Send OTP
    builder
      .addCase(sendOTP.pending, (state) => { state.isLoading = true; state.error = null; })
      .addCase(sendOTP.fulfilled, (state, action) => {
        state.isLoading = false;
        state.otpSent = true;
        state.otpTarget = action.payload.target;
        state.otpType = action.payload.type;
      })
      .addCase(sendOTP.rejected, (state, action) => {
        state.isLoading = false;
        state.error = action.payload as string;
      });
 
    // Verify OTP
    builder
      .addCase(verifyOTP.pending, (state) => { state.isLoading = true; state.error = null; })
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
 
    // Check Session
    builder
      .addCase(checkSession.fulfilled, (state, action) => {
        state.user = action.payload;
        state.isAuthenticated = true;
      })
      .addCase(checkSession.rejected, (state) => {
        state.user = null;
        state.isAuthenticated = false;
      });
 
    // Logout
    builder.addCase(logoutUser.fulfilled, (state) => {
      state.user = null;
      state.isAuthenticated = false;
      state.error = null;
    });
  },
});
 
export const { clearError, clearOTPState, updateUser } = authSlice.actions;
export default authSlice.reducer;