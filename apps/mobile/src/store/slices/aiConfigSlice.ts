import { createSlice, createAsyncThunk, PayloadAction } from "@reduxjs/toolkit";
import apiClient from "@/lib/api";

// ─── BYO AI Model Config — mirrors backend UserAIConfig / AIConfigResponse ───
export type AIProviderType = "groq" | "openai" | "anthropic" | "custom";
export type AIConfigPriority = "primary" | "secondary" | "tertiary";

export interface AIConfig {
  id: string;
  provider_type: AIProviderType;
  base_url: string;
  has_api_key: boolean;
  model_name: string;
  label: string;
  is_active: boolean;
  priority: AIConfigPriority | null;
  created_at: string;
  updated_at: string;
}

export interface CreateAIConfigInput {
  provider_type: AIProviderType;
  base_url?: string;
  api_key?: string;
  model_name: string;
  label: string;
  is_active?: boolean;
  priority?: AIConfigPriority;
}

interface AIConfigState {
  configs: AIConfig[];
  isLoading: boolean;
  isSaving: boolean;
  error: string | null;
}

const initialState: AIConfigState = {
  configs: [],
  isLoading: false,
  isSaving: false,
  error: null,
};

/** GET /ai/configs */
export const fetchAIConfigs = createAsyncThunk(
  "aiConfig/fetch",
  async (_: void, { rejectWithValue }) => {
    try {
      const { data } = await apiClient.get("/ai/configs");
      return data.configs as AIConfig[];
    } catch (error: any) {
      return rejectWithValue(error.message || "Failed to load AI models");
    }
  }
);

/** POST /ai/configs */
export const createAIConfig = createAsyncThunk(
  "aiConfig/create",
  async (payload: CreateAIConfigInput, { rejectWithValue }) => {
    try {
      const { data } = await apiClient.post("/ai/configs", payload);
      return data.config as AIConfig;
    } catch (error: any) {
      return rejectWithValue(error.message || "Failed to save AI model");
    }
  }
);

/** PATCH /ai/configs/{id} — set a saved config active */
export const setActiveAIConfig = createAsyncThunk(
  "aiConfig/setActive",
  async (id: string, { rejectWithValue }) => {
    try {
      const { data } = await apiClient.patch(`/ai/configs/${id}`, { is_active: true });
      return data.config as AIConfig;
    } catch (error: any) {
      return rejectWithValue(error.message || "Failed to switch AI model");
    }
  }
);

/** PATCH /ai/configs/{id} — deactivate, falling back to VengaiCode's default AI */
export const useDefaultAI = createAsyncThunk(
  "aiConfig/useDefault",
  async (activeId: string | undefined, { rejectWithValue }) => {
    try {
      if (activeId) {
        await apiClient.patch(`/ai/configs/${activeId}`, { is_active: false });
      }
      return true;
    } catch (error: any) {
      return rejectWithValue(error.message || "Failed to switch to default AI");
    }
  }
);

/** PATCH /ai/configs/{id} — assign or clear a config's fallback-chain slot */
export const setConfigPriority = createAsyncThunk(
  "aiConfig/setPriority",
  async (
    { id, priority }: { id: string; priority: AIConfigPriority | null },
    { rejectWithValue }
  ) => {
    try {
      const body = priority ? { priority } : { clear_priority: true };
      const { data } = await apiClient.patch(`/ai/configs/${id}`, body);
      return data.config as AIConfig;
    } catch (error: any) {
      return rejectWithValue(error.message || "Failed to update fallback order");
    }
  }
);

/** DELETE /ai/configs/{id} */
export const deleteAIConfig = createAsyncThunk(
  "aiConfig/delete",
  async (id: string, { rejectWithValue }) => {
    try {
      await apiClient.delete(`/ai/configs/${id}`);
      return id;
    } catch (error: any) {
      return rejectWithValue(error.message || "Failed to delete AI model");
    }
  }
);

const aiConfigSlice = createSlice({
  name: "aiConfig",
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchAIConfigs.pending, (state) => {
        state.isLoading = true;
        state.error = null;
      })
      .addCase(fetchAIConfigs.fulfilled, (state, action: PayloadAction<AIConfig[]>) => {
        state.isLoading = false;
        state.configs = action.payload;
      })
      .addCase(fetchAIConfigs.rejected, (state, action) => {
        state.isLoading = false;
        state.error = action.payload as string;
      })
      .addCase(createAIConfig.pending, (state) => {
        state.isSaving = true;
        state.error = null;
      })
      .addCase(createAIConfig.fulfilled, (state, action: PayloadAction<AIConfig>) => {
        state.isSaving = false;
        state.configs = state.configs.map((c) => ({
          ...c,
          is_active: action.payload.is_active ? false : c.is_active,
          priority: action.payload.priority && c.priority === action.payload.priority ? null : c.priority,
        }));
        state.configs.unshift(action.payload);
      })
      .addCase(createAIConfig.rejected, (state, action) => {
        state.isSaving = false;
        state.error = action.payload as string;
      })
      .addCase(setActiveAIConfig.fulfilled, (state, action: PayloadAction<AIConfig>) => {
        state.configs = state.configs.map((c) => ({
          ...c,
          is_active: c.id === action.payload.id,
        }));
      })
      .addCase(setConfigPriority.fulfilled, (state, action: PayloadAction<AIConfig>) => {
        state.configs = state.configs.map((c) => {
          if (c.id === action.payload.id) return action.payload;
          if (action.payload.priority && c.priority === action.payload.priority) {
            return { ...c, priority: null };
          }
          return c;
        });
      })
      .addCase(useDefaultAI.fulfilled, (state) => {
        state.configs = state.configs.map((c) => ({ ...c, is_active: false }));
      })
      .addCase(deleteAIConfig.fulfilled, (state, action: PayloadAction<string>) => {
        state.configs = state.configs.filter((c) => c.id !== action.payload);
      });
  },
});

export default aiConfigSlice.reducer;
