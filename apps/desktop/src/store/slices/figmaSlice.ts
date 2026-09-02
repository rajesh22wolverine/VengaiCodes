import { createSlice, createAsyncThunk, PayloadAction } from "@reduxjs/toolkit";
import apiClient from "@/lib/api";

// ─── Figma connection — mirrors backend FigmaConnectionResponse ───
interface FigmaConnectionState {
  connected: boolean;
  figmaHandle: string | null;
  isLoading: boolean;
  isSaving: boolean;
  error: string | null;
}

const initialState: FigmaConnectionState = {
  connected: false,
  figmaHandle: null,
  isLoading: false,
  isSaving: false,
  error: null,
};

interface ConnectionPayload {
  connected: boolean;
  figma_handle: string | null;
}

/** GET /figma/connection */
export const fetchFigmaStatus = createAsyncThunk(
  "figma/fetchStatus",
  async (_: void, { rejectWithValue }) => {
    try {
      const { data } = await apiClient.get("/figma/connection");
      return data as ConnectionPayload;
    } catch (error: any) {
      return rejectWithValue(error.message || "Failed to load Figma connection status");
    }
  }
);

/** POST /figma/connection */
export const connectFigma = createAsyncThunk(
  "figma/connect",
  async (token: string, { rejectWithValue }) => {
    try {
      const { data } = await apiClient.post("/figma/connection", { token });
      return data as ConnectionPayload;
    } catch (error: any) {
      return rejectWithValue(error.message || "Failed to connect Figma account");
    }
  }
);

/** DELETE /figma/connection */
export const disconnectFigma = createAsyncThunk(
  "figma/disconnect",
  async (_: void, { rejectWithValue }) => {
    try {
      await apiClient.delete("/figma/connection");
    } catch (error: any) {
      return rejectWithValue(error.message || "Failed to disconnect Figma account");
    }
  }
);

const figmaSlice = createSlice({
  name: "figma",
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchFigmaStatus.pending, (state) => {
        state.isLoading = true;
        state.error = null;
      })
      .addCase(fetchFigmaStatus.fulfilled, (state, action: PayloadAction<ConnectionPayload>) => {
        state.isLoading = false;
        state.connected = action.payload.connected;
        state.figmaHandle = action.payload.figma_handle;
      })
      .addCase(fetchFigmaStatus.rejected, (state, action) => {
        state.isLoading = false;
        state.error = action.payload as string;
      })
      .addCase(connectFigma.pending, (state) => {
        state.isSaving = true;
        state.error = null;
      })
      .addCase(connectFigma.fulfilled, (state, action: PayloadAction<ConnectionPayload>) => {
        state.isSaving = false;
        state.connected = action.payload.connected;
        state.figmaHandle = action.payload.figma_handle;
      })
      .addCase(connectFigma.rejected, (state, action) => {
        state.isSaving = false;
        state.error = action.payload as string;
      })
      .addCase(disconnectFigma.fulfilled, (state) => {
        state.connected = false;
        state.figmaHandle = null;
      });
  },
});

export default figmaSlice.reducer;
