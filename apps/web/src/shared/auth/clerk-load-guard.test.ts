import { describe, expect, it } from "vitest";
import { isClerkLoadFailure } from "./clerk-load-guard";

describe("isClerkLoadFailure", () => {
  it("matches Clerk's failed_to_load_clerk_js error message", () => {
    expect(
      isClerkLoadFailure(
        'Clerk: Failed to load Clerk, failed to load script: https://clerk.menivor.com/npm/@clerk/clerk-js@5/dist/clerk.browser.js\n\n(code="failed_to_load_clerk_js")\n\n',
      ),
    ).toBe(true);
  });

  it("is case-insensitive", () => {
    expect(isClerkLoadFailure("FAILED_TO_LOAD_CLERK_JS")).toBe(true);
  });

  it("ignores unrelated errors", () => {
    expect(isClerkLoadFailure("TypeError: x is undefined")).toBe(false);
    expect(isClerkLoadFailure("")).toBe(false);
    expect(isClerkLoadFailure(undefined)).toBe(false);
    expect(isClerkLoadFailure(null)).toBe(false);
  });
});
