import { afterEach, describe, expect, it, vi } from "vitest";

import { draftCampaign, listDraftableAccounts, validateDraftInput } from "./api";

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    statusText: "OK",
    text: async () => JSON.stringify({ status: 200, data: body }),
    headers: { get: () => null },
  } as unknown as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("validateDraftInput", () => {
  it("requires a name and a positive budget", () => {
    expect(validateDraftInput("", 1000)).toMatch(/Name/);
    expect(validateDraftInput("Launch", 0)).toMatch(/budget/);
    expect(validateDraftInput("Launch", -5)).toMatch(/budget/);
    expect(validateDraftInput("Launch", 1000)).toBeNull();
  });
});

describe("listDraftableAccounts", () => {
  it("keeps only accounts on providers that support campaign drafts", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      ads: {
        providers: [
          { provider: "meta", label: "Meta", campaign_drafts: true,
            accounts: [{ id: "a1", name: "Shop", currency: "USD" }] },
          { provider: "snapchat", label: "Snapchat", campaign_drafts: false,
            accounts: [{ id: "a2", name: "Other", currency: "USD" }] },
        ],
      },
    }));
    vi.stubGlobal("fetch", fetchMock);
    const out = await listDraftableAccounts({ workspaceId: "ws1" });
    expect(out).toEqual([{ id: "a1", provider: "Meta", name: "Shop", currency: "USD" }]);
  });
});

describe("draftCampaign", () => {
  it("sends a trimmed, uppercased, PAUSED-by-default draft request", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      provider: "meta", ad_account_id: "a1", external_id: "cmp_1", name: "Launch", status: "paused",
      manage_url: "https://adsmanager.facebook.com/x",
    }));
    vi.stubGlobal("fetch", fetchMock);
    const out = await draftCampaign("a1", { name: "  Launch  ", dailyBudgetMinor: 2000, countries: ["us", " ca "] },
      { workspaceId: "ws1" }, { token: "t" });
    expect(out.status).toBe("paused");
    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(String(url)).toContain("/integrations/ad-accounts/a1/campaigns/draft?workspace_id=ws1");
    expect(JSON.parse(init.body)).toEqual({
      name: "Launch", daily_budget_minor: 2000, countries: ["US", "CA"], adam_id: "",
    });
  });
});
