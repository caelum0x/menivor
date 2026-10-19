import { afterEach, describe, expect, it, vi } from "vitest";

import {
  applyDecision,
  approveBlocked,
  buildDecisionBody,
  decideApproval,
  listApprovals,
  summarizeResult,
  type ApprovalItem,
  type ApprovalList,
} from "@/lib/approvals";
import {
  buildPostsInput,
  channelQueue,
  checkCompose,
  connectReady,
  createChannelPosts,
  getChannelQueue,
  normalizeEntry,
  parseHashtags,
  problemsOf,
  toConnectInput,
  BLANK_FIELDS,
  type Channel,
  type QueueEntry,
} from "@/lib/channels";
import { cleanApiMessage, readableApiError } from "@/lib/readable-error";
import { ApiError } from "@/src/shared/api/client";

function item(overrides: Partial<ApprovalItem> = {}): ApprovalItem {
  return {
    id: "a1",
    source: "social_reply",
    external_ref: "r1",
    title: "Reply to @sam",
    summary: "",
    risk: "low",
    payload: { editable_fields: ["text"], text: "Thanks!" },
    edited_payload: null,
    status: "pending",
    decided_by: null,
    decided_via: "",
    decided_at: null,
    decision_note: "",
    result: {},
    error: "",
    expires_at: null,
    created_at: null,
    updated_at: null,
    open_url: null,
    can_decide: true,
    ...overrides,
  };
}

function channel(overrides: Partial<Channel> = {}): Channel {
  return {
    id: "c1",
    kind: "telegram",
    kind_label: "Telegram",
    label: "Updates",
    status: "connected",
    target_id: "@updates",
    target_name: "@updates",
    instance_url: "",
    shared: false,
    mine: true,
    can_post: true,
    can_manage: true,
    public_url: "",
    inbox: { reads: false, note: "" },
    caption_max: 4096,
    last_verified_at: null,
    last_error: "",
    ...overrides,
  };
}

