import { afterEach, describe, expect, it } from "vitest";

import { isWaitlistMode } from "../useProductMode";

const ORIGINAL = process.env.EXPO_PUBLIC_WAITLIST_MODE;

afterEach(() => {
  if (ORIGINAL === undefined) delete process.env.EXPO_PUBLIC_WAITLIST_MODE;
  else process.env.EXPO_PUBLIC_WAITLIST_MODE = ORIGINAL;
});

describe("isWaitlistMode", () => {
  it("defaults to false (product-first) when the flag is unset", () => {
    delete process.env.EXPO_PUBLIC_WAITLIST_MODE;
    expect(isWaitlistMode()).toBe(false);
  });

  it("stays off for any value other than an explicit 1", () => {
    process.env.EXPO_PUBLIC_WAITLIST_MODE = "0";
    expect(isWaitlistMode()).toBe(false);
    process.env.EXPO_PUBLIC_WAITLIST_MODE = "true";
    expect(isWaitlistMode()).toBe(false);
  });

  it("turns on only when explicitly set to 1 (pre-launch marketing build)", () => {
    process.env.EXPO_PUBLIC_WAITLIST_MODE = "1";
    expect(isWaitlistMode()).toBe(true);
  });
});
