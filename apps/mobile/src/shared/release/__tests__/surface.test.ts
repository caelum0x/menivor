import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import {
  RELEASE_ROUTES,
  SHADOWED_STATIC_ROUTES,
  isReleaseRoute,
  isRouteAvailable,
  normalizeRoute,
} from "../surface";
import {
  ROOT,
  isKnownScreen,
  routeForFile,
  routeLiterals,
  screenFiles,
  walk,
} from "./scan";

const screens = screenFiles().map(routeForFile);

describe("release surface", () => {
  it("only lists routes that exist under app/", () => {
    for (const route of RELEASE_ROUTES) {
      expect(screens, `missing screen for ${route}`).toContain(route);
    }
  });

  it("normalises groups, index, query and trailing slashes", () => {
    expect(normalizeRoute("/(tabs)/create?q=1")).toBe("/create");
    expect(normalizeRoute("/studio/captions/index")).toBe("/studio/captions");
    expect(normalizeRoute("/wallet/")).toBe("/wallet");
    expect(normalizeRoute("")).toBe("/");
  });

  it("keeps the creator product: create, edit, captions, voices, renders, credits", () => {
    for (const route of [
      "/",
      "/(tabs)/create",
      "/create/results",
      "/job/abc123",
      "/editor",
      "/studio/captions",
      "/studio/dub",
      "/account/voices",
      "/repurpose/clipping",
      "/wallet/top-up",
      "/account/settings",
      "/privacy",
      "/support",
      "/legal/terms",
    ]) {
      expect(isReleaseRoute(route), route).toBe(true);
    }
  });

  it("hides labs, admin, developer tooling, token transfers and marketplaces", () => {
    for (const route of [
      "/hook-lab",
      "/retention-lab",
      "/ab-lab",
      "/trend-lab",
      "/diffusion-lab",
      "/effects-lab",
      "/model-governance",
      "/account/admin",
      "/account/admin/users",
      "/account/developer-keys",
      "/account/provider-keys",
      "/account/webhooks",
      "/api-keys",
      "/developer",
      "/gateway",
      "/media-gateway",
      "/wallet/transfer",
      "/wallet-send",
      "/wallet/destinations",
      "/wallet/transfer-policy",
      "/clipmarket",
      "/clipfarm-console",
      "/marketplace",
      "/navigation/discoverability",
      "/account-access",
      "/social-sign-in",
      "/catalog/model-catalog",
      "/catalog/trend-pull",
      "/sso",
      "/reels/schedule",
    ]) {
      expect(isReleaseRoute(route), route).toBe(false);
      expect(isRouteAvailable(route, false), route).toBe(false);
      expect(isRouteAvailable(route, true), route).toBe(true);
    }
  });

  it("shadowed static routes are real screens", () => {
    for (const route of SHADOWED_STATIC_ROUTES) expect(screens).toContain(route);
  });

  it("no unreleased static screen is let through by a [param] pattern", () => {
    const released = new Set<string>(RELEASE_ROUTES);
    for (const screen of screens) {
      if (screen.includes("[")) continue;
      if (released.has(screen)) continue;
      expect(isReleaseRoute(screen), screen).toBe(false);
    }
  });
});

/**
 * Files only rendered by unreleased routes; their links can never be reached
 * from a store build.
 */
const ONLY_UNDER_GATED_ROUTES = new Set([
  "src/features/trends-feed/TrendsFeedScreen.tsx",
  "src/features/winner-loop/LoopDetailScreen.tsx",
]);

describe("release links", () => {
  it("released screens and shared code only link to released screens (or check first)", () => {
    const files = [
      ...screenFiles().filter((file) => isReleaseRoute(routeForFile(file))),
      ...walk(path.join(ROOT, "src")),
      ...walk(path.join(ROOT, "components")),
    ];
    const offenders: string[] = [];
    for (const file of files) {
      const rel = path.relative(ROOT, file);
      if (ONLY_UNDER_GATED_ROUTES.has(rel)) continue;
      const source = fs.readFileSync(file, "utf8");
      if (source.includes("isRouteAvailable(")) continue;
      for (const route of routeLiterals(source)) {
        if (isKnownScreen(route, screens) && !isReleaseRoute(route)) {
          offenders.push(`${rel} -> ${route}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it("exempted files are only imported by unreleased screens", () => {
    for (const rel of ONLY_UNDER_GATED_ROUTES) {
      const name = path.basename(rel, ".tsx");
      for (const file of screenFiles()) {
        const source = fs.readFileSync(file, "utf8");
        if (source.includes(name)) {
          expect(isReleaseRoute(routeForFile(file)), `${file} imports ${name}`).toBe(false);
        }
      }
    }
  });
});
