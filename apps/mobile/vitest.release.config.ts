import path from "node:path";

import { defineConfig } from "vitest/config";

/**
 * Release guards (node-only): the store build's screen surface, internal-link
 * hygiene, signup-first, and the dev-only demo mode that must never ship on.
 */
export default defineConfig({
  test: {
    environment: "node",
    include: ["src/shared/release/__tests__/**/*.test.ts"],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
});
