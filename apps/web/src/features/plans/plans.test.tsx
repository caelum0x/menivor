import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const auth = {
  isLoaded: true,
  isSignedIn: true,
  getToken: async (): Promise<string | null> => "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1In0.sig",
};
vi.mock("@clerk/nextjs", () => ({ useAuth: () => auth, UserButton: () => null }));

import {
  FALLBACK_CATALOG,
  formatUsd,
  savingsVsPacks,
  type MonthlyCatalog,
  type MyPlan,
} from "./api";
import { PlanUpsell, UPSELL_SNOOZE_MS, isSnoozed, upsellOffer } from "./PlanUpsell";
import { renewalLine } from "./MyMonthlyPlan";

const onSale: MonthlyCatalog = {
  ...FALLBACK_CATALOG,
  plans: FALLBACK_CATALOG.plans.map((p) => ({ ...p, available: { month: true, year: true } })),
};

const noPlan: MyPlan = {
  plan: null,
  status: "none",
  renews: false,
  cancel_at_period_end: false,
  current_period_end: null,
  included_left: 0,
  credits: 1,
  reels_used_30d: 3,
  can_manage: false,
  low_credits: true,
  recommended_plan: "creator",
};

const onCreator: MyPlan = {
  ...noPlan,
  plan: { plan_key: "creator", name: "Creator", interval: "month", price_cents: 1500, period_reels: 35 },
  status: "active",
  renews: true,
  current_period_end: "2026-10-25T12:00:00Z",
  included_left: 10,
  credits: 12,
  can_manage: true,
  low_credits: false,
  recommended_plan: "pro",
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("plan pricing", () => {
  it("every plan beats the best pack per reel", () => {
    for (const plan of FALLBACK_CATALOG.plans) {
      expect(plan.per_reel_cents.month).toBeLessThan(FALLBACK_CATALOG.best_pack_per_reel_cents);
      expect(plan.per_reel_cents.year).toBeLessThan(plan.per_reel_cents.month);
      expect(plan.yearly_cents).toBe(plan.monthly_cents * 10);
    }
  });

  it("formats prices and savings", () => {
    expect(formatUsd(1500)).toBe("$15");
    expect(formatUsd(43)).toBe("$0.43");
    const creator = FALLBACK_CATALOG.plans[0]!;
    expect(savingsVsPacks(creator, "month", 49)).toBeGreaterThan(0);
    expect(savingsVsPacks(creator, "month", 0)).toBe(0);
  });
});

describe("upsellOffer", () => {
  it("offers nothing while no plan is on sale", () => {
    expect(upsellOffer(FALLBACK_CATALOG, noPlan, "after_reel")).toBeNull();
  });

  it("offers the recommended plan to non-subscribers", () => {
    const offer = upsellOffer(onSale, noPlan, "out_of_credits");
    expect(offer?.kind).toBe("subscribe");
    expect(offer?.plan.plan_key).toBe("creator");
  });

  it("skips low-credit upsell when the user is not low", () => {
    expect(upsellOffer(onSale, { ...noPlan, low_credits: false }, "low_credits")).toBeNull();
  });

  it("offers subscribers an upgrade only when short, never after a reel", () => {
    expect(upsellOffer(onSale, onCreator, "after_reel")).toBeNull();
    const offer = upsellOffer(onSale, onCreator, "out_of_credits");
    expect(offer).toEqual({ kind: "upgrade", plan: expect.objectContaining({ plan_key: "pro" }) });
  });
});

describe("after-reel upsell", () => {
  it("waits for the third finished reel", () => {
    expect(upsellOffer(onSale, { ...noPlan, reels_rendered: 2 }, "after_reel")).toBeNull();
    expect(upsellOffer(onSale, noPlan, "after_reel")).toBeNull();
    expect(upsellOffer(onSale, { ...noPlan, reels_rendered: 3 }, "after_reel")?.kind).toBe("subscribe");
  });

  it("stays hidden while a dismissal is fresh", () => {
    const now = 1_800_000_000_000;
    expect(isSnoozed(null, now)).toBe(false);
    expect(isSnoozed("garbage", now)).toBe(false);
    expect(isSnoozed(String(now - 1000), now)).toBe(true);
    expect(isSnoozed(String(now - UPSELL_SNOOZE_MS), now)).toBe(false);
  });
});

describe("renewalLine", () => {
  it("states the renewal date and price", () => {
    expect(renewalLine(onCreator)).toBe("Renews Oct 25, 2026 at $15/month.");
  });

  it("says nothing else is charged once renewal is off", () => {
    expect(renewalLine({ ...onCreator, renews: false, cancel_at_period_end: true })).toContain(
      "nothing else is charged",
    );
  });
});

describe("PlanUpsell", () => {
  function stubApi(mine: MyPlan) {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const body = url.endsWith("/billing/monthly-plans")
          ? { status: 200, data: onSale }
          : { status: 200, data: mine };
        return { ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) };
      }),
    );
  }

  it("after the third reel shows one action with the real count, and can be dismissed", async () => {
    window.localStorage.clear();
    stubApi({ ...noPlan, reels_rendered: 3 });
    render(<PlanUpsell reason="after_reel" fallback={<p>fallback</p>} />);
    expect(await screen.findByText(/You have made 3 reels/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /Start Creator/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Yearly/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Not now" }));
    expect(screen.queryByTestId("plan-upsell")).toBeNull();
    expect(screen.getByText("fallback")).toBeTruthy();
    cleanup();
    render(<PlanUpsell reason="after_reel" />);
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByTestId("plan-upsell")).toBeNull();
    window.localStorage.clear();
  });

  it("before the third reel renders the fallback only", async () => {
    stubApi({ ...noPlan, reels_rendered: 2 });
    render(<PlanUpsell reason="after_reel" fallback={<p>fallback</p>} />);
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByTestId("plan-upsell")).toBeNull();
    expect(screen.getByText("fallback")).toBeTruthy();
  });

  it("renders clear price and renewal terms, and starts checkout in one click", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push(`${init?.method ?? "GET"} ${url}`);
        const body = url.endsWith("/billing/monthly-plans")
          ? { status: 200, data: onSale }
          : url.endsWith("/billing/monthly-plan")
            ? { status: 200, data: noPlan }
            : { status: 200, data: { checkout_url: "https://checkout.creem.io/x" } };
        return { ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) };
      }),
    );
    render(<PlanUpsell reason="out_of_credits" />);
    const button = await screen.findByRole("button", { name: /Start Creator, \$15\/month/ });
    expect(screen.getByText(/Renews automatically until you cancel/)).toBeTruthy();
    expect(screen.getByText(/do not roll over/)).toBeTruthy();
    fireEvent.click(button);
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://checkout.creem.io/x"));
    expect(calls.some((c) => c.startsWith("POST") && c.endsWith("/billing/monthly-plan/checkout"))).toBe(
      true,
    );
  });
});
