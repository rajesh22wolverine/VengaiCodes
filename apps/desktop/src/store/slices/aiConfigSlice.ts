import { createSlice, createAsyncThunk, PayloadAction } from "@reduxjs/toolkit";
import apiClient from "@/lib/api";

// ─── BYO AI Model Config — mirrors backend UserAIConfig / AIConfigResponse ───
export type AIProviderType = "groq" | "openai" | "anthropic" | "custom" | "portable";
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

// ─── Bag — the merged, ordered view of platform defaults + this user's
// own configs that app.ai.orchestrator.get_effective_bag() assembles and
// generate_text() walks through. Supersedes `priority` above. ───
export interface BagConfig extends AIConfig {
  is_platform_default: boolean;
  order_index: number | null;
}

interface AIConfigState {
  configs: AIConfig[];
  isLoading: boolean;
  isSaving: boolean;
  error: string | null;
  bag: BagConfig[];
  isBagLoading: boolean;
  isBagSaving: boolean;
}

const initialState: AIConfigState = {
  configs: [],
  isLoading: false,
  isSaving: false,
  error: null,
  bag: [],
  isBagLoading: false,
  isBagSaving: false,
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

/** GET /ai/configs/bag — the merged, ordered bag (platform defaults + own configs) */
export const fetchAIBag = createAsyncThunk(
  "aiConfig/fetchBag",
  async (_: void, { rejectWithValue }) => {
    try {
      const { data } = await apiClient.get("/ai/configs/bag");
      return data.bag as BagConfig[];
    } catch (error: any) {
      return rejectWithValue(error.message || "Failed to load AI model order");
    }
  }
);

/** PUT /ai/configs/bag-order — save a personal reorder of the bag */
export const setAIBagOrder = createAsyncThunk(
  "aiConfig/setBagOrder",
  async (order: string[], { rejectWithValue }) => {
    try {
      const { data } = await apiClient.put("/ai/configs/bag-order", { order });
      return data.bag as BagConfig[];
    } catch (error: any) {
      return rejectWithValue(error.message || "Failed to save the new order");
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
      .addCase(useDefaultAI.fulfilled, (state) => {
        state.configs = state.configs.map((c) => ({ ...c, is_active: false }));
      })
      .addCase(deleteAIConfig.fulfilled, (state, action: PayloadAction<string>) => {
        state.configs = state.configs.filter((c) => c.id !== action.payload);
        state.bag = state.bag.filter((c) => c.id !== action.payload);
      })
      .addCase(fetchAIBag.pending, (state) => {
        state.isBagLoading = true;
      })
      .addCase(fetchAIBag.fulfilled, (state, action: PayloadAction<BagConfig[]>) => {
        state.isBagLoading = false;
        state.bag = action.payload;
      })
      .addCase(fetchAIBag.rejected, (state, action) => {
        state.isBagLoading = false;
        state.error = action.payload as string;
      })
      .addCase(setAIBagOrder.pending, (state) => {
        state.isBagSaving = true;
      })
      .addCase(setAIBagOrder.fulfilled, (state, action: PayloadAction<BagConfig[]>) => {
        state.isBagSaving = false;
        state.bag = action.payload;
      })
      .addCase(setAIBagOrder.rejected, (state, action) => {
        state.isBagSaving = false;
        state.error = action.payload as string;
      });
  },
});

export default aiConfigSlice.reducer;
