import { describe, expect, it } from "vitest";
import { rallyOnboardUrl, rallyWebUrl } from "./rally-link";

describe("rallyWebUrl", () => {
  it("returns null when RALLY_WEB_URL is not set (no shut-down fallback host)", () => {
    expect(rallyWebUrl(undefined)).toBeNull();
    expect(rallyWebUrl("")).toBeNull();
    expect(rallyWebUrl("   ")).toBeNull();
  });

  it("returns null for invalid or non-http values", () => {
    expect(rallyWebUrl("not a url")).toBeNull();
    expect(rallyWebUrl("javascript:alert(1)")).toBeNull();
  });

  it("normalizes a configured origin", () => {
    expect(rallyWebUrl("https://rally.example.com/some/path")).toBe("https://rally.example.com");
  });
});

describe("rallyOnboardUrl", () => {
  it("builds the onboarding deep link with the product site", () => {
    const url = rallyOnboardUrl("https://rally.example.com", "https://shop.example.com");
    expect(url).toBe(
      "https://rally.example.com/rally/onboard?url=https%3A%2F%2Fshop.example.com&source=menivor",
    );
  });

  it("omits the url param when the product site is unknown", () => {
    expect(rallyOnboardUrl("https://rally.example.com", null)).toBe(
      "https://rally.example.com/rally/onboard?source=menivor",
    );
  });
});
