import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  DEFAULT_FILTERS,
  MAX_REPLY_CHARS,
  getThread,
  listThreads,
  mergeThreads,
  readableApiMessage,
  readablePlatforms,
  replaceThread,
  replyAffordance,
  sendReply,
  setThreadStatus,
  syncInbox,
  threadQuery,
  validateReply,
  type InboxThread,
  type PlatformCapability,
} from "@/lib/social-inbox";
import { ApiError } from "@/src/shared/api";

type FetchMock = ReturnType<typeof vi.fn>;
let fetchMock: FetchMock;

function respond(data: unknown, status = 200): void {
  fetchMock.mockResolvedValueOnce({
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(status < 300 ? { status, data } : { status, message: data }),
    headers: { get: () => null },
  });
}

function lastCall(): { url: string; init: RequestInit } {
  const [url, init] = fetchMock.mock.calls[fetchMock.mock.calls.length - 1] as [string, RequestInit];
  return { url, init };
}

function thread(overrides: Partial<InboxThread> = {}): InboxThread {
  return {
    id: "t1",
    platform: "youtube",
    platform_label: "YouTube",
    kind: "comment",
    post_id: "p1",
    post_title: "Launch reel",
    author_name: "Ada",
    text: "Love it",
    like_count: 0,
    message_count: 1,
    status: "needs_reply",
    last_message_at: null,
    replied_at: null,
    reply_via: "",
    reply_text: "",
    reply: { mode: "api", reason: "", open_url: "https://youtube.com/watch?v=1" },
    ...overrides,
  };
}

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("social inbox client", () => {
  it("builds the thread query from filters", () => {
    expect(threadQuery(DEFAULT_FILTERS)).toBe("status=needs_reply&limit=30&offset=0");
    expect(threadQuery({ platform: "x", status: "all", kind: "dm" }, 60)).toBe(
      "platform=x&status=all&kind=dm&limit=30&offset=60",
    );
    expect(threadQuery(DEFAULT_FILTERS, -5)).toContain("offset=0");
  });

  it("lists threads with the caller's key", async () => {
    respond({ threads: [thread()], total: 1, limit: 30, offset: 0 });
    const page = await listThreads(DEFAULT_FILTERS, 0, { token: "k_user" });
    expect(page.total).toBe(1);
    const { url, init } = lastCall();
    expect(url).toMatch(/\/social-inbox\/threads\?status=needs_reply&limit=30&offset=0$/);
    expect((init.headers as Record<string, string>)["x-api-key"]).toBe("k_user");
  });

  it("encodes the thread id and posts trimmed reply text", async () => {
    respond({ ...thread(), messages: [] });
    await sendReply("a/b", "  thanks!  ", { token: "k" });
    const { url, init } = lastCall();
    expect(url).toMatch(/\/social-inbox\/threads\/a%2Fb\/reply$/);
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ text: "thanks!" });
  });

  it("sets status with reply_text", async () => {
    respond({ ...thread({ status: "replied" }), messages: [] });
    const updated = await setThreadStatus("t1", "replied", " sent on app ");
    expect(updated.status).toBe("replied");
    expect(JSON.parse(String(lastCall().init.body))).toEqual({ status: "replied", reply_text: "sent on app" });
  });

  it("syncs with POST and surfaces rate limits as ApiError", async () => {
    respond("slow down", 429);
    await expect(syncInbox()).rejects.toBeInstanceOf(ApiError);
    expect(lastCall().init.method).toBe("POST");
  });

  it("returns thread detail", async () => {
    respond({ ...thread(), messages: [{ id: "m1", author: "Ada", text: "hi", at: null, from_me: false, via: "" }] });
    const detail = await getThread("t1");
    expect(detail.messages).toHaveLength(1);
  });
});

describe("social inbox helpers", () => {
  it("offers in-app send only when the platform and server allow it", () => {
    expect(replyAffordance(thread(), true).canSendInApp).toBe(true);
    const off = replyAffordance(thread(), false);
    expect(off.canSendInApp).toBe(false);
    expect(off.note).toMatch(/turned off/);
    expect(off.openUrl).toBe("https://youtube.com/watch?v=1");
    const manual = replyAffordance(
      thread({ reply: { mode: "manual", reason: "", open_url: "" }, platform_label: "TikTok" }),
      true,
    );
    expect(manual.canSendInApp).toBe(false);
    expect(manual.note).toMatch(/TikTok does not let apps post replies/);
  });

  it("validates reply length", () => {
    expect(validateReply("   ")).toEqual({ ok: false, error: "Write a reply first." });
    expect(validateReply(" ok ")).toEqual({ ok: true, text: "ok" });
    expect(validateReply("x".repeat(MAX_REPLY_CHARS + 1)).ok).toBe(false);
  });

  it("keeps only connected platforms with read access", () => {
    const base: PlatformCapability = {
      platform: "youtube",
      label: "YouTube",
      connected: true,
      comments: { read: "yes", reply: "yes", note: "" },
      dms: { read: "not_offered", reply: "not_offered", note: "" },
      needs_reconnect: false,
      reconnect_scopes: "",
    };
    const list = readablePlatforms([
      base,
      { ...base, platform: "x", connected: false },
      { ...base, platform: "tiktok", comments: { read: "needs_permission", reply: "no" as never, note: "" } },
    ]);
    expect(list.map((p) => p.platform)).toEqual(["youtube"]);
  });

  it("merges pages without duplicates and without mutating", () => {
    const current = [thread({ id: "a" })];
    const merged = mergeThreads(current, [thread({ id: "a" }), thread({ id: "b" })]);
    expect(merged.map((t) => t.id)).toEqual(["a", "b"]);
    expect(current).toHaveLength(1);
  });

  it("drops a thread that no longer matches the status filter", () => {
    const list = [thread({ id: "a" }), thread({ id: "b" })];
    const updated = thread({ id: "a", status: "done" });
    expect(replaceThread(list, updated, DEFAULT_FILTERS).map((t) => t.id)).toEqual(["b"]);
    expect(replaceThread(list, updated, { ...DEFAULT_FILTERS, status: "all" })[0]?.status).toBe("done");
  });

  it("strips request ids from API messages", () => {
    expect(readableApiMessage("0f3c9a1b2c3d4e5f60718293a4b5c6d7: thread not found", "x")).toBe("Thread not found");
    expect(readableApiMessage("Validation: bad input", "x")).toBe("Validation: bad input");
    expect(readableApiMessage("", "Fallback")).toBe("Fallback");
    expect(readableApiMessage("plain message", "x")).toBe("Plain message");
  });
});
