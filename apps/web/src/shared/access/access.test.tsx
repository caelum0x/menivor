import * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

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

import { LEGACY_UNLOCKED, getCardCheckStatus, isCreemReturn } from "./api";
import { signUpHref, unlockHref, useCreateAccess } from "./use-web-access";
import { OnboardingFlow } from "@/src/features/onboarding/OnboardingFlow";
import { apiRequest } from "@/src/shared/api";
import { setSessionTokenGetter } from "@/src/shared/api/session-token";

function json(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "",
    text: async () => JSON.stringify(body),
    headers: { get: () => null },
  } as unknown as Response;
}

const LOCKED = {
  unlocked: false,
  available: true,
  credits: 0,
  price_usd: 1,
  card_check_credits: 1,
  free_credits: 3,
};

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

beforeEach(() => {
  auth.isSignedIn = true;
  replace.mockReset();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  setSessionTokenGetter(null);
  window.localStorage.clear();
});

describe("access api", () => {
  it("treats an API without the card check (404) as unlocked", async () => {
    stub({ "/billing/card-check": () => json({ message: "Not Found" }, 404) });
    await expect(getCardCheckStatus({ token: "t" })).resolves.toEqual(LEGACY_UNLOCKED);
  });

  it("recognises only signed Creem returns", () => {
    expect(isCreemReturn("?checkout_id=ch_1&signature=abc")).toBe(true);
    expect(isCreemReturn("?checkout=return")).toBe(false);
    expect(isCreemReturn("?checkout_id=ch_1")).toBe(false);
  });

  it("builds sign-up and unlock links that come back to the create box", () => {
    expect(signUpHref("/create?q=x&auto=1")).toBe("/sign-up?redirect_url=%2Fcreate%3Fq%3Dx%26auto%3D1");
    expect(unlockHref("/create")).toBe("/onboarding?next=%2Fcreate");
  });
});

describe("transport", () => {
  it("sends the signed-in session token and never mints a web guest session", async () => {
    window.localStorage.clear();
    setSessionTokenGetter(async () => "eyJsession.token.value");
    const calls = stub({ "/me": () => json({ status: 200, data: { credits: 4 } }) });
    await apiRequest("/me");
    expect(calls.map((c) => c.url).some((u) => u.includes("/auth/device"))).toBe(false);
    const headers = calls[0]?.init?.headers as Record<string, string>;
    expect(headers["x-api-key"]).toBe("eyJsession.token.value");
  });

  it("signed out with no stored key: no device exchange", async () => {
    window.localStorage.clear();
    const calls = stub({});
    await apiRequest("/me").catch(() => undefined);
    expect(calls.some((c) => c.url.includes("/auth/device"))).toBe(false);
  });
});

function Gate({ back }: { back: string }) {
  const access = useCreateAccess(back);
  return <p>{access.status}</p>;
}

describe("useCreateAccess", () => {
  it("sends signed-out visitors to sign-up", async () => {
    auth.isSignedIn = false;
    stub({});
    render(<Gate back="/create?q=shop&auto=1" />);
    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith(signUpHref("/create?q=shop&auto=1")),
    );
  });

  it("sends locked accounts to the unlock step", async () => {
    stub({ "/billing/card-check": () => json({ status: 200, data: LOCKED }) });
    render(<Gate back="/create" />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith(unlockHref("/create")));
  });

  it("is ready once unlocked", async () => {
    stub({
      "/billing/card-check": () => json({ status: 200, data: { ...LOCKED, unlocked: true, credits: 4 } }),
    });
    render(<Gate back="/create" />);
    expect(await screen.findByText("ready")).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });
});

describe("OnboardingFlow", () => {
  it("offers one $1 button that opens the Creem card check with the next path", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign, search: "", href: "http://localhost/onboarding" });
    const calls = stub({
      "/billing/card-check": (init) =>
        init?.method === "POST"
          ? json({ status: 200, data: { checkout_url: "https://checkout.creem.io/ch_1" } })
          : json({ status: 200, data: LOCKED }),
    });
    render(<OnboardingFlow next="/create?q=shop&auto=1" />);
    const button = await screen.findByRole("button", { name: /pay \$1 and unlock 4 reels/i });
    fireEvent.click(button);
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://checkout.creem.io/ch_1"));
    const post = calls.find((c) => c.init?.method === "POST");
    expect(JSON.parse(String(post?.init?.body))).toEqual({ next: "/create?q=shop&auto=1" });
  });

  it("continues straight to next when already unlocked", async () => {
    stub({
      "/billing/card-check": () => json({ status: 200, data: { ...LOCKED, unlocked: true } }),
    });
    render(<OnboardingFlow next="/create" />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/create"));
  });
});
