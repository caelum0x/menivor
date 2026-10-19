import * as React from "react";
import * as fs from "node:fs";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
const signed = { isLoaded: true, isSignedIn: true };
vi.mock("@/lib/auth-state", () => ({ useSignedInState: () => signed }));
vi.mock("@/lib/use-api-token", () => ({ useApiToken: () => async () => "session" }));

import { checkUnits, type Denylist } from "@/src/shared/policy/copy-check";
import { sourceUnits } from "@/src/shared/policy/source-units";
import { LaunchVideoClient, TOKEN_STORAGE_KEY, takePartnerToken } from "./LaunchVideoClient";

function stubApi(status: number, data: unknown) {
  const calls: { url: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      const body = status === 200 ? { status, data } : { status, data, message: "refused" };
      return {
        ok: status === 200,
        status,
        statusText: "",
        headers: new Headers(),
        json: async () => body,
        text: async () => JSON.stringify(body),
      };
    }),
  );
  return calls;
}

beforeEach(() => {
  window.sessionStorage.clear();
  window.history.replaceState(null, "", "/launch-video?app_url=https%3A%2F%2Fmyapp.example#token=tok_abc");
  signed.isSignedIn = true;
  push.mockClear();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("launch video page", () => {
  it("reads the token from the fragment, strips it from the address bar and keeps it for this tab", () => {
    expect(takePartnerToken()).toBe("tok_abc");
    expect(window.location.hash).toBe("");
    expect(window.location.href).not.toContain("tok_abc");
    expect(window.sessionStorage.getItem(TOKEN_STORAGE_KEY)).toBe("tok_abc");
    expect(takePartnerToken()).toBe("tok_abc");
  });

  it("signed in: sends the token once and opens the pre-filled create flow", async () => {
    const calls = stubApi(200, {
      app_url: "https://myapp.example",
      app_name: "My App",
      topic: "Launch video for My App",
      create_url: "/create?q=https%3A%2F%2Fmyapp.example",
      source: "scribase",
    });
    render(<LaunchVideoClient appUrl="https://myapp.example" appName="My App" source="scribase" />);
    await waitFor(() => expect(push).toHaveBeenCalledWith("/create?q=https%3A%2F%2Fmyapp.example"));
    const post = calls.filter((c) => c.url.endsWith("/partners/launch-video"));
    expect(post).toHaveLength(1);
    expect(post[0]?.body).toEqual({
      token: "tok_abc",
      app_url: "https://myapp.example",
      app_name: "My App",
      source: "scribase",
    });
    expect(window.sessionStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull();
  });

  it("signed out: asks for the user's own email sign-up and returns to this page", () => {
    signed.isSignedIn = false;
    stubApi(200, {});
    render(<LaunchVideoClient appUrl="https://myapp.example" appName="My App" source="scribase" />);
    const link = screen.getByRole("link", { name: /Sign up with your email/ });
    expect(link.getAttribute("href")).toContain("/sign-up?redirect_url=");
    expect(decodeURIComponent(link.getAttribute("href") ?? "")).toContain("/launch-video?app_url=");
    expect(decodeURIComponent(link.getAttribute("href") ?? "")).not.toContain("tok_abc");
  });

  it("shows a plain refusal for an expired or revoked link", async () => {
    stubApi(401, { code: "expired" });
    render(<LaunchVideoClient appUrl="https://myapp.example" appName="" source="scribase" />);
    expect((await screen.findByRole("alert")).textContent).toMatch(/expired/);
    expect(push).not.toHaveBeenCalled();
  });

  it("follows live pricing and has no presenter copy", () => {
    stubApi(200, {});
    signed.isSignedIn = false;
    render(<LaunchVideoClient appUrl="" appName="" source="scribase" />);
    const pricing = screen.getByText(/Pricing is the same as for everyone/);
    expect(pricing.getAttribute("data-copy-source")).toContain("offersFromPlanConfig");
    expect(document.body.textContent).not.toMatch(/presenter|avatar|lip[- ]?sync/i);
  });

  it("passes the copy denylist", () => {
    const web = path.resolve(__dirname, "../../..");
    const denylist = JSON.parse(fs.readFileSync(path.resolve(web, "../../policy/copy-denylist.json"), "utf8")) as Denylist;
    const units = ["page.tsx", "LaunchVideoClient.tsx"].flatMap(
      (rel) => sourceUnits(fs.readFileSync(path.join(__dirname, rel), "utf8"), `app/(marketing)/launch-video/${rel}`).units,
    );
    const hits = checkUnits(denylist, units, { flags: {} }).filter((h) => h.severity === "error");
    expect(hits).toEqual([]);
  });
});
