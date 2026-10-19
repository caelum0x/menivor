import * as React from "react";
import * as fs from "node:fs";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { checkUnits, type Denylist } from "@/src/shared/policy/copy-check";
import { sourceUnits } from "@/src/shared/policy/source-units";
import { writeSession } from "@/src/features/ott-auth";
import { socketUrl, subscribe } from "./realtime";
import { LiveChat } from "./LiveChat";
import { latencySeconds } from "./LivePlayer";

class FakeSocket {
  static last: FakeSocket | null = null;
  readyState = 0;
  sent: unknown[] = [];
  onopen: ((ev: Event) => void) | null = null;
  onclose: ((ev: CloseEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  constructor(readonly url: string) {
    FakeSocket.last = this;
  }
  send(data: string) {
    this.sent.push(JSON.parse(data));
  }
  close() {
    this.readyState = 3;
  }
  open() {
    this.readyState = 1;
    this.onopen?.(new Event("open"));
  }
  push(frame: unknown) {
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(frame) }));
  }
}

beforeEach(() => {
  window.localStorage.clear();
  process.env.NEXT_PUBLIC_SCRIBASE_VIEWERS_URL = "https://viewers.scribase.example";
  process.env.NEXT_PUBLIC_SCRIBASE_VIEWERS_ANON_KEY = "anon";
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("Scribase Realtime client", () => {
  it("joins the broadcast topic, beats, and delivers chat and hide events", () => {
    vi.useFakeTimers();
    const chats: unknown[] = [];
    const hides: string[] = [];
    const states: boolean[] = [];
    const stop = subscribe("https://viewers.scribase.example", "anon", "ott-live:s1",
      { onChat: (m) => chats.push(m), onHide: (id) => hides.push(id), onState: (o) => states.push(o) },
      (url) => new FakeSocket(url) as never);
    const socket = FakeSocket.last!;
    expect(socket.url).toBe("wss://viewers.scribase.example/realtime/v1/websocket?apikey=anon&vsn=1.0.0");
    socket.open();
    expect(socket.sent[0]).toMatchObject({ topic: "realtime:ott-live:s1", event: "phx_join" });
    vi.advanceTimersByTime(25_000);
    expect(socket.sent[1]).toMatchObject({ topic: "phoenix", event: "heartbeat" });
    socket.push({ topic: "realtime:ott-live:s1", event: "broadcast", payload: { event: "chat", payload: { id: "m1", name: "ana", body: "hi", at: null } } });
    socket.push({ topic: "realtime:ott-live:other", event: "broadcast", payload: { event: "chat", payload: { id: "x" } } });
    socket.push({ topic: "realtime:ott-live:s1", event: "broadcast", payload: { event: "hide", payload: { id: "m1" } } });
    expect(chats).toEqual([{ id: "m1", name: "ana", body: "hi", at: null }]);
    expect(hides).toEqual(["m1"]);
    expect(states).toEqual([true]);
    stop();
    expect(socket.readyState).toBe(3);
    expect(socketUrl("http://localhost:54321/", "k")).toBe("ws://localhost:54321/realtime/v1/websocket?apikey=k&vsn=1.0.0");
  });
});

describe("LiveChat", () => {
  it("reads chat, falls back to polling without a socket and posts as the signed-in viewer", async () => {
    vi.stubGlobal("WebSocket", undefined);
    writeSession("maya", { session: "vs-1", expiresAt: 4102444800, name: "ana" });
    const calls: { url: string; init?: RequestInit }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      if (init?.method === "POST") {
        return { ok: true, status: 200, json: async () => ({ data: { id: "m2", name: "ana", body: "hello", at: "2026-10-05T10:00:01+00:00" } }) } as Response;
      }
      return { ok: true, status: 200, json: async () => ({ data: { messages: [{ id: "m1", name: "bo", body: "first", at: "2026-10-05T10:00:00+00:00" }], topic: "ott-live:s1" } }) } as Response;
    }));
    render(<LiveChat handle="maya" streamId="s1" />);
    await waitFor(() => screen.getByText("first"));
    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "hello" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => screen.getByText("hello"));
    const post = calls.find((c) => c.init?.method === "POST");
    expect((post?.init?.headers as Record<string, string>)["X-OTT-Viewer"]).toBe("vs-1");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("asks a viewer who is not signed in to sign in before chatting", async () => {
    vi.stubGlobal("WebSocket", undefined);
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ data: { messages: [] } }) }) as Response));
    render(<LiveChat handle="maya" streamId="s1" />);
    expect(screen.getByLabelText("Email")).toBeTruthy();
  });
});

describe("latency", () => {
  it("uses program dates when the browser has them, else the distance to the live edge", () => {
    const video = document.createElement("video") as HTMLVideoElement & { getStartDate?: () => Date };
    Object.defineProperty(video, "currentTime", { value: 100, configurable: true });
    video.getStartDate = () => new Date(1_000_000);
    expect(latencySeconds(video, 1_000_000 + 105_000)).toBe(5);
    const edge = document.createElement("video");
    Object.defineProperty(edge, "currentTime", { value: 50, configurable: true });
    Object.defineProperty(edge, "seekable", { value: { length: 1, end: () => 53 }, configurable: true });
    expect(latencySeconds(edge)).toBe(4);
  });
});

describe("copy", () => {
  it("passes the copy denylist", () => {
    const web = path.resolve(__dirname, "../../..");
    const denylist = JSON.parse(fs.readFileSync(path.resolve(web, "../../policy/copy-denylist.json"), "utf8")) as Denylist;
    const files = ["src/features/ott-live-chat/LiveChat.tsx", "src/features/ott-live-chat/StudioLive.tsx",
      "src/features/ott-live-chat/LiveNow.tsx", "src/features/ott-live-chat/LivePlayer.tsx",
      "app/(ott)/c/[handle]/live/[streamId]/page.tsx"];
    const units = files.flatMap((rel) => sourceUnits(fs.readFileSync(path.join(web, rel), "utf8"), rel).units);
    // Live copy renders only behind OTT_LIVE_LIVE (the page 404s and the studio panel hides without it).
    expect(checkUnits(denylist, units, { flags: { OTT_LIVE_LIVE: true } }).filter((h) => h.severity === "error")).toEqual([]);
    const linear = ["src/features/ott-linear/StudioLinear.tsx", "src/features/ott-linear/LinearWatch.tsx",
      "app/(ott)/linear/[slug]/page.tsx"];
    const linearUnits = linear.flatMap((rel) => sourceUnits(fs.readFileSync(path.join(web, rel), "utf8"), rel).units);
    expect(checkUnits(denylist, linearUnits, { flags: {} }).filter((h) => h.severity === "error")).toEqual([]);
  });
});

void act;
