import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { LAB_ENV_FLAG, isLabEnabled } from "../build-flags";
import { PUBLIC_ROUTES, isPublicRoute, routeAccess } from "../route-access";
import { RELEASE_ROUTES } from "../surface";
import { ROOT, routeForFile, screenFiles } from "./scan";

const read = (rel: string) => fs.readFileSync(path.join(ROOT, rel), "utf8");

describe("lab build flag", () => {
  it("is off by default, in dev sessions and in store builds", () => {
    expect(isLabEnabled(false, undefined)).toBe(false);
    expect(isLabEnabled(true, undefined)).toBe(false);
    expect(isLabEnabled(true, "0")).toBe(false);
    expect(isLabEnabled(true, "true")).toBe(false);
  });

  it("can never turn on in a store build, even if the env flag leaks", () => {
    expect(isLabEnabled(false, "1")).toBe(false);
  });

  it("needs a dev session plus EXPO_PUBLIC_ENABLE_LAB=1", () => {
    expect(LAB_ENV_FLAG).toBe("EXPO_PUBLIC_ENABLE_LAB");
    expect(isLabEnabled(true, "1")).toBe(true);
    expect(isLabEnabled(true, " 1 ")).toBe(true);
  });

  it("no EAS profile, app.json or committed env file enables the lab", () => {
    expect(read("eas.json")).not.toContain(LAB_ENV_FLAG);
    expect(read("app.json")).not.toContain(LAB_ENV_FLAG);
    for (const name of fs.readdirSync(ROOT)) {
      if (name.startsWith(".env") && name !== ".env.example") {
        expect(read(name)).not.toMatch(new RegExp(`${LAB_ENV_FLAG}\\s*=\\s*1`));
      }
    }
  });
});

const signedIn = { lab: false, signedIn: true, authLoading: false };
const signedOut = { lab: false, signedIn: false, authLoading: false };

describe("route access (store build)", () => {
  it("lab, admin, developer and crypto screens are internal for everyone", () => {
    for (const name of [
      "hook-lab",
      "effects-lab",
      "diffusion-lab",
      "account/admin/index",
      "account/admin/users",
      "account/developer-keys",
      "account-access",
      "wallet/transfer",
      "wallet-send",
      "wallet/destinations",
      "wallet/transfer-policy",
      "clipmarket",
      "marketplace",
      "social-sign-in",
    ]) {
      expect(routeAccess(name, signedIn), name).toBe("internal");
      expect(routeAccess(name, signedOut), name).toBe("internal");
    }
  });

  it("the creator product needs a signed-in account (no guest use)", () => {
    for (const name of [
      "(tabs)/create",
      "create/advanced",
      "create/results",
      "job/[id]",
      "editor",
      "studio/captions/index",
      "wallet/index",
      "wallet/top-up",
      "account/settings",
    ]) {
      expect(routeAccess(name, signedOut), name).toBe("signin");
      expect(routeAccess(name, signedIn), name).toBe("allow");
    }
  });

  it("waits for the stored session before deciding", () => {
    expect(routeAccess("editor", { ...signedOut, authLoading: true })).toBe("wait");
    expect(routeAccess("hook-lab", { ...signedOut, authLoading: true })).toBe("internal");
  });

  it("sign-in, legal, support, waitlist and public share links stay open", () => {
    for (const name of [
      "index",
      "(tabs)",
      "privacy",
      "support",
      "legal/terms",
      "legal/privacy",
      "legal/creator-contract",
      "waitlist",
      "beta-request",
      "r/[token]",
    ]) {
      expect(routeAccess(name, signedOut), name).toBe("allow");
    }
  });

  it("public routes are a subset of the release surface", () => {
    const released = new Set<string>(RELEASE_ROUTES);
    for (const route of PUBLIC_ROUTES) expect(released.has(route), route).toBe(true);
    expect(isPublicRoute("/editor")).toBe(false);
  });

  it("every screen file resolves to a decision (no route slips through)", () => {
    for (const file of screenFiles()) {
      const route = routeForFile(file);
      const decision = routeAccess(route.slice(1) || "index", signedOut);
      expect(["internal", "signin", "allow"], route).toContain(decision);
      if (decision === "allow") expect(isPublicRoute(route), route).toBe(true);
    }
  });
});

describe("route access (lab build)", () => {
  it("opens internal screens only when the lab flag is on, still behind sign-in", () => {
    const lab = { lab: true, signedIn: true, authLoading: false };
    expect(routeAccess("hook-lab", lab)).toBe("allow");
    expect(routeAccess("hook-lab", { ...lab, signedIn: false })).toBe("signin");
  });
});

describe("root layout gate", () => {
  const layout = read("app/_layout.tsx");

  it("wraps every stack screen in the render-blocking RouteGate", () => {
    expect(layout).toContain('import { gateScreen } from "@/src/shared/release/RouteGate";');
    expect(layout).toContain("screenLayout={gateScreen}");
  });

  it("no longer relies on the after-render redirect guard", () => {
    expect(layout).not.toContain("ReleaseRouteGuard");
    expect(fs.existsSync(path.join(ROOT, "src/shared/release/ReleaseRouteGuard.tsx"))).toBe(false);
  });

  it("the gate renders a redirect instead of the screen for blocked routes", () => {
    const gate = read("src/shared/release/RouteGate.tsx");
    expect(gate).toContain("routeAccess(");
    expect(gate).toMatch(/<Redirect/);
    // children (the screen) are only returned on "allow"
    expect(gate.match(/return children|return <>\{children\}<\/>/g)?.length).toBe(1);
  });
});
