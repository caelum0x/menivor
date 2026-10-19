import * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";

const replace = vi.fn();
const auth = {
  isLoaded: true,
  isSignedIn: true,
  getToken: async (): Promise<string | null> => "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1In0.sig",
};
vi.mock("@clerk/nextjs", () => ({ useAuth: () => auth, UserButton: () => null }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace }) }));
vi.mock("next/link", () => ({
  __esModule: true,
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

import { dodoReturnIds, isFailedDodoReturn, startPackCheckout } from "./api";
import { BuyCredits } from "./BuyCredits";
import { useCreemReturn } from "./use-creem-return";
import { OnboardingFlow } from "@/src/features/onboarding/OnboardingFlow";
import {
  checkoutProvider,
  pausedCopy,
  paymentsModeFrom,
  providerLabel,
  resetPaymentsModeCache,
} from "@/src/shared/payments";
import { setSessionTokenGetter } from "@/src/shared/api/session-token";

function json(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "",
    text: async () => JSON.stringify(body),
    json: async () => body,
    headers: { get: () => null },
  } as unknown as Response;
}

function stub(routes: Record<string, (init?: RequestInit) => Response>) {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, init });
      const key = Object.keys(routes).find((path) => url.includes(path));
      const handler = key ? routes[key] : undefined;
      return handler ? handler(init) : json({ status: 200, data: {} });
    }),
  );
  return calls;
}

function setSearch(search: string) {
  vi.stubGlobal("location", {
    ...window.location,
    assign: vi.fn(),
    search,
    href: `http://localhost/onboarding${search}`,
  });
}

const LOCKED = {
  unlocked: false,
  available: true,
  credits: 0,
  price_usd: 1,
  card_check_credits: 1,
  free_credits: 3,
  provider: "dodo",
};

beforeEach(() => {
  auth.isSignedIn = true;
  replace.mockReset();
  resetPaymentsModeCache();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  setSessionTokenGetter(null);
  window.localStorage.clear();
});

describe("payments mode helpers", () => {
  it("normalizes the launch-status payments block", () => {
    expect(paymentsModeFrom({ paused: true, provider: "none", free_monthly_reels: 3 })).toEqual({
      paused: true,
      provider: "none",
      free_monthly_reels: 3,
    });
    expect(paymentsModeFrom({ paused: false, provider: "dodo" }).provider).toBe("dodo");
    expect(paymentsModeFrom({ provider: "none" }).paused).toBe(true);
    expect(paymentsModeFrom(null).paused).toBe(false);
    expect(paymentsModeFrom({ provider: "evil" }).provider).toBe("dodo");
  });

  it("labels providers and picks the checkout provider", () => {
    expect(providerLabel("dodo")).toBe("Dodo Payments");
    expect(providerLabel(undefined)).toBe("our payment partner");
    expect(checkoutProvider({ paused: true, provider: "none", free_monthly_reels: 3 })).toBeNull();
    expect(checkoutProvider({ paused: false, provider: "dodo", free_monthly_reels: 0 })).toBe("dodo");
    expect(pausedCopy({ paused: true, provider: "none", free_monthly_reels: 3 })).toBe(
      "Paid plans are back soon. Free while we move to a new payment partner: 3 reels every month.",
    );
  });

  it("detects Dodo returns", () => {
    expect(dodoReturnIds("?checkout=return&provider=dodo&payment_id=pay_1&status=succeeded")).toEqual({
      payment_id: "pay_1",
    });
    expect(dodoReturnIds("?provider=dodo&subscription_id=sub_1")).toEqual({ subscription_id: "sub_1" });
    expect(dodoReturnIds("?payment_id=pay_1")).toBeNull();
    expect(dodoReturnIds("?provider=dodo")).toBeNull();
    expect(isFailedDodoReturn("?provider=dodo&payment_id=pay_1&status=failed")).toBe(true);
    expect(isFailedDodoReturn("?provider=dodo&payment_id=pay_1&status=succeeded")).toBe(false);
  });
});

