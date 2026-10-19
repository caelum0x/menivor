import path from "node:path";

import { defineConfig } from "vitest/config";

/**
 * Node-only behaviour tests for the waitlist-era product logic (waitlist client,
 * local drafts, product mode). Mirrors vitest.wallet.config.ts: no Expo SDK
 * required — the native AsyncStorage module is aliased to a no-op stub, and the
 * draft tests inject an in-memory storage backend.
 */
export default defineConfig({
  esbuild: {
    tsconfigRaw: JSON.stringify({
      compilerOptions: {
        jsx: "react-jsx",
        target: "ES2022",
      },
    }),
  },
  test: {
    environment: "node",
    include: ["src/shared/product/__tests__/**/*.test.ts"],
  },
  resolve: {
    alias: {
      "@react-native-async-storage/async-storage": path.resolve(
        __dirname,
        "web-stubs/async-storage.js",
      ),
      "@": path.resolve(__dirname, "."),
    },
  },
});
