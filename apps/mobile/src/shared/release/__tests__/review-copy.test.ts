/**
 * App Review (2.1 / 2.2): a store build must not show a whole tab that only
 * says "unavailable", nor talk about internal pilots or betas.
 */
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { isBrollAvailable } from "@/src/features/broll-studio/availability";
import { ROOT } from "./scan";

const read = (rel: string) => fs.readFileSync(path.join(ROOT, rel), "utf8");

describe("B-roll tab availability", () => {
  it("is shown only when the server switches AI B-roll on for this account", () => {
    expect(isBrollAvailable(null)).toBe(false);
    expect(isBrollAvailable(undefined)).toBe(false);
    expect(isBrollAvailable({ generation: { broll: false } })).toBe(false);
    expect(isBrollAvailable({ generation: {} })).toBe(false);
    expect(isBrollAvailable({ generation: { broll: true } })).toBe(true);
  });

  it("stays hidden while storage for clips is not ready", () => {
    expect(
      isBrollAvailable({ generation: { broll: true }, product: { runtime: { storage_ready: false } } }),
    ).toBe(false);
    expect(
      isBrollAvailable({ generation: { broll: true }, product: { runtime: { storage_ready: true } } }),
    ).toBe(true);
  });

  it("the tab bar hides the B-roll tab unless it is available", () => {
    const tabs = read("app/(tabs)/_layout.tsx");
    expect(tabs).toContain("isBrollAvailable(");
    expect(tabs).toMatch(/href:\s*brollVisible \? undefined : null/);
  });

  it("Create only offers 'Generate AI B-roll' when B-roll is available", () => {
    const create = read("src/features/reel-create/CreateScreen.tsx");
    expect(create).toMatch(/\{brollAvailable \? \(\s*<Pressable[\s\S]{0,120}router\.push\("\/\(tabs\)\/broll"\)/);
  });

  it("the B-roll screen uses the same availability rule", () => {
    expect(read("src/features/broll-studio/BrollScreen.tsx")).toContain("isBrollAvailable(");
  });
});

describe("no pilot/beta wording on creator screens", () => {
  it.each([
    "src/features/broll-studio/BrollScreen.tsx",
    "src/features/reel-create/CreateScreen.tsx",
    "src/features/reel-compose/components/TemplateInputForm.tsx",
  ])("%s", (rel) => {
    expect(read(rel)).not.toMatch(/internal (generation )?pilot|pilot accounts/i);
  });
});

describe("Menivor tab bar honours hidden tabs", () => {
  it("treats expo-router href: null (display none) as hidden", async () => {
    const { isTabHidden } = await import("@/src/ui/menivor/tab-visibility");
    expect(isTabHidden({ tabBarItemStyle: { display: "none" } })).toBe(true);
    expect(isTabHidden({ tabBarItemStyle: [{ height: 3 }, { display: "none" }] })).toBe(true);
    expect(isTabHidden({ tabBarItemStyle: { display: "flex" } })).toBe(false);
    expect(isTabHidden({})).toBe(false);
  });

  it("ReelTabBar skips hidden routes", () => {
    expect(read("src/ui/menivor/ReelTabBar.tsx")).toMatch(/if \(isTabHidden\(options\)\) return null;/);
  });
});
