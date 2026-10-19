import { describe, expect, it } from "vitest";
import { isStoreLink } from "./api";

describe("isStoreLink", () => {
  it("recognizes App Store links (apps.apple.com and the legacy itunes.apple.com host)", () => {
    expect(isStoreLink("https://apps.apple.com/us/app/caldesk/id6780166477")).toBe(true);
    expect(isStoreLink("https://itunes.apple.com/us/app/x/id123456789")).toBe(true);
  });

  it("recognizes Google Play links", () => {
    expect(isStoreLink("https://play.google.com/store/apps/details?id=com.example.app")).toBe(true);
  });

  it("rejects everything else, including malformed URLs", () => {
    expect(isStoreLink("https://example.com/")).toBe(false);
    expect(isStoreLink("https://tiktok.com/@someone/video/1")).toBe(false);
    expect(isStoreLink("not a url")).toBe(false);
    expect(isStoreLink("")).toBe(false);
  });
});
