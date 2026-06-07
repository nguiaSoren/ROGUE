import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

/**
 * Minimal Vitest config for the frontend.
 *
 * - `@vitejs/plugin-react` lets component tests render JSX/TSX.
 * - `environment: "jsdom"` gives DOM globals for @testing-library/react.
 * - The `@/*` alias mirrors tsconfig.json so imports resolve the same way the
 *   Next build does.
 */
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
});
