import path from "node:path";

import { defineConfig } from "vitest/config";

/**
 * Sign-in guards (node-only): which auth project (Scribase) a build signs in
 * against, sign-out wording, and identity deletion. Native modules are mocked
 * inside each test file.
 */
export default defineConfig({
  test: {
    environment: "node",
    include: ["src/shared/auth/__tests__/**/*.test.ts"],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
});
