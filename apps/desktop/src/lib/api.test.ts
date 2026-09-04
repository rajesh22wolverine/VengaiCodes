import { AxiosError, InternalAxiosRequestConfig } from "axios";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

// The request interceptor reads localStorage, which does not exist under
// vitest's "node" environment. A two-method stub is enough and keeps this
// suite free of a jsdom/happy-dom dependency.
const store = new Map<string, string>();

beforeAll(() => {
  (globalThis as any).localStorage = {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
    clear: () => store.clear(),
  };
});

afterEach(() => {
  store.clear();
  vi.unstubAllEnvs();
  vi.resetModules();
});

/** Load a fresh copy of api.ts with VITE_API_URL stubbed to `url`. */
async function loadApiWith(url: string) {
  vi.stubEnv("VITE_API_URL", url);
  vi.resetModules();
  return import("./api");
}

describe("IS_LOCAL_BACKEND", () => {
  // Portable/local AI models are saved with a 127.0.0.1 base_url, which a
  // remote backend can never reach. This flag gates the warning that stops
  // users configuring something guaranteed not to work, so a wrong answer
  // here is silently user-hostile in both directions.
  it.each([
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "https://localhost",
    "http://localhost",
    "http://LocalHost:1420",
  ])("treats %s as local", async (url) => {
    const { IS_LOCAL_BACKEND } = await loadApiWith(url);
    expect(IS_LOCAL_BACKEND).toBe(true);
  });

  it.each([
    "https://vengaicode-backend.onrender.com",
    "https://api.example.com",
    // Must not be fooled by a hostname that merely starts with "localhost".
    "http://localhost.evil.com",
    "http://127.0.0.1.evil.com",
  ])("treats %s as remote", async (url) => {
    const { IS_LOCAL_BACKEND } = await loadApiWith(url);
    expect(IS_LOCAL_BACKEND).toBe(false);
  });

  it("builds the baseURL by appending the v1 prefix", async () => {
    const { apiClient } = await loadApiWith("https://vengaicode-backend.onrender.com");
    expect(apiClient.defaults.baseURL).toBe(
      "https://vengaicode-backend.onrender.com/api/v1"
    );
  });
});

describe("request interceptor", () => {
  it("attaches a bearer token when one is stored", async () => {
    const { apiClient } = await loadApiWith("http://localhost:8000");
    store.set("vengaicode_token", "tok123");

    let seen: string | undefined;
    apiClient.defaults.adapter = async (config) => {
      seen = config.headers?.Authorization as string | undefined;
      return { data: {}, status: 200, statusText: "OK", headers: {}, config } as any;
    };

    await apiClient.get("/whoami");
    expect(seen).toBe("Bearer tok123");
  });

  it("sends no Authorization header when logged out", async () => {
    const { apiClient } = await loadApiWith("http://localhost:8000");

    let seen: string | undefined = "unset";
    apiClient.defaults.adapter = async (config) => {
      seen = config.headers?.Authorization as string | undefined;
      return { data: {}, status: 200, statusText: "OK", headers: {}, config } as any;
    };

    await apiClient.get("/whoami");
    expect(seen).toBeUndefined();
  });
});

describe("response interceptor error normalization", () => {
  /** Make apiClient fail the way axios does, with `data` as the error body. */
  function failWith(
    apiClient: { defaults: { adapter?: unknown } },
    data: unknown,
    code?: string,
    message = "Request failed"
  ) {
    (apiClient.defaults as any).adapter = async (
      config: InternalAxiosRequestConfig
    ) => {
      throw new AxiosError(
        message,
        code,
        config,
        null,
        data === undefined
          ? undefined
          : ({
              data,
              status: 400,
              statusText: "Bad Request",
              headers: {},
              config,
            } as any)
      );
    };
  }

  it("surfaces a plain FastAPI HTTPException detail string", async () => {
    const { apiClient } = await loadApiWith("http://localhost:8000");
    failWith(apiClient, { detail: "Incorrect username/email or password." });

    await expect(apiClient.get("/x")).rejects.toThrow(
      "Incorrect username/email or password."
    );
  });

  it("surfaces the first field error from the validation-handler shape", async () => {
    // main.py's RequestValidationError handler emits this shape. It exists
    // precisely because the frontend could not read FastAPI's default one.
    const { apiClient } = await loadApiWith("http://localhost:8000");
    failWith(apiClient, {
      success: false,
      message: "Validation failed",
      errors: [{ field: "label", message: "ensure this value has at most 100 characters" }],
    });

    await expect(apiClient.get("/x")).rejects.toThrow(
      "label: ensure this value has at most 100 characters"
    );
  });

  it("falls back to `message` when the errors array is empty", async () => {
    const { apiClient } = await loadApiWith("http://localhost:8000");
    failWith(apiClient, { success: false, message: "Validation failed", errors: [] });

    await expect(apiClient.get("/x")).rejects.toThrow("Validation failed");
  });

  it("reports an unreachable backend distinctly from a server error", async () => {
    const { apiClient } = await loadApiWith("http://localhost:8000");
    failWith(apiClient, undefined, undefined, "Network Error");

    await expect(apiClient.get("/x")).rejects.toThrow(
      "Cannot reach VengaiCode backend. Is it running?"
    );
  });

  it("reports a timeout distinctly", async () => {
    const { apiClient } = await loadApiWith("http://localhost:8000");
    failWith(apiClient, undefined, "ECONNABORTED", "timeout exceeded");

    await expect(apiClient.get("/x")).rejects.toThrow(
      "Request timed out. Please check your connection."
    );
  });

  // KNOWN GAP, asserted so it is visible rather than forgotten: FastAPI's
  // *default* 422 body puts errors in a `detail` ARRAY. The interceptor only
  // reads `detail` when it is a string, so such a body degrades to the
  // generic toast and the real reason is lost. Today the backend's own
  // handler means this shape should not reach us — if that handler is ever
  // removed or bypassed, this test documents what users would see.
  it("degrades to the generic message for FastAPI's raw 422 detail array", async () => {
    const { apiClient } = await loadApiWith("http://localhost:8000");
    failWith(apiClient, {
      detail: [{ loc: ["body", "label"], msg: "field required", type: "value_error" }],
    });

    await expect(apiClient.get("/x")).rejects.toThrow(
      "Something went wrong. Baby Tiger is investigating!"
    );
  });
});
