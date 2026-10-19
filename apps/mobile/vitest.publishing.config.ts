import path from "node:path";

import { defineConfig } from "vitest/config";

/**
 * Node-only tests for the approvals and channel-publishing clients (lib/approvals,
 * lib/channels, lib/readable-error). No Expo SDK needed; fetch is stubbed.
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
    include: ["lib/__tests__/approvals-channels.test.ts"],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
});
