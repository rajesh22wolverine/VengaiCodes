import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// ─────────────────────────────────────────────────────────────
//  VengaiCode — Generated App — Vite Config (Capacitor/Android)
//  Fixed template (not AI-generated). Capacitor loads the built
//  dist/ folder as the app's local web assets.
// ─────────────────────────────────────────────────────────────

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
  },
});
