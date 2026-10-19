import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { DEMO_ENV_FLAG, isDemoMode } from "../build-flags";
import { DemoUnavailableError, demoResponse } from "../demo-api";
import { DEMO_PROJECTS } from "../demo-data";
import { ROOT } from "./scan";

const read = (rel: string) => fs.readFileSync(path.join(ROOT, rel), "utf8");

describe("demo mode release guard", () => {
  it("is off in store builds even when the env flag is set", () => {
    expect(isDemoMode(false, "1")).toBe(false);
    expect(isDemoMode(false, undefined)).toBe(false);
  });

  it("needs both a dev session and the explicit flag", () => {
    expect(isDemoMode(true, "1")).toBe(true);
    expect(isDemoMode(true, undefined)).toBe(false);
    expect(isDemoMode(true, "true")).toBe(false);
  });

  it("no EAS profile and no committed env file turns the flag on", () => {
    expect(read("eas.json")).not.toContain(DEMO_ENV_FLAG);
    for (const name of fs.readdirSync(ROOT)) {
      if (name.startsWith(".env") && name !== ".env.example") {
        expect(read(name)).not.toMatch(new RegExp(`${DEMO_ENV_FLAG}\\s*=\\s*1`));
      }
    }
  });

  it("the API client only answers locally behind isDemoMode()", () => {
    const client = read("src/shared/api/client.ts");
    const guard = client.indexOf("if (isDemoMode())");
    expect(guard).toBeGreaterThan(-1);
    expect(client.indexOf("demoResponse(")).toBeGreaterThan(guard);
    expect(client.indexOf("demoResponse(")).toBeLessThan(client.indexOf("await fetch("));
  });

  it("sign-in only uses the demo session behind isDemoMode()", () => {
    const signIn = read("app/index.tsx");
    expect(signIn).toContain("const demo = isDemoMode();");
    expect(signIn).toMatch(/if \(demo\) \{[\s\S]*?signIn\(DEMO_API_KEY\)/);
    expect(signIn.match(/DEMO_API_KEY/g)?.length).toBe(2); // import + guarded use
  });

  it("demo data is read-only and seeded with real-looking projects", () => {
    expect(() => demoResponse("POST", "/jobs")).toThrow(DemoUnavailableError);
    expect(() => demoResponse("GET", "/wallet/transfer")).toThrow(DemoUnavailableError);
    const jobs = demoResponse("GET", "/jobs") as { title?: string }[];
    expect(jobs.length).toBe(DEMO_PROJECTS.length);
    for (const job of jobs) {
      expect(job.title ?? "").not.toMatch(/lorem|test|sample|todo/i);
    }
    expect(demoResponse("GET", "/jobs/demo-reel-knife")).toMatchObject({ job_id: "demo-reel-knife" });
  });
});

describe("signup first", () => {
  it("released screens never mint an anonymous (identity-less) session", () => {
    for (const rel of ["app/index.tsx"]) {
      const source = read(rel);
      for (const call of source.matchAll(/createDeviceSession\(([^)]*)\)/g)) {
        expect((call[1] ?? "").split(",").length, `${rel}: ${call[0]}`).toBe(3);
      }
      expect(source).not.toMatch(/Start creating|continue without an account/i);
    }
  });

  it("Sign in with Apple uses the native button", () => {
    expect(read("app/index.tsx")).toContain("AppleAuthentication.AppleAuthenticationButton");
  });

  it("asks for AI processing consent before the creator tabs are usable", () => {
    expect(read("app/(tabs)/_layout.tsx")).toContain("<AiProcessingConsent");
  });

  it("Google sign-in is loaded lazily", () => {
    const social = read("src/shared/auth/social-signin.ts");
    expect(social).not.toMatch(/^import .*google-signin/m);
    expect(social).toContain('require("@react-native-google-signin/google-signin")');
  });
});
