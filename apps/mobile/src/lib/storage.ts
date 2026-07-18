import * as SecureStore from "expo-secure-store";
import AsyncStorage from "@react-native-async-storage/async-storage";

// ─── Tokens — expo-secure-store (encrypted, replaces web's localStorage) ───
const ACCESS_TOKEN_KEY = "vengaicode_token";
const REFRESH_TOKEN_KEY = "vengaicode_refresh_token";

export async function getAccessToken(): Promise<string | null> {
  return SecureStore.getItemAsync(ACCESS_TOKEN_KEY);
}

export async function setTokens(accessToken: string, refreshToken: string): Promise<void> {
  await SecureStore.setItemAsync(ACCESS_TOKEN_KEY, accessToken);
  await SecureStore.setItemAsync(REFRESH_TOKEN_KEY, refreshToken);
}

export async function clearTokens(): Promise<void> {
  await SecureStore.deleteItemAsync(ACCESS_TOKEN_KEY);
  await SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY);
}

// ─── UI flags/preferences — AsyncStorage (replaces web's localStorage) ───
const THEME_KEY = "vengaicode-theme";
const ONBOARDED_KEY = "vengaicode_onboarded";
const SYSTEM_SCANNED_KEY = "vengaicode_system_scanned";

export async function getStoredTheme(): Promise<"light" | "dark" | null> {
  const value = await AsyncStorage.getItem(THEME_KEY);
  return value === "light" || value === "dark" ? value : null;
}

export async function setStoredTheme(theme: "light" | "dark"): Promise<void> {
  await AsyncStorage.setItem(THEME_KEY, theme);
}

export async function getIsOnboarded(): Promise<boolean> {
  return (await AsyncStorage.getItem(ONBOARDED_KEY)) != null;
}

export async function setOnboarded(): Promise<void> {
  await AsyncStorage.setItem(ONBOARDED_KEY, "true");
}

export async function getSystemScanned(): Promise<boolean> {
  return (await AsyncStorage.getItem(SYSTEM_SCANNED_KEY)) != null;
}

export async function setSystemScanned(): Promise<void> {
  await AsyncStorage.setItem(SYSTEM_SCANNED_KEY, "true");
}
