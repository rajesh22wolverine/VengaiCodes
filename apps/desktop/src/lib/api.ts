import axios, { AxiosError, AxiosInstance, InternalAxiosRequestConfig } from "axios";

// ─── Base URL ───
// Points to the FastAPI backend (apps/backend).
// In Tauri production builds this should be overridden via VITE_API_URL
// to point at the deployed Render backend.
export const API_BASE_URL =
  (import.meta.env.VITE_API_URL as string | undefined) || "http://localhost:8000";

// Local/portable AI models (Settings -> AI Model) are launched on this same
// machine and saved with a 127.0.0.1 base_url. That's only reachable by a
// backend running on this same machine too — a remote-hosted backend (e.g.
// the deployed Render instance) can never reach it, since 127.0.0.1 from
// its side means its own container, not this PC. Used to warn users on a
// remote backend before they configure something that can never work.
export const IS_LOCAL_BACKEND = /^https?:\/\/(localhost|127\.0\.0\.1)(:|\/|$)/i.test(
  API_BASE_URL
);

const API_V1_PREFIX = "/api/v1";

export const apiClient: AxiosInstance = axios.create({
  baseURL: `${API_BASE_URL}${API_V1_PREFIX}`,
  headers: {
    "Content-Type": "application/json",
  },
  timeout: 30000,
});

// ─── Request interceptor — attach access token ───
apiClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = localStorage.getItem("vengaicode_token");
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
  (error: AxiosError<any>) => {
    const data = error.response?.data;

    let message = "Something went wrong. Baby Tiger is investigating! 🐯🔍";

    if (data) {
      if (typeof data.detail === "string") {
        message = data.detail;
      } else if (typeof data.message === "string") {
        message = data.message;
        if (Array.isArray(data.errors) && data.errors.length > 0) {
          // Append first field error for clarity
          const first = data.errors[0];
          message = `${first.field}: ${first.message}`;
        }
      }
    } else if (error.code === "ECONNABORTED") {
      message = "Request timed out. Please check your connection.";
    } else if (error.message === "Network Error") {
      message = "Cannot reach VengaiCode backend. Is it running?";
    }

    // Attach normalized message so thunks can read error.message
    return Promise.reject(new Error(message));
  }
);

export default apiClient;