function mockFetch(body: unknown, status = 200) {
  const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("approvals decision body", () => {
  it("sends via=mobile and a trimmed note (comment) on reject, never edits", () => {
    const body = buildDecisionBody(item(), "reject", "  off brand  ", "Changed text");
    expect(body).toEqual({ via: "mobile", note: "off brand" });
  });

  it("sends edits only when the approved text actually changed", () => {
    expect(buildDecisionBody(item(), "approve", "", "Thanks!").edits).toBeUndefined();
    expect(buildDecisionBody(item(), "approve", "", "Thanks a lot!").edits).toEqual({ text: "Thanks a lot!" });
  });

  it("ignores edits when the text field is not editable", () => {
    const locked = item({ payload: { text: "x" } });
    expect(buildDecisionBody(locked, "approve", "", "y").edits).toBeUndefined();
  });

  it("caps the note at the server limit", () => {
    expect(buildDecisionBody(item(), "approve", "n".repeat(1500), null).note).toHaveLength(1000);
  });
});

describe("approvals list reducer and gate", () => {
  const list: ApprovalList = {
    items: [item(), item({ id: "a2", source: "publish_hold" })],
    total: 2,
    limit: 25,
    offset: 0,
    pending_count: 2,
    pending_by_source: { social_reply: 1, publish_hold: 1 },
    unavailable_sources: [],
  };

  it("drops a decided item from the pending view and decrements counters", () => {
    const next = applyDecision(list, item({ status: "executed", can_decide: false }), "pending");
    expect(next.items.map((i) => i.id)).toEqual(["a2"]);
    expect(next.pending_count).toBe(1);
    expect(next.total).toBe(1);
    expect(next.pending_by_source.social_reply).toBe(0);
    expect(list.items).toHaveLength(2);
  });

  it("replaces the item in history", () => {
    const next = applyDecision(list, item({ status: "rejected", can_decide: false }), "all");
    expect(next.items[0].status).toBe("rejected");
    expect(next.total).toBe(2);
  });

  it("blocks approving post-scheduling items while publishing is closed", () => {
    expect(approveBlocked(item({ source: "publish_hold" }), false)).toBe(true);
    expect(approveBlocked(item({ source: "publish_hold" }), true)).toBe(false);
    expect(approveBlocked(item({ source: "social_reply" }), false)).toBe(false);
  });

  it("summarises executed results and returns null when empty", () => {
    expect(summarizeResult({})).toBeNull();
    const summary = summarizeResult({
      posts: [{ id: "p1", platform: "telegram", status: "scheduled", channel_label: "Updates" }],
      skipped: [{ platform: "tiktok", message: "Not connected" }],
      job_ids: ["j1"],
      credits: 1,
    });
    expect(summary?.posts[0]).toContain("Telegram (Updates): scheduled");
    expect(summary?.skipped[0]).toBe("Tiktok: Not connected");
    expect(summary?.jobsLabel).toBe("Reel jobs (1 credit)");
  });
});

describe("approvals requests", () => {
  it("lists with filters and posts decisions to the right route", async () => {
    const fetchMock = mockFetch({ status: 200, data: { items: [], total: 0 } });
    await listApprovals({ status: "pending", source: "ad_budget", offset: 25, limit: 25 });
    const listUrl = String(fetchMock.mock.calls[0][0]);
    expect(listUrl).toContain("/approvals?status=pending&limit=25&offset=25&source=ad_budget");

    mockFetch({ status: 200, data: { item: item(), idempotent: false } });
    const outcome = await decideApproval("a/1", "approve", { via: "mobile", note: "ok" });
    expect(outcome.item.id).toBe("a1");
    const decideCall = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(String(decideCall[0])).toContain("/approvals/a%2F1/approve");
    expect(JSON.parse(String((decideCall[1] as RequestInit).body))).toEqual({ via: "mobile", note: "ok" });
  });
});

describe("channels compose", () => {
  it("parses hashtags without #, de-duplicated", () => {
    expect(parseHashtags("#launch, launch  #Indie  dev")).toEqual(["launch", "Indie", "dev"]);
  });

  it("validates channel count, text, caption limit and future time", () => {
    const now = new Date("2026-09-25T10:00:00Z");
    expect(checkCompose([], "hi", null, now).ok).toBe(false);
    expect(checkCompose([channel()], "   ", null, now).ok).toBe(false);
    expect(checkCompose([channel({ caption_max: 5 })], "too long", null, now).reason).toContain("5 characters");
    expect(checkCompose([channel()], "hi", new Date("2026-09-25T09:00:00Z"), now).ok).toBe(false);
    expect(checkCompose([channel({ can_post: false })], "hi", null, now).ok).toBe(false);
    expect(checkCompose([channel()], "hi", new Date("2026-09-26T09:00:00Z"), now).ok).toBe(true);
  });

  it("builds one draft per channel and only schedules when a time is set", () => {
    const now = buildPostsInput([channel(), channel({ id: "c2" })], " hi ", ["a"], null);
    expect(now).toEqual({
      drafts: [
        { channel_id: "c1", caption: "hi", hashtags: ["a"] },
        { channel_id: "c2", caption: "hi", hashtags: ["a"] },
      ],
    });
    const later = buildPostsInput([channel()], "hi", [], new Date("2026-09-26T09:00:00Z"));
    expect(later.scheduled_at).toBe("2026-09-26T09:00:00.000Z");
  });

  it("posts drafts and returns the created posts", async () => {
    const fetchMock = mockFetch({ status: 200, data: { posts: [{ id: "p1", status: "published" }] } });
    const posts = await createChannelPosts({ drafts: [{ channel_id: "c1", caption: "hi", hashtags: [] }] });
    expect(posts).toHaveLength(1);
    expect(String(fetchMock.mock.calls[0][0])).toContain("/publishing/channel-posts");
  });
});

describe("channels queue", () => {
  const raw = [
    { source: "post", id: "p1", target_id: "c1", scheduled_at: "2026-09-26T10:00:00Z", status: "scheduled" },
    { source: "post", id: "p2", target_id: "other", channel_label: "", platforms: ["tiktok"] },
    { source: "native", id: "n1", platforms: ["youtube"] },
    { source: "post", id: "p3", target_id: "c9", channel_label: "Old channel", scheduled_at: "2026-09-27T10:00:00Z" },
    { id: "broken" },
  ];

  it("normalises rows and drops malformed ones", () => {
    expect(normalizeEntry({ id: "broken" })).toBeNull();
    expect(normalizeEntry(raw[0])?.status).toBe("scheduled");
  });

  it("keeps only channel posts, latest first", () => {
    const entries = raw.map(normalizeEntry).filter((e): e is QueueEntry => e !== null);
    expect(channelQueue(entries, new Set(["c1"])).map((e) => e.id)).toEqual(["p3", "p1"]);
  });

  it("requests the calendar window and filters to channels", async () => {
    const fetchMock = mockFetch({ status: 200, data: { entries: raw } });
    const queue = await getChannelQueue(new Set(["c1"]), undefined, new Date("2026-09-25T00:00:00Z"));
    expect(queue.map((e) => e.id)).toEqual(["p3", "p1"]);
    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("/publishing/calendar/entries?start=2026-09-18");
  });
});

describe("channels connect form", () => {
  it("applies the web form minimums per kind", () => {
    expect(connectReady("telegram", { ...BLANK_FIELDS, bot_token: "x".repeat(20), chat_id: "@c" })).toBe(true);
    expect(connectReady("discord", { ...BLANK_FIELDS, webhook_url: "http://x" })).toBe(false);
    expect(connectReady("mastodon", { ...BLANK_FIELDS, instance: "m.s", access_token: "t".repeat(20) })).toBe(true);
  });

  it("maps fields to the kind's connect body", () => {
    expect(toConnectInput("mastodon", { ...BLANK_FIELDS, instance: " m.social ", access_token: " tok " })).toEqual({
      kind: "mastodon",
      instance: "m.social",
      access_token: "tok",
      visibility: "public",
      label: "",
    });
  });

  it("reads 409 problems", () => {
    const err = new ApiError("conflict", 409, { data: { problems: [{ channel_id: "c1", message: "Too long" }] } });
    expect(problemsOf(err)).toEqual([{ channel_id: "c1", message: "Too long" }]);
    expect(problemsOf(new Error("x"))).toEqual([]);
  });
});

describe("readable errors", () => {
  it("strips request ids and maps launch-gate and transport failures", () => {
    expect(cleanApiMessage("0123456789abcdef0123456789abcdef: channel not found")).toBe("Channel not found");
    expect(readableApiError(new ApiError("x", 403, { data: { code: "publishing_closed" } }), "f")).toContain(
      "Publishing is not open",
    );
    expect(readableApiError(new ApiError("x", 0), "f")).toContain("Could not reach Menivor");
    expect(readableApiError(new ApiError("x", 503), "f")).toContain("Nothing was posted");
    expect(readableApiError({}, "fallback")).toBe("fallback");
  });
});
