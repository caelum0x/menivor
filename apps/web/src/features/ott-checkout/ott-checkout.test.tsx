import * as React from "react";
import * as fs from "node:fs";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { checkUnits, type Denylist } from "@/src/shared/policy/copy-check";
import { sourceUnits } from "@/src/shared/policy/source-units";
import { writeSession } from "@/src/features/ott-auth";
import { formatPrice, type Offer } from "./api";
import { Offers } from "./Offers";

const SVOD: Offer = { id: "o1", kind: "svod", title_id: null, sku: "svod.month", name: "Members", price_cents: 500,
  currency: "USD", interval: "month", rental_hours: null, active: true };
const RENT: Offer = { ...SVOD, id: "o2", kind: "rental", title_id: "t2", sku: "rental.t2", name: "Rent", price_cents: 299,
  interval: null, rental_hours: 48 };

const assign = vi.fn();

beforeEach(() => {
  window.localStorage.clear();
  Object.defineProperty(window, "location", { value: { ...window.location, assign }, configurable: true });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  assign.mockReset();
});

function stub(open = true) {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    if (url.endsWith("/offers")) {
      return { ok: true, status: 200, json: async () => ({ data: { offers: [SVOD, RENT], checkout_open: open } }) } as Response;
    }
    if (url.endsWith("/checkout")) {
      return { ok: true, status: 200, json: async () => ({ data: { url: "https://test.checkout.example/cs_1" } }) } as Response;
    }
    return { ok: false, status: 404, json: async () => ({}) } as Response;
  }));
  return calls;
}

describe("prices", () => {
  it("say what the viewer pays and for how long", () => {
    expect(formatPrice(SVOD)).toBe("$5.00 a month");
    expect(formatPrice(RENT)).toBe("$2.99 for 48 hours");
  });
});

describe("Offers", () => {
  it("sends a signed-in viewer straight to the creator's checkout", async () => {
    writeSession("maya", { session: "vs-1", expiresAt: 4102444800, name: "ana" });
    const calls = stub();
    render(<Offers handle="maya" titleId="t2" />);
    fireEvent.click(await screen.findByRole("button", { name: /Rent: Rent, \$2\.99 for 48 hours/ }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://test.checkout.example/cs_1"));
    const checkout = calls.find((c) => c.url.endsWith("/checkout"));
    expect((checkout?.init?.headers as Record<string, string>)["X-OTT-Viewer"]).toBe("vs-1");
    expect(JSON.parse(String(checkout?.init?.body))).toEqual({ offer_id: "o2" });
  });

  it("asks for sign-in first when the viewer is not signed in", async () => {
    stub();
    render(<Offers handle="maya" />);
    fireEvent.click(await screen.findByRole("button", { name: /Subscribe: Members/ }));
    expect(screen.getByLabelText("Email")).toBeTruthy();
    expect(assign).not.toHaveBeenCalled();
  });

  it("shows nothing until checkout is open", async () => {
    stub(false);
    const { container } = render(<Offers handle="maya" />);
    await new Promise((r) => setTimeout(r, 20));
    expect(container.innerHTML).toBe("");
  });
});

describe("copy", () => {
  it("passes the copy denylist", () => {
    const web = path.resolve(__dirname, "../../..");
    const denylist = JSON.parse(fs.readFileSync(path.resolve(web, "../../policy/copy-denylist.json"), "utf8")) as Denylist;
    const files = ["src/features/ott-checkout/Offers.tsx", "src/features/ott-checkout/StudioSales.tsx",
      "src/features/ott-player/Player.tsx"];
    const units = files.flatMap((rel) => sourceUnits(fs.readFileSync(path.join(web, rel), "utf8"), rel).units);
    expect(checkUnits(denylist, units, { flags: {} }).filter((h) => h.severity === "error")).toEqual([]);
  });
});
