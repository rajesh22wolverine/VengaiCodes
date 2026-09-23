// VengaiCode desktop — ESLint config.
//
// `root: true` stops config resolution climbing up to the repo root's
// .eslintrc.js, which is a deliberately-empty stub (see its own
// comment) — without this, ESLint would try to merge with that empty
// file and error immediately trying to require() it as a module.
//
// Scoped to what apps/desktop/package.json actually has installed
// (@typescript-eslint/*, eslint-plugin-react-hooks) — no
// eslint-plugin-react, since that package was never added here.
module.exports = {
  root: true,
  parser: "@typescript-eslint/parser",
  parserOptions: {
    ecmaVersion: "latest",
    sourceType: "module",
    ecmaFeatures: { jsx: true },
  },
  env: { browser: true, es2021: true, node: true },
  plugins: ["@typescript-eslint", "react-hooks"],
  extends: ["eslint:recommended", "plugin:@typescript-eslint/recommended"],
  rules: {
    "react-hooks/rules-of-hooks": "error",
    "react-hooks/exhaustive-deps": "warn",
    // TypeScript's own compiler (tsc --noEmit, run separately in CI)
    // already catches undefined-variable errors more accurately than
    // ESLint's JS-only no-undef, which false-positives on TS-only
    // globals and ambient types.
    "no-undef": "off",
    "@typescript-eslint/no-unused-vars": ["warn", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
    // This codebase uses `any` deliberately at a number of API/library
    // interop boundaries — not a style this config is trying to change.
    "@typescript-eslint/no-explicit-any": "off",
    // Empty catch/interface bodies show up in a few deliberate places
    // (e.g. a swallowed clipboard-write failure); not worth erroring on.
    "@typescript-eslint/no-empty-function": "off",
  },
  ignorePatterns: ["dist", "node_modules", "*.config.js", "*.config.ts"],
};
