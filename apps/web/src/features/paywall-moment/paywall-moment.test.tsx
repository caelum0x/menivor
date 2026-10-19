import * as React from "react";
import * as fs from "node:fs";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const auth = {
  isLoaded: true,
  isSignedIn: true,
  getToken: async (): Promise<string | null> => "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1In0.sig",
};
vi.mock("@clerk/nextjs", () => ({ useAuth: () => auth, UserButton: () => null }));

import { PRICING_PLANS } from "@/components/marketing/plans";
import { FALLBACK_CATALOG, type MonthlyCatalog, type MyPlan } from "@/src/features/plans/api";
import { checkUnits, type Denylist } from "@/src/shared/policy/copy-check";
import { sourceUnits } from "@/src/shared/policy/source-units";
import type { Job } from "@/lib/types";
import { eventKey, isExhausted } from "./exhaustion";
import { paywallOffers } from "./offer";
import { PaywallMoment } from "./PaywallMoment";

const onSale: MonthlyCatalog = {
  ...FALLBACK_CATALOG,
  plans: FALLBACK_CATALOG.plans.map((p) => ({ ...p, available: { month: true, year: true } })),
};

const outOfFree: MyPlan = {
  plan: null,
  status: "none",
  renews: false,
  cancel_at_period_end: false,
  current_period_end: null,
  included_left: 0,
  credits: 0,
  reels_used_30d: 4,
  reels_rendered: 4,
  can_manage: false,
  low_credits: true,
  recommended_plan: "creator",
};

const job = {
  job_id: "job_a",
  state: 1,
  result_url: "https://media.menivor.com/r/job_a.mp4",
} as unknown as Job;

// Dodo test-mode checkout fixture (no live call).
const DODO_TEST_CHECKOUT = "https://test.checkout.dodopayments.com/buy/fixture";