describe("pack checkout provider", () => {
  it("sends the active provider (dodo) to /billing/checkout", async () => {
    const calls = stub({
      "/launch/status": () =>
        json({ status: 200, data: { payments: { paused: false, provider: "dodo", free_monthly_reels: 0 } } }),
      "/billing/checkout": () => json({ status: 200, data: { checkout_url: "https://checkout.dodopayments.com/s/1" } }),
    });
    const result = await startPackCheckout("starter", { token: "t" });
    expect(result.checkout_url).toBe("https://checkout.dodopayments.com/s/1");
    const post = calls.find((c) => c.url.includes("/billing/checkout"));
    expect(JSON.parse(String(post?.init?.body))).toEqual({ plan_key: "starter", provider: "dodo" });
  });

  it("refuses to open a checkout while payments are paused", async () => {
    const calls = stub({
      "/launch/status": () =>
        json({ status: 200, data: { payments: { paused: true, provider: "none", free_monthly_reels: 3 } } }),
    });
    await expect(startPackCheckout("pro", { token: "t" })).rejects.toThrow(/back soon/i);
    expect(calls.some((c) => c.url.includes("/billing/checkout"))).toBe(false);
  });
});

describe("paused UI", () => {
  it("BuyCredits shows the calm paused notice instead of buy buttons", async () => {
    stub({
      "/launch/status": () =>
        json({ status: 200, data: { payments: { paused: true, provider: "none", free_monthly_reels: 3 } } }),
    });
    render(<BuyCredits />);
    expect(await screen.findByTestId("payments-paused")).toHaveTextContent(/paid plans are back soon/i);
    expect(screen.queryByRole("button", { name: /buy 30 reels/i })).toBeNull();
  });

  it("BuyCredits names Dodo Payments when it is the provider", async () => {
    stub({
      "/launch/status": () =>
        json({ status: 200, data: { payments: { paused: false, provider: "dodo", free_monthly_reels: 0 } } }),
    });
    render(<BuyCredits />);
    expect(await screen.findByText(/paid securely through dodo payments/i)).toBeInTheDocument();
  });

  it("onboarding passes straight through when payments are paused", async () => {
    setSearch("");
    stub({
      "/billing/card-check": () =>
        json({ status: 200, data: { ...LOCKED, unlocked: true, paused: true, provider: "none", free_monthly_reels: 3 } }),
    });
    render(<OnboardingFlow next="/create" />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/create"));
  });
});

function ReturnProbe({ delays }: Readonly<{ delays: readonly number[] }>) {
  const state = useCreemReturn({ dodoRetryDelaysMs: delays });
  return <p data-testid="phase">{state.phase === "pending" ? `pending:${state.message}` : state.phase}</p>;
}

describe("Dodo return", () => {
  it("confirms a Dodo card-check return and continues", async () => {
    setSearch("?checkout=return&provider=dodo&next=%2Fcreate&payment_id=pay_1&status=succeeded");
    let confirmed = false;
    const calls = stub({
      "/billing/dodo/confirm": () => {
        confirmed = true;
        return json({ status: 200, data: { plan_key: "card_check", credits: 1, balance: 4, unlocked: true } });
      },
      "/billing/card-check": () =>
        json({ status: 200, data: confirmed ? { ...LOCKED, unlocked: true, credits: 4 } : LOCKED }),
    });
    render(<OnboardingFlow next="/create" />);
    expect(await screen.findByText(/payment confirmed\. you have 4 reel credits/i)).toBeInTheDocument();
    const post = calls.find((c) => c.url.includes("/billing/dodo/confirm"));
    expect(JSON.parse(String(post?.init?.body))).toEqual({ payment_id: "pay_1" });
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/create"));
  });

  it("retries while Dodo reports pending, then says it is processing", async () => {
    setSearch("?checkout=return&provider=dodo&payment_id=pay_2&status=succeeded");
    const calls = stub({
      "/billing/dodo/confirm": () => json({ status: 200, data: { pending: true } }),
    });
    render(<ReturnProbe delays={[0, 1, 1]} />);
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent(/^pending:.*processing/i));
    expect(calls.filter((c) => c.url.includes("/billing/dodo/confirm"))).toHaveLength(3);
  });

  it("reports a failed Dodo checkout without calling the API", async () => {
    setSearch("?checkout=return&provider=dodo&payment_id=pay_3&status=failed");
    const calls = stub({});
    render(<ReturnProbe delays={[0]} />);
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("failed"));
    expect(calls.some((c) => c.url.includes("/billing/dodo/confirm"))).toBe(false);
  });
});
