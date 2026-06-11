import { createSlice, PayloadAction } from "@reduxjs/toolkit";
 
interface UIState {
  theme: "light" | "dark";
  sidebarCollapsed: boolean;
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
}
 
const initialState: UIState = {
  theme: "dark",
  sidebarCollapsed: false,
  isFirstLaunch: !localStorage.getItem("vengaicode_onboarded"),
  activeTab: "create",
  isLoading: false,
  loadingMessage: "",
  tigerExpression: "idle",
  showSystemScanPermission: false,
  systemScanCompleted: !!localStorage.getItem("vengaicode_system_scanned"),
};
 
const uiSlice = createSlice({
  name: "ui",
  initialState,
  reducers: {
    setTheme: (state, action: PayloadAction<"light" | "dark">) => {
      state.theme = action.payload;
      localStorage.setItem("vengaicode-theme", action.payload);
    },
    toggleTheme: (state) => {
      state.theme = state.theme === "light" ? "dark" : "light";
      localStorage.setItem("vengaicode-theme", state.theme);
    },
    toggleSidebar: (state) => {
      state.sidebarCollapsed = !state.sidebarCollapsed;
    },
    setSidebarCollapsed: (state, action: PayloadAction<boolean>) => {
      state.sidebarCollapsed = action.payload;
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
      localStorage.setItem("vengaicode_onboarded", "true");
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
      localStorage.setItem("vengaicode_system_scanned", "true");
    },
  },
});
 
export const {
  setTheme,
  toggleTheme,
  toggleSidebar,
  setSidebarCollapsed,
  setActiveTab,
  setLoading,
  setTigerExpression,
  completeOnboarding,
  showSystemScan,
  hideSystemScan,
  completeSystemScan,
} = uiSlice.actions;
 
export default uiSlice.reducer;