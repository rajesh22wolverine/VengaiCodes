import { defineConfig } from "vitest/config";
import path from "path";

// Why vitest and not jest-expo here:
// everything covered is pure logic, reducers, or axios wiring — none of it
// renders a React Native component or touches the native runtime, so the
// Expo/Metro test stack buys nothing and costs a much heavier install.
// If real component tests are ever wanted (rendering a screen, firing a
// press), that IS jest-expo + @testing-library/react-native territory and
// should be added alongside this, not instead of it.
//
// The "@/*" -> "src/*" alias mirrors tsconfig.json's paths.
export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
    // app/ holds expo-router screens (.tsx) — those need the RN runtime and
    // are deliberately out of scope for this suite.
    exclude: ["node_modules/**", "app/**", "android/**", "ios/**"],
  },
});
