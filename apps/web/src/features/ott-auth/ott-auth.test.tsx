import * as React from "react";
import * as fs from "node:fs";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { checkUnits, type Denylist } from "@/src/shared/policy/copy-check";
import { sourceUnits } from "@/src/shared/policy/source-units";
import { ViewerAccount } from "./ViewerAccount";
import { readSession, writeSession } from "./session-store";
import { trackProgress } from "./progress";
import { requestCode, verifyCode } from "./scribase-auth";

type Call = { url: string; method: string; headers: Record<string, string>; body: unknown };

function stubFetch(route: (url: string, method: string) => { status: number; body: unknown }) {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    calls.push({ url, method, headers: (init?.headers ?? {}) as Record<string, string>,
      body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const { status, body } = route(url, method);
    return { ok: status < 400, status, json: async () => body } as Response;
  }));
  return calls;
}

beforeEach(() => {
  process.env.NEXT_PUBLIC_SCRIBASE_VIEWERS_URL = "https://viewers.scribase.example";
  process.env.NEXT_PUBLIC_SCRIBASE_VIEWERS_ANON_KEY = "anon-publishable";
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("Scribase Auth email code", () => {
  it("sends the code and verifies it with the publishable key only", async () => {
    const calls = stubFetch((url) => ({ status: 200, body: url.endsWith("/verify") ? { access_token: "jwt-1" } : {} }));
    await requestCode(" Ana@Example.com ");
    expect(await verifyCode("ana@example.com", " 123456 ")).toBe("jwt-1");
    expect(calls[0]?.url).toBe("https://viewers.scribase.example/auth/v1/otp");
    expect(calls[0]?.body).toEqual({ email: "ana@example.com", create_user: true });
    expect(calls[1]?.body).toEqual({ type: "email", email: "ana@example.com", token: "123456" });
    expect(calls.every((c) => c.headers.apikey === "anon-publishable")).toBe(true);
  });

  it("explains a wrong code in plain words", async () => {
    stubFetch(() => ({ status: 403, body: { msg: "Token has expired or is invalid" } }));
    await expect(verifyCode("a@b.io", "000000")).rejects.toThrow("That code did not work. Ask for a new one.");
  });
});

describe("ViewerAccount", () => {
  it("signs in with email and code, stores the channel session and shows continue watching", async () => {
    const calls = stubFetch((url, method) => {
      if (url.endsWith("/auth/v1/otp")) return { status: 200, body: {} };
      if (url.endsWith("/auth/v1/verify")) return { status: 200, body: { access_token: "jwt-1" } };
      if (url.endsWith("/ott/viewers/maya/session") && method === "POST") {
        return { status: 200, body: { data: { session: "vs-1", expires_at: 4102444800, viewer: { id: "v1", email: "a@b.io", display_name: "ana" } } } };
      }
      if (url.endsWith("/ott/viewers/maya/continue")) {
        return { status: 200, body: { data: { items: [{ title_id: "t1", title: "Episode one", position_s: 30, duration_s: 600, finished: false, device: "ios" }] } } };
      }
      return { status: 404, body: {} };
    });
    render(<ViewerAccount handle="maya" />);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "a@b.io" } });
    fireEvent.click(screen.getByRole("button", { name: "Send code" }));
    await waitFor(() => screen.getByLabelText("Code from your email"));
    fireEvent.change(screen.getByLabelText("Code from your email"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => screen.getByText("Episode one"));
    expect(readSession("maya")?.session).toBe("vs-1");
    expect(readSession("other")).toBeNull();
    const continueCall = calls.find((c) => c.url.endsWith("/continue"));
    expect(continueCall?.headers["X-OTT-Viewer"]).toBe("vs-1");
    expect(screen.getByText("Episode one").closest("a")?.getAttribute("href")).toBe("/c/maya/t1");
  });

  it("deletes the account after a confirmation and forgets the session", async () => {
    writeSession("maya", { session: "vs-1", expiresAt: 4102444800, name: "ana" });
    const calls = stubFetch((url, method) => {
      if (method === "DELETE") return { status: 200, body: { data: { deleted: true, history_deleted: 3 } } };
      return { status: 200, body: { data: { items: [] } } };
    });
    render(<ViewerAccount handle="maya" />);
    fireEvent.click(await screen.findByRole("button", { name: "Delete my account" }));
    fireEvent.click(screen.getByRole("button", { name: "Yes, delete my account and history" }));
    await waitFor(() => screen.getByText("Your account and watch history on this channel were deleted."));
    expect(readSession("maya")).toBeNull();
    expect(calls.some((c) => c.method === "DELETE" && c.url.endsWith("/ott/viewers/maya/me"))).toBe(true);
  });

  it("drops a session the server no longer accepts", async () => {
    writeSession("maya", { session: "stale", expiresAt: 4102444800, name: "ana" });
    stubFetch(() => ({ status: 401, body: { message: "Sign in to this channel to continue." } }));
    render(<ViewerAccount handle="maya" />);
    await waitFor(() => screen.getByRole("button", { name: "Send code" }));
    expect(readSession("maya")).toBeNull();
  });
});

describe("resume tracking", () => {
  it("saves the position every 10 s while playing and on pause", () => {
    vi.useFakeTimers();
    const video = document.createElement("video");
    Object.defineProperty(video, "paused", { value: false, configurable: true });
    Object.defineProperty(video, "duration", { value: 600, configurable: true });
    const saved: number[] = [];
    const stop = trackProgress(video, "maya", "vs-1", "t1", async (_h, _s, _t, at) => {
      saved.push(at);
      return {} as never;
    });
    video.currentTime = 12.7;
    vi.advanceTimersByTime(10_000);
    video.currentTime = 25;
    video.dispatchEvent(new Event("pause"));
    stop();
    expect(saved).toEqual([12, 25]);
  });
});

describe("copy", () => {
  it("passes the copy denylist", () => {
    const web = path.resolve(__dirname, "../../..");
    const denylist = JSON.parse(fs.readFileSync(path.resolve(web, "../../policy/copy-denylist.json"), "utf8")) as Denylist;
    const files = ["src/features/ott-auth/ViewerAccount.tsx", "src/features/ott-auth/scribase-auth.ts",
      "src/features/ott-plans/PlanUsage.tsx", "src/features/ott-plans/api.ts"];
    const units = files.flatMap((rel) => sourceUnits(fs.readFileSync(path.join(web, rel), "utf8"), rel).units);
    expect(checkUnits(denylist, units, { flags: {} }).filter((h) => h.severity === "error")).toEqual([]);
  });
});

describe("TvApprove", () => {
  it("approves the TV code for the signed-in viewer", async () => {
    const { TvApprove } = await import("./TvApprove");
    writeSession("maya", { session: "vs-1", expiresAt: 4102444800, name: "ana" });
    const calls = stubFetch(() => ({ status: 200, body: { data: { approved: true } } }));
    render(<TvApprove handle="maya" />);
    fireEvent.change(screen.getByLabelText("Code on your TV"), { target: { value: "k7m-4qx" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in TV" }));
    await waitFor(() => screen.getByText("Your TV is signed in. You can put your phone away."));
    expect(calls[0]?.url.endsWith("/ott/viewers/maya/tv-codes/approve")).toBe(true);
    expect(calls[0]?.headers["X-OTT-Viewer"]).toBe("vs-1");
    expect(calls[0]?.body).toEqual({ user_code: "k7m-4qx" });
  });

  it("asks for sign-in first", async () => {
    const { TvApprove } = await import("./TvApprove");
    render(<TvApprove handle="maya" />);
    expect(screen.getByLabelText("Email")).toBeTruthy();
  });
});
