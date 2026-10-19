import { afterEach, describe, expect, it, vi } from "vitest";

import {
  askAgent,
  cardStatus,
  connectAdKey,
  decideProposal,
  scopeQuery,
  validateSecret,
  type ProviderCard,
} from "./api";

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    statusText: "OK",
    text: async () => JSON.stringify({ status: 200, data: body }),
    headers: { get: () => null },
  } as unknown as Response;
}

function card(partial: Partial<ProviderCard>): ProviderCard {
  return {
    provider: "meta", label: "Meta", capabilities: "", auth: "oauth", configured: true, delivery: true,
    connected: false, status: "not_connected", token_hint: "", last_error: null, account_count: 0, accounts: [],
    ...partial,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("cardStatus", () => {
  it("matches the Creatify card states", () => {
    expect(cardStatus(card({}))).toBe("Not connected");
    expect(cardStatus(card({ configured: false }))).toBe("Not available yet");
    expect(cardStatus(card({ configured: false, auth: "api_key" }))).toBe("Not connected");
    expect(cardStatus(card({ connected: true }))).toBe("No Meta accounts");
    expect(cardStatus(card({ connected: true, account_count: 1 }))).toBe("1 account");
    expect(cardStatus(card({ connected: true, account_count: 3 }))).toBe("3 accounts");
    expect(cardStatus(card({ connected: true, status: "needs_reauth", account_count: 2 }))).toBe("Reconnect needed");
  });
});

describe("scopeQuery and validateSecret", () => {
  it("builds the workspace and brand space query", () => {
    expect(scopeQuery()).toBe("");
    expect(scopeQuery({ workspaceId: "ws1", brandSpaceId: "b1" })).toBe("?workspace_id=ws1&brand_space_id=b1");
    expect(scopeQuery({ workspaceId: null }, { days: "7" })).toBe("?days=7");
  });

  it("rejects short or spaced keys", () => {
    expect(validateSecret("short")).toMatch(/full/);
    expect(validateSecret("has a space in it")).toMatch(/spaces/);
    expect(validateSecret("sk-ads-1234567890")).toBeNull();
  });
});

describe("requests", () => {
  it("sends the API key once and scopes by workspace", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ provider: "openai_ads", credits_granted: 50 }));
    vi.stubGlobal("fetch", fetchMock);
    const out = await connectAdKey("openai_ads", "  sk-ads-123456  ", { workspaceId: "ws1" }, { token: "t" });
    expect(out.credits_granted).toBe(50);
    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(String(url)).toContain("/integrations/ads/openai_ads/key?workspace_id=ws1");
    expect(JSON.parse(init.body)).toEqual({ api_key: "sk-ads-123456" });
  });

  it("asks the agent and decides proposals through the approval routes", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ answer: "ok", used_llm: true, credits_granted: 10, suggestions: [] }))
      .mockResolvedValueOnce(jsonResponse({ item: { id: "p1", status: "executed" } }));
    vi.stubGlobal("fetch", fetchMock);
    expect((await askAgent(" How are ads? ", {}, { token: "t" })).answer).toBe("ok");
    await decideProposal("p1", "approve", { workspaceId: "ws1" }, { token: "t" });
    expect(String(fetchMock.mock.calls[1]?.[0])).toContain("/integrations/agent/proposals/p1/approve?workspace_id=ws1");
  });
});
