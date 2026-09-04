import { defineConfig } from "vitest/config";
import path from "path";

// Kept separate from vite.config.ts so the app build config stays free of
// test-only settings. The alias list must mirror vite.config.ts's — if an
// alias is added there, add it here too or test imports will fail to resolve.
export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      "@components": path.resolve(__dirname, "./src/components"),
      "@screens": path.resolve(__dirname, "./src/screens"),
      "@store": path.resolve(__dirname, "./src/store"),
      "@hooks": path.resolve(__dirname, "./src/hooks"),
      "@lib": path.resolve(__dirname, "./src/lib"),
      "@styles": path.resolve(__dirname, "./src/styles"),
      "@types": path.resolve(__dirname, "./src/types"),
    },
  },
  test: {
    // "node" rather than jsdom: everything covered here is pure logic,
    // reducers, or axios wiring. No DOM dependency means no extra
    // dependency (jsdom/happy-dom) and a much faster run. Add an
    // environment override per-file if a real component test lands later.
    environment: "node",
    include: ["src/**/*.test.ts"],
    // Playwright specs live under e2e/ and are driven by @playwright/test,
    // not vitest — excluded so `vitest` never tries to collect them.
    exclude: ["node_modules/**", "dist/**", "e2e/**", "src-tauri/**"],
  },
});
