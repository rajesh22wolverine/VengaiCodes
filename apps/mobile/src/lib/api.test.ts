import { AxiosError, InternalAxiosRequestConfig } from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// storage.ts pulls in expo-secure-store and AsyncStorage, both of which need
// the native runtime. Mocking the module boundary keeps this suite in plain
// node with no Expo/Metro test stack.
const getAccessToken = vi.fn<[], Promise<string | null>>();
const clearTokens = vi.fn<[], Promise<void>>();

vi.mock("@/lib/storage", () => ({
  getAccessToken: () => getAccessToken(),
  clearTokens: () => clearTokens(),
  setTokens: vi.fn(),
}));

beforeEach(() => {
  getAccessToken.mockResolvedValue(null);
  clearTokens.mockResolvedValue(undefined);
});

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllEnvs();
  vi.resetModules();
});

async function loadApi(url?: string) {
  if (url === undefined) {
    vi.stubEnv("EXPO_PUBLIC_API_URL", "");
  } else {
    vi.stubEnv("EXPO_PUBLIC_API_URL", url);
  }
  vi.resetModules();
  return import("./api");
}

/** Make apiClient fail the way axios does, with `data` as the error body. */
function failWith(
  apiClient: { defaults: { adapter?: unknown } },
  data: unknown,
  status = 400,
  code?: string,
  message = "Request failed"
) {
  (apiClient.defaults as any).adapter = async (config: InternalAxiosRequestConfig) => {
    throw new AxiosError(
      message,
      code,
      config,
      null,
      data === undefined
        ? undefined
        : ({ data, status, statusText: "Error", headers: {}, config } as any)
    );
  };
}

describe("base URL", () => {
  it("defaults to the deployed Render backend, not localhost", () => {
    // Deliberately different from the desktop client, which defaults to
    // localhost. A phone has no useful "localhost", so shipping a build with
    // no env override must still reach a real backend.
    return loadApi().then(({ apiClient }) => {
      expect(apiClient.defaults.baseURL).toBe(
        "https://vengaicode-backend.onrender.com/api/v1"
      );
    });
  });

  it("honours EXPO_PUBLIC_API_URL for LAN development", async () => {
    const { apiClient } = await loadApi("http://192.168.1.50:8000");
    expect(apiClient.defaults.baseURL).toBe("http://192.168.1.50:8000/api/v1");
  });
});

describe("request interceptor", () => {
  it("attaches the token from secure storage", async () => {
    const { apiClient } = await loadApi("http://localhost:8000");
    getAccessToken.mockResolvedValue("tok-abc");

    let seen: string | undefined;
    apiClient.defaults.adapter = async (config) => {
      seen = config.headers?.Authorization as string | undefined;
      return { data: {}, status: 200, statusText: "OK", headers: {}, config } as any;
    };

    await apiClient.get("/whoami");
    expect(seen).toBe("Bearer tok-abc");
  });

  it("sends no Authorization header when there is no stored token", async () => {
    const { apiClient } = await loadApi("http://localhost:8000");

    let seen: string | undefined = "unset";
    apiClient.defaults.adapter = async (config) => {
      seen = config.headers?.Authorization as string | undefined;
      return { data: {}, status: 200, statusText: "OK", headers: {}, config } as any;
    };

    await apiClient.get("/whoami");
    expect(seen).toBeUndefined();
  });
});

describe("401 handling", () => {
  // Mobile-only behaviour with no desktop counterpart: an expired/revoked
  // token must be purged from secure storage, or the app retries forever
  // with a dead credential and can never get back to the login screen.
  it("clears stored tokens on a 401", async () => {
    const { apiClient } = await loadApi("http://localhost:8000");
    failWith(apiClient, { detail: "Not authenticated" }, 401);

    await expect(apiClient.get("/projects")).rejects.toThrow("Not authenticated");
    expect(clearTokens).toHaveBeenCalledTimes(1);
  });

  it("does NOT clear tokens on other error statuses", async () => {
    // A 500 or a validation error must not log the user out.
    const { apiClient } = await loadApi("http://localhost:8000");
    failWith(apiClient, { detail: "Server exploded" }, 500);

    await expect(apiClient.get("/projects")).rejects.toThrow("Server exploded");
    expect(clearTokens).not.toHaveBeenCalled();
  });

  it("does not clear tokens when the backend is simply unreachable", async () => {
    // Offline must not silently destroy the session.
    const { apiClient } = await loadApi("http://localhost:8000");
    failWith(apiClient, undefined, 0, undefined, "Network Error");

    await expect(apiClient.get("/projects")).rejects.toThrow(
      "Cannot reach VengaiCode backend. Is it running?"
    );
    expect(clearTokens).not.toHaveBeenCalled();
  });
});

describe("response interceptor error normalization", () => {
  it("surfaces a FastAPI HTTPException detail string", async () => {
    const { apiClient } = await loadApi("http://localhost:8000");
    failWith(apiClient, { detail: "Incorrect username/email or password." });

    await expect(apiClient.get("/x")).rejects.toThrow(
      "Incorrect username/email or password."
    );
  });

  it("surfaces the first field error from the validation-handler shape", async () => {
    const { apiClient } = await loadApi("http://localhost:8000");
    failWith(apiClient, {
      success: false,
      message: "Validation failed",
      errors: [{ field: "label", message: "at most 100 characters" }],
    });

    await expect(apiClient.get("/x")).rejects.toThrow("label: at most 100 characters");
  });

  it("reports a timeout distinctly", async () => {
    const { apiClient } = await loadApi("http://localhost:8000");
    failWith(apiClient, undefined, 0, "ECONNABORTED", "timeout exceeded");

    await expect(apiClient.get("/x")).rejects.toThrow(
      "Request timed out. Please check your connection."
    );
  });
});
