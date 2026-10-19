import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TRACKED_BRIEF_KEY } from "./api";
import { CompetitorTracker } from "./CompetitorTracker";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "test-token" }) }));
const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const EMOJI = /\p{Extended_Pictographic}/u;

function jsonResponse(body: unknown): Response {
  return { ok: true, status: 200, statusText: "OK", text: async () => JSON.stringify(body), headers: { get: () => null } } as unknown as Response;
}

const AD = (id: string, tier: string, days: number) => ({
  id, brand_id: "b1", brand_name: "Brewly", source: "meta", advertiser: "Brewly", body: `Copy ${id}`, title: `Title ${id}`,
  page_url: `https://www.facebook.com/ads/library/?id=${id}`, media_url: "", thumbnail_url: "", platforms: ["facebook"],
  started_at: null, stopped_at: null, active: true, is_new: false, days_running: days, tier, scaled: false, score: 50, can_clone: true,
});

const OVERVIEW = {
  brands: [{ id: "b1", name: "Brewly", meta_page_ids: ["111"], tiktok_advertiser_ids: [], search_terms: "", countries: ["DE"],
             last_checked_at: null, last_error: "", ads: 2, active: 2, new: 1, winners: 1 }],
  sources: [
    { id: "meta", name: "Meta Ad Library", connected: true, detail: "Official Ad Library API." },
    { id: "tiktok", name: "TikTok ad library", connected: false, detail: "The owner applies for the TikTok Commercial Content API." },
  ],
  alerts: 1,
};

function route(fetchMock: ReturnType<typeof vi.fn>) {
  fetchMock.mockImplementation(async (url: string, init: RequestInit) => {
    if (String(url).endsWith("/competitors")) return jsonResponse({ data: OVERVIEW });
    if (String(url).includes("/competitors/ads?") || String(url).endsWith("/competitors/ads"))
      return jsonResponse({ data: { ads: [AD("901", "winner", 45), AD("902", "testing", 3)] } });
    if (String(url).includes("/clone") && init.method === "POST")
      return jsonResponse({ data: { brief: { version: 1 }, source_url: "https://www.facebook.com/ads/library/?id=901", ad_clone_path: "/ad-clone?from=tracked" } });
    return jsonResponse({ data: {} });
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  push.mockReset();
  window.sessionStorage.clear();
});

describe("competitor tracker", () => {
  it("renders sources, alerts and tiers without emoji", async () => {
    const fetchMock = vi.fn();
    route(fetchMock);
    vi.stubGlobal("fetch", fetchMock);
    render(<CompetitorTracker />);
    expect(await screen.findByText("Winner")).toBeInTheDocument();
    expect(screen.getAllByText("Testing").length).toBeGreaterThan(0);
    expect(screen.getByText("45 days running")).toBeInTheDocument();
    expect(screen.getByText(/not connected yet/)).toBeInTheDocument();
    expect(screen.getByText(/1 new ads since the last check/)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /View in ad library/ })[0]).toHaveAttribute("rel", "noopener noreferrer");
    expect(EMOJI.test(document.body.textContent ?? "")).toBe(false);
  });

  it("Clone this stores the brief and opens Ad Clone", async () => {
    const fetchMock = vi.fn();
    route(fetchMock);
    vi.stubGlobal("fetch", fetchMock);
    render(<CompetitorTracker />);
    const buttons = await screen.findAllByRole("button", { name: /Clone this/ });
    fireEvent.click(buttons[0]!);
    await waitFor(() => expect(push).toHaveBeenCalledWith("/ad-clone?from=tracked"));
    const stored = JSON.parse(window.sessionStorage.getItem(TRACKED_BRIEF_KEY) ?? "{}");
    expect(stored.brief).toEqual({ version: 1 });
    expect(stored.source_url).toContain("901");
  });

  it("filters by tier", async () => {
    const fetchMock = vi.fn();
    route(fetchMock);
    vi.stubGlobal("fetch", fetchMock);
    render(<CompetitorTracker />);
    await screen.findByText("Winner");
    fireEvent.click(screen.getByRole("button", { name: "Winners" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u).includes("tier=winner"))).toBe(true));
  });
});
