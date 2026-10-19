import * as React from "react";
import * as fs from "node:fs";
import * as path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { checkUnits, type Denylist } from "@/src/shared/policy/copy-check";
import { sourceUnits } from "@/src/shared/policy/source-units";

const token = vi.hoisted(() => async () => "session");
vi.mock("@/lib/use-api-token", () => ({ useApiToken: () => token }));
const apiRequest = vi.fn();
vi.mock("@/src/shared/api", () => ({ API_BASE: "https://api.example/api/v1", apiRequest: (...a: unknown[]) => apiRequest(...a) }));

import { StudioSales } from "./StudioSales";
import { toCents } from "./api";

const SVOD = { id: "o1", kind: "svod", title_id: null, sku: "svod.month", name: "Members", price_cents: 500, currency: "USD",
  interval: "month", rental_hours: null, active: true };
const TITLES = [{ id: "t1", title: "Pilot" }, { id: "t2", title: "Finale" }];

function routes(extra: Record<string, unknown> = {}) {
  apiRequest.mockImplementation(async (route: string, init?: { method?: string; body?: unknown }) => {
    if (route in extra) return extra[route];
    if (route === "/ott/studio/commerce") return { account: { connected: true, provider: "dodo", mode: "test" }, offers: [SVOD] };
    if (route === "/ott/studio/commerce/coupons" && init?.method !== "POST") return { coupons: [] };
    if (route.startsWith("/ott/studio/commerce/sales")) {
      return { days: 30, sales: [{ title_id: "t1", title: "Pilot", gross_cents: 1300, grants: 2, currency: "USD" },
        { title_id: "t2", title: "Finale", gross_cents: 0, grants: 0, currency: "USD" }],
      sales_totals: { gross_cents: 1300, grants: 2, currency: "USD" } };
    }
    return init?.body ?? {};
  });
}

const posted = (route: string) => apiRequest.mock.calls.filter(([r, i]) => r === route && i?.method === "POST").map(([, i]) => i.body);

afterEach(() => {
  cleanup();
  apiRequest.mockReset();
});

describe("studio prices", () => {
  it("parses prices to cents", () => {
    expect(toCents("9.99")).toBe(999);
    expect(toCents("2,50")).toBe(250);
    expect(toCents("0.20")).toBeNull();
    expect(toCents("abc")).toBeNull();
  });

  it("keeps the members price and sets a buy and a rental per title in two fields each", async () => {
    routes();
    render(<StudioSales titles={TITLES} />);
    const row = await screen.findByText("Pilot", { selector: "span" });
    const li = row.closest("li") as HTMLElement;
    fireEvent.change(within(li).getByLabelText("Buy"), { target: { value: "9.99" } });
    fireEvent.change(within(li).getByLabelText("Rent"), { target: { value: "2.99" } });
    fireEvent.click(within(li).getByRole("button", { name: "Save prices" }));
    await waitFor(() => expect(posted("/ott/studio/commerce/offers")).toHaveLength(2));
    expect(posted("/ott/studio/commerce/offers")).toEqual([
      { kind: "tvod", name: "Own Pilot", price_cents: 999, title_id: "t1" },
      { kind: "rental", name: "Rent Pilot", price_cents: 299, title_id: "t1", rental_hours: 48 },
    ]);
    expect(screen.getByLabelText("Monthly price for members")).toBeTruthy();
    expect(screen.getByText(/Members: \$5\.00 a month/)).toBeTruthy();
  });

  it("refuses a price under 0.50 without calling the API", async () => {
    routes();
    render(<StudioSales titles={TITLES} />);
    const li = (await screen.findByText("Finale", { selector: "span" })).closest("li") as HTMLElement;
    fireEvent.change(within(li).getByLabelText("Buy"), { target: { value: "0.10" } });
    fireEvent.click(within(li).getByRole("button", { name: "Save prices" }));
    expect(await within(li).findByRole("alert")).toBeTruthy();
    expect(posted("/ott/studio/commerce/offers")).toEqual([]);
  });
});

describe("coupons and sales", () => {
  it("sends a percent or an amount with an end date", async () => {
    routes();
    render(<StudioSales titles={TITLES} />);
    fireEvent.change(await screen.findByLabelText("Code"), { target: { value: "save20" } });
    fireEvent.change(screen.getByLabelText("Off"), { target: { value: "20%" } });
    fireEvent.change(screen.getByLabelText("Ends"), { target: { value: "2026-12-31" } });
    fireEvent.click(screen.getByRole("button", { name: "Add coupon" }));
    await waitFor(() => expect(posted("/ott/studio/commerce/coupons")).toHaveLength(1));
    fireEvent.change(screen.getByLabelText("Code"), { target: { value: "fiveoff" } });
    fireEvent.change(screen.getByLabelText("Off"), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Add coupon" }));
    await waitFor(() => expect(posted("/ott/studio/commerce/coupons")).toHaveLength(2));
    expect(posted("/ott/studio/commerce/coupons")).toEqual([
      { code: "save20", kind: "percent", percent: 20, expires_at: "2026-12-31T23:59:59.000Z" },
      { code: "fiveoff", kind: "amount", amount_cents: 500, expires_at: "2026-12-31T23:59:59.000Z" },
    ]);
  });

  it("shows gross sales per title", async () => {
    routes();
    render(<StudioSales titles={TITLES} />);
    expect(await screen.findByText("$13.00 from 2 sales")).toBeTruthy();
    expect(screen.getByText("Pilot: $13.00 (2)")).toBeTruthy();
    expect(screen.queryByText(/Finale: /)).toBeNull();
  });
});

describe("copy", () => {
  it("passes the copy denylist", () => {
    const web = path.resolve(__dirname, "../../..");
    const denylist = JSON.parse(fs.readFileSync(path.resolve(web, "../../policy/copy-denylist.json"), "utf8")) as Denylist;
    const files = ["src/features/ott-checkout/TitleOffers.tsx", "src/features/ott-checkout/StudioSales.tsx",
      "src/features/ott-checkout/Offers.tsx"];
    const units = files.flatMap((rel) => sourceUnits(fs.readFileSync(path.join(web, rel), "utf8"), rel).units);
    expect(checkUnits(denylist, units, { flags: {} }).filter((h) => h.severity === "error")).toEqual([]);
  });
});
