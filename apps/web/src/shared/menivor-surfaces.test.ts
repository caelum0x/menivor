import { describe, expect, it } from "vitest";

import {
  APP_NAV_GROUPS,
  hiddenNavCount,
  visibleNavGroups,
} from "@/components/app-shell/nav-items";
import { sdkOrigin } from "@/components/developer/SdkInstallSnippets";

describe("More tools nav group", () => {
  const group = APP_NAV_GROUPS.find((g) => g.label === "More tools");

  it("lists the secondary surfaces and labs", () => {
    const hrefs = group?.items.map((i) => i.href) ?? [];
    for (const href of [
      "/discover",
      "/catalog",
      "/media",
      "/models/compare",
      "/agency",
      "/hook-lab",
      "/ab-lab",
      "/retention-lab",
      "/trend-lab",
      "/effects-lab",
      "/workflows-lab",
    ]) {
      expect(hrefs).toContain(href);
    }
  });

  it("is hidden until Show all tools is on", () => {
    expect(group?.items.some((i) => i.core)).toBe(false);
    expect(visibleNavGroups(APP_NAV_GROUPS, false).map((g) => g.label)).not.toContain(
      "More tools",
    );
    expect(visibleNavGroups(APP_NAV_GROUPS, true).map((g) => g.label)).toContain("More tools");
    expect(hiddenNavCount(APP_NAV_GROUPS)).toBeGreaterThanOrEqual(group?.items.length ?? 0);
  });

  it("has no duplicate hrefs across the whole menu", () => {
    const all = APP_NAV_GROUPS.flatMap((g) => g.items.map((i) => i.href));
    expect(new Set(all).size).toBe(all.length);
  });
});

describe("sdkOrigin", () => {
  it("strips the /api/v1 suffix the SDKs append themselves", () => {
    expect(sdkOrigin("https://api.menivor.com/api/v1")).toBe("https://api.menivor.com");
    expect(sdkOrigin("https://api.menivor.com/api/v1/")).toBe("https://api.menivor.com");
  });

  it("keeps a bare origin and falls back to the hosted API", () => {
    expect(sdkOrigin("http://localhost:8080")).toBe("http://localhost:8080");
    expect(sdkOrigin("")).toBe("https://api.menivor.com");
  });
});
