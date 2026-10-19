import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";

const auth = { isLoaded: true, isSignedIn: false, getToken: async (): Promise<string | null> => null };
vi.mock("@clerk/nextjs", () => ({ useAuth: () => auth, UserButton: () => null }));

import {
  FALLBACK_CATALOG,
  catalogFrom,
  fallbackAvailability,
  loadCatalogForRender,
  type MonthlyCatalog,
} from "./api";
import { MonthlyPlans } from "./MonthlyPlans";
import { resetPaymentsModeCache } from "@/src/shared/payments/mode";

const LIVE_PAYLOAD = {
  plans: [
    {
      plan_key: "creator",
      name: "Creator",
      rank: 1,
      currency: "USD",
      monthly_cents: 1500,
      yearly_cents: 15000,
      monthly_reels: 35,
      yearly_reels: 420,
      per_reel_cents: { month: 43, year: 36 },
      available: { month: true, year: true },
    },
    {
      plan_key: "pro",
      name: "Pro",
      rank: 2,
      currency: "USD",
      monthly_cents: 3900,
      yearly_cents: 39000,
      monthly_reels: 100,
      yearly_reels: 1200,
      per_reel_cents: { month: 39, year: 32 },
      available: { month: true, year: false },
    },
  ],
  yearly_months_charged: 10,
  best_pack_per_reel_cents: 49,
};

const offSale: MonthlyCatalog = {
  ...FALLBACK_CATALOG,
  plans: FALLBACK_CATALOG.plans.map((p) => ({ ...p, available: { month: false, year: false } })),
};

function jsonResponse(body: unknown, ok = true) {
  return {
    ok,
    status: ok ? 200 : 500,
    json: async () => body,
    text: async () => JSON.stringify(body),
    headers: new Headers(),
  } as unknown as Response;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  resetPaymentsModeCache();
});

describe("fallbackAvailability", () => {
  it("is off unless the env says the plans are on sale", () => {
    expect(fallbackAvailability(undefined)).toEqual({ month: false, year: false });
    expect(fallbackAvailability("")).toEqual({ month: false, year: false });
    expect(fallbackAvailability("0")).toEqual({ month: false, year: false });
    expect(fallbackAvailability("1")).toEqual({ month: true, year: true });
    expect(fallbackAvailability("true")).toEqual({ month: true, year: true });
    expect(fallbackAvailability("month")).toEqual({ month: true, year: false });
    expect(fallbackAvailability("month, year")).toEqual({ month: true, year: true });
  });
});

describe("catalogFrom", () => {
  it("keeps the API's availability per plan and interval", () => {
    const catalog = catalogFrom(LIVE_PAYLOAD)!;
    expect(catalog.plans.map((p) => p.plan_key)).toEqual(["creator", "pro"]);
    expect(catalog.plans[0]!.available).toEqual({ month: true, year: true });
    expect(catalog.plans[1]!.available).toEqual({ month: true, year: false });
  });

  it("treats anything but an explicit true as not on sale", () => {
    const raw = {
      plans: [{ ...LIVE_PAYLOAD.plans[0], available: { month: "true", year: 1 } }],
    };
    expect(catalogFrom(raw)!.plans[0]!.available).toEqual({ month: false, year: false });
  });

  it("rejects payloads with no usable plans", () => {
    expect(catalogFrom(null)).toBeNull();
    expect(catalogFrom({ plans: [] })).toBeNull();
    expect(catalogFrom({ plans: [{ plan_key: "enterprise" }] })).toBeNull();
  });
});

describe("loadCatalogForRender", () => {
  it("reads the live catalog from the API envelope", async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ status: 200, data: LIVE_PAYLOAD }));
    const catalog = await loadCatalogForRender(fetchImpl as unknown as typeof fetch, "https://api.test/v1");
    expect(fetchImpl).toHaveBeenCalledWith("https://api.test/v1/billing/monthly-plans", expect.any(Object));
    expect(catalog?.plans[0]!.available.month).toBe(true);
  });

  it("returns null (render the fallback) when the API fails or is unreachable", async () => {
    const failing = vi.fn(async () => jsonResponse({ status: 500 }, false));
    expect(await loadCatalogForRender(failing as unknown as typeof fetch, "x")).toBeNull();
    const throwing = vi.fn(async () => {
      throw new TypeError("network down");
    });
    expect(await loadCatalogForRender(throwing as unknown as typeof fetch, "x")).toBeNull();
  });
});

describe("MonthlyPlans on the pricing page", () => {
  it("renders Start buttons on first render when the server-read catalog is on sale", () => {
    // The client refresh never answers, so what we see is the first render.
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    render(<MonthlyPlans initialCatalog={catalogFrom(LIVE_PAYLOAD)} />);
    expect(screen.getByRole("button", { name: "Start Creator" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Start Pro" })).toBeEnabled();
    expect(screen.queryByText("Not on sale yet")).toBeNull();
  });

  it("says Not on sale yet only when the API reports the plan unavailable", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    render(<MonthlyPlans initialCatalog={offSale} />);
    expect(screen.getAllByRole("button", { name: "Not on sale yet" })).toHaveLength(3);
  });

  it("switches from the fallback to Start once the live catalog loads", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        String(url).endsWith("/billing/monthly-plans")
          ? jsonResponse({ status: 200, data: LIVE_PAYLOAD })
          : jsonResponse({ status: 200, data: {} }),
      ),
    );
    render(<MonthlyPlans initialCatalog={offSale} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Start Creator" })).toBeEnabled());
  });
});

describe("premium packs", () => {
  it("normalizes the status and drops unknown kinds", async () => {
    const { premiumStatusFrom } = await import("./api");
    const status = premiumStatusFrom({
      balances: { premium_voice: 3, ai_video: 150 },
      packs: [
        { key: "premium_voice_25", kind: "premium_voice", credits: 25, price_usd: 9, available: true },
        { key: "ai_video_2000", kind: "ai_video", credits: 2000, price_usd: 20, available: false },
        { key: "mystery", kind: "other", credits: 1, price_usd: 1, available: true },
      ],
    });
    expect(status.balances.premium_voice).toBe(3);
    expect(status.packs.map((p) => p.key)).toEqual(["premium_voice_25", "ai_video_2000"]);
  });

  it("shows a buy button per pack on sale and never the provider name", async () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    const { PremiumPacksView } = await import("./PremiumPacks");
    const { container } = render(
      <PremiumPacksView
        status={{
          balances: { premium_voice: 0, ai_video: 0 },
          packs: [
            { key: "premium_voice_25", kind: "premium_voice", credits: 25, price_usd: 9, available: true },
            { key: "ai_video_2000", kind: "ai_video", credits: 2000, price_usd: 20, available: false },
          ],
        }}
      />,
    );
    expect(screen.getByRole("button", { name: "Buy premium voice" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Not on sale yet" })).toBeDisabled();
    expect(container.textContent).not.toMatch(/elevenlabs|presenter|lip-?sync/i);
  });
});
