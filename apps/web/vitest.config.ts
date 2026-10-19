import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

/**
 * Vitest config for the ReelForge web app. Uses jsdom + Testing Library so
 * feature components can be exercised against a mocked `fetch`, and mirrors the
 * `@/*` path alias from `tsconfig.json` so imports resolve identically to Next.
 */
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    // Non-secret, non-routable test key (decodes to "clerk.menivor.test") so
    // `hasRealClerkKey` is true and `components/auth/clerk-safe` delegates to
    // the per-test `vi.mock("@clerk/nextjs")`. No-key behaviour is covered by
    // app/no-clerk-smoke.test.tsx, which mocks `@/lib/clerk` directly.
    env: { NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY: "pk_test_Y2xlcmsubWVuaXZvci50ZXN0JA==" },
    // "components" was missing from this list, so a `*.test.tsx` placed next
    // to a top-level components/ file (as opposed to app/_components or src/)
    // silently never ran — see components/marketing/free-tools/shared.test.tsx.
    include: [
      "src/**/*.test.{ts,tsx}",
      "app/**/*.test.{ts,tsx}",
      "lib/seo/**/*.test.{ts,tsx}",
      "components/**/*.test.{ts,tsx}",
    ],
  },
  resolve: {
    alias: { "@": path.resolve(__dirname, ".") },
  },
});
