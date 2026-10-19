import path from "node:path";

import { defineConfig } from "vitest/config";

/**
 * Node-only tests for the mobile social inbox, standalone Dub Studio and
 * Design Studio clients (lib/social-inbox.ts, lib/dub-studio.ts,
 * lib/design-studio.ts). `fetch` is stubbed in-test; no Expo SDK needed.
 */
export default defineConfig({
  test: {
    environment: "node",
    include: ["lib/__tests__/{social-inbox,dub-studio,design-studio}.test.ts"],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
});
