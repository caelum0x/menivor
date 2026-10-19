import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Regression guard for the "raw Clerk hook crashes without a Clerk key" bug.
 * Mirrors the ESLint `no-restricted-imports` rule in `.eslintrc.json` so it
 * also fails in CI setups that only run the test suite.
 */
const ROOT = path.resolve(__dirname, "../../..");
const SCAN_DIRS = ["app", "components", "lib", "src"];
const ALLOWED = new Set([
  "components/auth/clerk-safe.tsx",
  // Mounts <ClerkProvider> only when hasRealClerkKey is true.
  "app/layout.tsx",
]);
const RAW_IMPORT = /from\s+["']@clerk\/nextjs["']/;

function walk(dir: string, out: string[]): string[] {
  for (const entry of readdirSync(dir)) {
    if (entry === "node_modules" || entry.startsWith(".")) continue;
    const full = path.join(dir, entry);
    if (statSync(full).isDirectory()) walk(full, out);
    else if (/\.(ts|tsx)$/.test(entry)) out.push(full);
  }
  return out;
}

function isTestFile(rel: string): boolean {
  return /\.test\.tsx?$/.test(rel) || rel.includes("__tests__/");
}

describe("Clerk import boundary", () => {
  it("routes every app import of @clerk/nextjs through clerk-safe", () => {
    const offenders = SCAN_DIRS.flatMap((d) => walk(path.join(ROOT, d), []))
      .map((f) => path.relative(ROOT, f).split(path.sep).join("/"))
      .filter((rel) => !ALLOWED.has(rel) && !isTestFile(rel))
      .filter((rel) => RAW_IMPORT.test(readFileSync(path.join(ROOT, rel), "utf8")));
    expect(offenders).toEqual([]);
  });
});
