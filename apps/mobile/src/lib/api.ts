import axios, { AxiosError, AxiosInstance, InternalAxiosRequestConfig } from "axios";
import { clearTokens, getAccessToken } from "@/lib/storage";

// ─── Base URL ───
// Points to the FastAPI backend (apps/backend). Override for local dev via
// EXPO_PUBLIC_API_URL (e.g. http://<lan-ip>:8000 when running the backend locally —
// localhost does not resolve to the host machine from a physical device/emulator).
const API_BASE_URL = process.env.EXPO_PUBLIC_API_URL || "https://vengaicode-backend.onrender.com";

const API_V1_PREFIX = "/api/v1";

export const apiClient: AxiosInstance = axios.create({
  baseURL: `${API_BASE_URL}${API_V1_PREFIX}`,
  headers: {
    "Content-Type": "application/json",
  },
  timeout: 30000,
});

// ─── Request interceptor — attach access token ───
apiClient.interceptors.request.use(async (config: InternalAxiosRequestConfig) => {
  const token = await getAccessToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// ─── Response interceptor — normalize error messages ───
// FastAPI returns errors as either:
//   { "detail": "message" }                          — HTTPException
//   { "success": false, "message": "...", "errors": [...] }  — validation errors (main.py handler)
apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError<any>) => {
    const data = error.response?.data;

    let message = "Something went wrong. Baby Tiger is investigating! 🐯🔍";

    if (data) {
      if (typeof data.detail === "string") {
        message = data.detail;
      } else if (typeof data.message === "string") {
        message = data.message;
        if (Array.isArray(data.errors) && data.errors.length > 0) {
          const first = data.errors[0];
          message = `${first.field}: ${first.message}`;
        }
      }
    } else if (error.code === "ECONNABORTED") {
      message = "Request timed out. Please check your connection.";
    } else if (error.message === "Network Error") {
      message = "Cannot reach VengaiCode backend. Is it running?";
    }

    if (error.response?.status === 401) {
      await clearTokens();
    }

    return Promise.reject(new Error(message));
  }
);

export default apiClient;
