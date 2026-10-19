import path from "node:path";

import { defineConfig } from "vitest/config";

/**
 * Node-only tests for the pure feature modules behind the mobile one-flow
 * create, Ad Studio, winner loop, per-reel pricing, and the studio /
 * marketplace feature clients (clip market, film, speak, trends, ...). Mirrors
 * vitest.product.config.ts: no Expo SDK needed, AsyncStorage is a no-op stub.
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
    include: [
      "src/features/one-flow/__tests__/**/*.test.ts",
      "src/features/ad-studio/__tests__/**/*.test.ts",
      "src/features/winner-loop/__tests__/**/*.test.ts",
      "src/shared/billing/__tests__/per-reel.test.ts",
      "src/shared/media/__tests__/local-folder-migration.test.ts",
      // Preset shelf client — the mobile port of the web one-tap preset flow.
      "lib/__tests__/presets-shelf.test.ts",
      // Studio / marketplace feature clients + pure logic (fetch stubbed in-test).
      "src/features/clip-market/__tests__/**/*.test.ts",
      "src/features/clipfarm-console/__tests__/**/*.test.ts",
      "src/features/experiments/__tests__/**/*.test.ts",
      "src/features/film-studio/__tests__/**/*.test.ts",
      "src/features/media-gateway/__tests__/**/*.test.ts",
      "src/features/reel-compose/__tests__/**/*.test.ts",
      "src/features/speak-studio/__tests__/**/*.test.ts",
      "src/features/trends-feed/__tests__/**/*.test.ts",
      "src/features/jobs-library/__tests__/**/*.test.ts",
    ],
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
