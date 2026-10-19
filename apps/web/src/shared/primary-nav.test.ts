import { describe, expect, it } from "vitest";
import { APP_NAV_GROUPS, PRIMARY_NAV_ITEMS, isPrimaryActive } from "@/components/app-shell/nav-items";

describe("primary navigation", () => {
  it("has exactly the five WP3.2 destinations", () => {
    expect(PRIMARY_NAV_ITEMS.map((i) => i.label)).toEqual([
      "Home",
      "Create",
      "Autopilot",
      "Results",
      "Settings",
    ]);
  });

  it("lights the right destination for nested routes", () => {
    const [home, create, autopilot, results, settings] = PRIMARY_NAV_ITEMS;
    expect(isPrimaryActive("/scheduled", autopilot!)).toBe(true);
    expect(isPrimaryActive("/reels", home!)).toBe(true);
    expect(isPrimaryActive("/reels/calendar", home!)).toBe(true);
    expect(isPrimaryActive("/create/results", create!)).toBe(true);
    expect(isPrimaryActive("/creator-contract", create!)).toBe(false);
    expect(isPrimaryActive("/insights/winners", results!)).toBe(true);
    expect(isPrimaryActive("/wallet/plans", settings!)).toBe(true);
  });

  it("keeps every page that left the header reachable under More", () => {
    const hrefs = APP_NAV_GROUPS.flatMap((g) => g.items.map((i) => i.href));
    for (const href of ["/reels/calendar", "/scheduled", "/uploads", "/film", "/ad-studio", "/create/advanced", "/wallet"]) {
      expect(hrefs).toContain(href);
    }
  });
});