function stubApi(mine: MyPlan, calls: string[] = []) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? "GET"} ${url}`);
      const body = url.endsWith("/billing/monthly-plans")
        ? { status: 200, data: onSale }
        : url.endsWith("/billing/monthly-plan")
          ? { status: 200, data: mine }
          : url.endsWith("/launch/status")
            ? { status: 200, data: { payments: { paused: false, provider: "dodo", free_monthly_reels: 0 } } }
            : { status: 200, data: { checkout_url: DODO_TEST_CHECKOUT } };
      return { ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) };
    }),
  );
  return calls;
}

beforeEach(() => window.localStorage.clear());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("paywall offers", () => {
  it("defaults to the cheapest pack and puts the cheapest monthly plan second, from plan config", () => {
    const offers = paywallOffers(onSale);
    const starter = PRICING_PLANS.find((p) => p.planKey === "starter");
    expect(offers.pack).toEqual({ planKey: "starter", name: starter?.name, price: starter?.price, reels: starter?.credits });
    expect(offers.monthly?.planKey).toBe("creator");
    expect(offers.monthly?.price).toBe(`$${(FALLBACK_CATALOG.plans[0]?.monthly_cents ?? 0) / 100}`);
  });

  it("follows plan config when a price changes", () => {
    const packs = PRICING_PLANS.map((p) => (p.planKey === "starter" ? { ...p, price: "$21" } : p));
    expect(paywallOffers(onSale, packs).pack?.price).toBe("$21");
    expect(paywallOffers(FALLBACK_CATALOG).monthly).toBeNull(); // not on sale: no monthly row
  });

  it("detects exhaustion only with no credits and no plan", () => {
    expect(isExhausted(outOfFree)).toBe(true);
    expect(isExhausted({ ...outOfFree, credits: 1 })).toBe(false);
    expect(
      isExhausted({
        ...outOfFree,
        plan: { plan_key: "creator", name: "Creator", interval: "month", price_cents: 1500, period_reels: 35 },
      }),
    ).toBe(false);
    expect(isExhausted(undefined)).toBe(false);
  });
});

describe("PaywallMoment", () => {
  it("shows the reel, then the pack first and the monthly plan second", async () => {
    stubApi(outOfFree);
    render(<PaywallMoment jobIds={["job_a", "job_b"]} job={job} ready />);
    const dialog = await screen.findByTestId("paywall-moment");
    expect(dialog.querySelector("video")?.getAttribute("src")).toBe(job.result_url);
    expect(screen.getByRole("heading", { name: "Keep making reels" })).toBeTruthy();
    const buttons = screen.getAllByRole("button").filter((b) => b.getAttribute("data-copy-source"));
    expect(buttons[0]?.textContent).toMatch(/30 reels for \$19, one time/);
    expect(buttons[0]?.getAttribute("data-copy-source")).toBe("components/marketing/plans.ts");
    expect(buttons[1]?.textContent).toMatch(/Creator: 35 reels a month for \$15/);
  });

  it("is shown exactly once per exhaustion event", async () => {
    stubApi(outOfFree);
    const first = render(<PaywallMoment jobIds={["job_a", "job_b"]} job={job} ready />);
    await screen.findByTestId("paywall-moment");
    first.unmount();
    // Same run again (reload / revisit): not shown.
    render(<PaywallMoment jobIds={["job_b", "job_a"]} job={job} ready />);
    await new Promise((r) => setTimeout(r, 30));
    expect(screen.queryByTestId("paywall-moment")).toBeNull();
    cleanup();
    expect(window.localStorage.getItem(eventKey(["job_a", "job_b"]))).toBe("1");
    // A new run that empties the balance is a new event.
    render(<PaywallMoment jobIds={["job_c"]} job={job} ready />);
    expect(await screen.findByTestId("paywall-moment")).toBeTruthy();
  });

  it("stays closed while rendering, with credits left, or once dismissed", async () => {
    stubApi({ ...outOfFree, credits: 2 });
    render(<PaywallMoment jobIds={["job_a"]} job={job} ready />);
    await new Promise((r) => setTimeout(r, 30));
    expect(screen.queryByTestId("paywall-moment")).toBeNull();
    cleanup();
    stubApi(outOfFree);
    render(<PaywallMoment jobIds={["job_d"]} job={job} ready={false} />);
    await new Promise((r) => setTimeout(r, 30));
    expect(screen.queryByTestId("paywall-moment")).toBeNull();
    cleanup();
    render(<PaywallMoment jobIds={["job_e"]} job={job} ready />);
    fireEvent.click(await screen.findByRole("button", { name: "Close" }));
    expect(screen.queryByTestId("paywall-moment")).toBeNull();
  });

  it("opens the pack checkout in one click (Dodo test-mode fixture)", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    const calls = stubApi(outOfFree);
    render(<PaywallMoment jobIds={["job_f"]} job={job} ready />);
    const [pack] = (await screen.findAllByRole("button")).filter((b) => b.getAttribute("data-copy-source"));
    fireEvent.click(pack as HTMLElement);
    await waitFor(() => expect(assign).toHaveBeenCalledWith(DODO_TEST_CHECKOUT));
    const post = calls.find((c) => c.startsWith("POST") && c.endsWith("/billing/checkout"));
    expect(post).toBeTruthy();
  });

  it("opens the monthly checkout in one click", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    const calls = stubApi(outOfFree);
    render(<PaywallMoment jobIds={["job_g"]} job={job} ready />);
    await screen.findByTestId("paywall-moment");
    fireEvent.click(screen.getByRole("button", { name: /reels a month/ }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith(DODO_TEST_CHECKOUT));
    expect(calls.some((c) => c.startsWith("POST") && c.endsWith("/billing/monthly-plan/checkout"))).toBe(true);
  });
});

describe("paywall copy", () => {
  it("passes the copy denylist, types no price and uses no emoji", () => {
    const web = path.resolve(__dirname, "../../..");
    const denylist = JSON.parse(
      fs.readFileSync(path.resolve(web, "../../policy/copy-denylist.json"), "utf8"),
    ) as Denylist;
    for (const rel of ["PaywallMoment.tsx", "offer.ts", "use-paywall-moment.ts", "exhaustion.ts"]) {
      const source = fs.readFileSync(path.join(__dirname, rel), "utf8");
      expect(source, rel).not.toMatch(/\$\d/);
      expect(source, rel).not.toMatch(/\p{Extended_Pictographic}/u);
      const units = sourceUnits(source, `src/features/paywall-moment/${rel}`).units.map((u) => ({
        ...u,
        surface: "app-ui" as const,
      }));
      const hits = checkUnits(denylist, units, { flags: {} }).filter((h) => h.severity === "error");
      expect(hits, rel).toEqual([]);
    }
  });
});
