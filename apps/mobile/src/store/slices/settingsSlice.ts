import { createSlice, createAsyncThunk, PayloadAction } from "@reduxjs/toolkit";
import apiClient from "@/lib/api";

export interface UserPreferences {
  theme: "light" | "dark";
  language: string;
  notifications: {
    email: boolean;
    sms: boolean;
    push: boolean;
  };
  audio: {
    language: string;
    accent: string;
    voice: "male" | "female";
  };
}

const defaultPreferences: UserPreferences = {
  theme: "dark",
  language: "en",
  notifications: { email: true, sms: true, push: true },
  audio: { language: "en", accent: "indian", voice: "female" },
};

interface SettingsState {
  preferences: UserPreferences;
  isSaving: boolean;
  error: string | null;
}

const initialState: SettingsState = {
  preferences: defaultPreferences,
  isSaving: false,
  error: null,
};

/** PATCH /users/me/preferences */
export const updatePreferences = createAsyncThunk(
  "settings/updatePreferences",
  async (preferences: Partial<UserPreferences>, { rejectWithValue }) => {
    try {
      const { data } = await apiClient.patch("/users/me/preferences", preferences);
      return data.preferences as UserPreferences;
    } catch (error: any) {
      return rejectWithValue(error.message || "Failed to save settings");
    }
  }
);

const settingsSlice = createSlice({
  name: "settings",
  initialState,
  reducers: {
    setPreferences: (state, action: PayloadAction<Partial<UserPreferences>>) => {
      state.preferences = { ...state.preferences, ...action.payload };
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(updatePreferences.pending, (state) => {
        state.isSaving = true;
        state.error = null;
      })
      .addCase(updatePreferences.fulfilled, (state, action) => {
        state.isSaving = false;
        state.preferences = action.payload;
      })
      .addCase(updatePreferences.rejected, (state, action) => {
        state.isSaving = false;
        state.error = action.payload as string;
      });
  },
});

export const { setPreferences } = settingsSlice.actions;
export default settingsSlice.reducer;
