import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AdFatigue } from "./AdFatigue";
import { pct } from "./api";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "test-token" }) }));

const EMOJI = /\p{Extended_Pictographic}/u;

function jsonResponse(body: unknown): Response {
  return { ok: true, status: 200, statusText: "OK", text: async () => JSON.stringify(body), headers: { get: () => null } } as unknown as Response;
}

const CREATIVE = {
  ad_account_id: "acc1", ad_account_name: "Brewly Ads", provider: "meta", entity_id: "ad-tired", entity_name: "Summer UGC",
  currency: "USD", spend: 560, days: 14, impressions: 28000,
  series: [{ day: "2026-09-23", ctr: 0.02, frequency: 1.2 }, { day: "2026-09-24", ctr: 0.015, frequency: 2 }, { day: "2026-09-25", ctr: 0.009, frequency: 4.5 }],
  frequency: 4.5, ctr_decay: 0.55, cpa_drift: null, score: 88, status: "fatigued", reasons: ["CTR down 55% from the first days"],
};
const REPORT = {
  since: "2026-09-23", until: "2026-10-06", creatives: [CREATIVE],
  counts: { fatigued: 1, watch: 0, fresh: 0, not_enough_data: 0 }, accounts: [{ id: "acc1", name: "Brewly Ads", provider: "meta" }],
};

afterEach(() => vi.unstubAllGlobals());

describe("ad fatigue", () => {
  it("formats missing metrics as not reported", () => {
    expect(pct(null)).toBe("not reported");
    expect(pct(0.384)).toBe("38%");
  });

  it("shows status, metrics and never invents a zero", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ data: REPORT })));
    render(<AdFatigue />);
    expect(await screen.findByText("Fatigued")).toBeInTheDocument();
    expect(screen.getByText("55%")).toBeInTheDocument();
    expect(screen.getByText("not reported")).toBeInTheDocument();
    expect(screen.getByText("88 / 100")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Daily CTR for Summer UGC/ })).toBeInTheDocument();
    expect(EMOJI.test(document.body.textContent ?? "")).toBe(false);
  });

  it("Make variations posts and links to Agent", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse({ data: REPORT }));
    fetchMock.mockResolvedValueOnce(jsonResponse({ data: { action: { id: "x", status: "pending", credits_estimate: 15, title: "t" },
      creative: { entity_id: "ad-tired", entity_name: "Summer UGC", score: 88, status: "fatigued" } } }));
    vi.stubGlobal("fetch", fetchMock);
    render(<AdFatigue />);
    fireEvent.click(await screen.findByRole("button", { name: /Make variations/ }));
    expect(await screen.findByText(/3 variations queued for approval \(15 credits\)/)).toBeInTheDocument();
    const [url, init] = fetchMock.mock.calls[1]!;
    expect(String(url)).toContain("/ad-fatigue/variations");
    expect(JSON.parse(init.body as string)).toEqual({ ad_account_id: "acc1", entity_id: "ad-tired" });
    expect(screen.getByRole("link", { name: "Approve in Agent" })).toHaveAttribute("href", "/agent");
  });

  it("empty state points to integrations", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ data: { ...REPORT, creatives: [], accounts: [] } })));
    render(<AdFatigue />);
    expect(await screen.findByRole("link", { name: "Connect an ad account" })).toHaveAttribute("href", "/settings/integrations");
  });
});
