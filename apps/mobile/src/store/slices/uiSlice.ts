import { createSlice, createAsyncThunk, PayloadAction } from "@reduxjs/toolkit";
import {
  getIsOnboarded,
  getStoredTheme,
  getSystemScanned,
  setOnboarded,
  setStoredTheme,
  setSystemScanned,
} from "@/lib/storage";

interface UIState {
  theme: "light" | "dark";
  isFirstLaunch: boolean;
  activeTab: "create" | "pending" | "completed";
  isLoading: boolean;
  loadingMessage: string;
  tigerExpression:
    | "idle"
    | "happy"
    | "sad"
    | "thinking"
    | "excited"
    | "coding"
    | "celebrating"
    | "investigating"
    | "serious"
    | "concerned"
    | "waving";
  showSystemScanPermission: boolean;
  systemScanCompleted: boolean;
  hydrated: boolean;
}

const initialState: UIState = {
  theme: "dark",
  // Defaults true until hydrateUI resolves (AsyncStorage is async, unlike web's localStorage) —
  // app/_layout.tsx awaits hydrateUI before routing so this never leaks into the UI.
  isFirstLaunch: true,
  activeTab: "create",
  isLoading: false,
  loadingMessage: "",
  tigerExpression: "idle",
  showSystemScanPermission: false,
  systemScanCompleted: false,
  hydrated: false,
};

/** Reads persisted theme/onboarding/system-scan flags from AsyncStorage on app start. */
export const hydrateUI = createAsyncThunk("ui/hydrate", async () => {
  const [theme, isOnboarded, systemScanned] = await Promise.all([
    getStoredTheme(),
    getIsOnboarded(),
    getSystemScanned(),
  ]);
  return {
    theme: theme ?? ("dark" as const),
    isFirstLaunch: !isOnboarded,
    systemScanCompleted: systemScanned,
  };
});

const uiSlice = createSlice({
  name: "ui",
  initialState,
  reducers: {
    setTheme: (state, action: PayloadAction<"light" | "dark">) => {
      state.theme = action.payload;
      setStoredTheme(action.payload);
    },
    toggleTheme: (state) => {
      state.theme = state.theme === "light" ? "dark" : "light";
      setStoredTheme(state.theme);
    },
    setActiveTab: (state, action: PayloadAction<"create" | "pending" | "completed">) => {
      state.activeTab = action.payload;
    },
    setLoading: (state, action: PayloadAction<{ isLoading: boolean; message?: string }>) => {
      state.isLoading = action.payload.isLoading;
      state.loadingMessage = action.payload.message || "";
    },
    setTigerExpression: (state, action: PayloadAction<UIState["tigerExpression"]>) => {
      state.tigerExpression = action.payload;
    },
    completeOnboarding: (state) => {
      state.isFirstLaunch = false;
      setOnboarded();
    },
    showSystemScan: (state) => {
      state.showSystemScanPermission = true;
    },
    hideSystemScan: (state) => {
      state.showSystemScanPermission = false;
    },
    completeSystemScan: (state) => {
      state.systemScanCompleted = true;
      state.showSystemScanPermission = false;
      setSystemScanned();
    },
  },
  extraReducers: (builder) => {
    builder.addCase(hydrateUI.fulfilled, (state, action) => {
      state.theme = action.payload.theme;
      state.isFirstLaunch = action.payload.isFirstLaunch;
      state.systemScanCompleted = action.payload.systemScanCompleted;
      state.hydrated = true;
    });
  },
});

export const {
  setTheme,
  toggleTheme,
  setActiveTab,
  setLoading,
  setTigerExpression,
  completeOnboarding,
  showSystemScan,
  hideSystemScan,
  completeSystemScan,
} = uiSlice.actions;

export default uiSlice.reducer;
