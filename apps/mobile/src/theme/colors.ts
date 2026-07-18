export interface ThemeColors {
  background: string;
  surface: string;
  textPrimary: string;
  textSecondary: string;
  textTertiary: string;
  border: string;
  primary: string;
  primaryLight: string;
  error: string;
  success: string;
}

const dark: ThemeColors = {
  background: "#0f1115",
  surface: "#1a1d24",
  textPrimary: "#f5f5f7",
  textSecondary: "#a1a1aa",
  textTertiary: "#71717a",
  border: "#2a2d36",
  primary: "#f97316",
  primaryLight: "#f9731633",
  error: "#ef4444",
  success: "#22c55e",
};

const light: ThemeColors = {
  background: "#ffffff",
  surface: "#f8f9fb",
  textPrimary: "#18181b",
  textSecondary: "#52525b",
  textTertiary: "#a1a1aa",
  border: "#e4e4e7",
  primary: "#f97316",
  primaryLight: "#f9731622",
  error: "#dc2626",
  success: "#16a34a",
};

export function getColors(theme: "light" | "dark"): ThemeColors {
  return theme === "dark" ? dark : light;
}
