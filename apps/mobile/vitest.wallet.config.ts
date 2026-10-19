import path from "node:path";

import { defineConfig } from "vitest/config";

/** Focused, Node-only contract tests for the wallet transfer client and journal. */
export default defineConfig({
  // Keep the pure contract suite runnable when the optional Expo SDK is not
  // installed. Native type-check/build still uses the app's Expo tsconfig.
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
    include: [
      "lib/transfer-outcome.test.ts",
      "lib/transfer-pending.test.ts",
      "src/features/wallet-publish/__tests__/wallet.test.ts",
      "src/features/wallet-publish/__tests__/schedule-time.test.ts",
    ],
  },
  resolve: {
    alias: { "@": path.resolve(__dirname, ".") },
  },
});
