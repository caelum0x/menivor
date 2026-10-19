import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { WalletOverview } from "./WalletOverview";

// Stable references so `useAuth()` does not return a fresh `getToken` on every
// render (which would make the `refresh` callback — and its effect — loop).
const getToken = async () => "tok";
const auth = { getToken, isLoaded: true };
vi.mock("@clerk/nextjs", () => ({
  useAuth: () => auth,
  UserButton: () => null,
}));

vi.mock("next/link", () => ({
  __esModule: true,
  default: ({
    children,
    href,
  }: {
    children: React.ReactNode;
    href: string;
  }) => <a href={href}>{children}</a>,
}));

function jsonResponse(
  body: unknown,
  init: { ok?: boolean; status?: number } = {},
): Response {
  const ok = init.ok ?? true;
  return {
    ok,
    status: init.status ?? (ok ? 200 : 400),
    statusText: ok ? "OK" : "Error",
    text: async () => JSON.stringify(body),
    headers: { get: () => null },
  } as unknown as Response;
}

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const BALANCE = {
  status: 200,
  data: {
    available_micros: 5_000_000,
    reserved_micros: 250_000,
    plan: "pro",
    currency: "usd",
  },
};

const SOURCE = {
  source_account_id: "src_personal",
  kind: "personal",
  label: "Personal wallet",
  role: "owner",
  can_send: true,
  limits: {
    per_transfer_micros: 1_000_000_000,
    daily_micros: 2_000_000_000,
    daily_used_micros: 0,
    daily_remaining_micros: 2_000_000_000,
  },
};

function walletBootstrap(url: string): Response | null {
  if (url.endsWith("/wallet/destinations")) {
    return jsonResponse({ status: 200, data: { destinations: [] } });
  }
  if (url.includes("/wallet/receive-addresses")) {
    return jsonResponse({
      status: 200,
      data: { address: "ait1qpersonal", source: SOURCE },
    });
  }
  if (url.includes("/wallet/sources")) {
    return jsonResponse({ status: 200, data: { sources: [SOURCE] } });
  }
  if (url.includes("/wallet/saved-recipients")) {
    return jsonResponse({ status: 200, data: { recipients: [] } });
  }
  if (url.includes("source_account_id=")) return jsonResponse(BALANCE);
  if (/\/wallet(?:\?|$)/.test(url)) return jsonResponse(BALANCE);
  return null;
}

async function submitTransferReturning(status: number, message: string) {
  const fetchMock = vi.fn().mockImplementation((input: string) => {
    const url = String(input);
    const bootstrap = walletBootstrap(url);
    if (bootstrap) return Promise.resolve(bootstrap);
    if (url.includes("/wallet/transfer-challenges")) {
      return Promise.resolve(jsonResponse({ status: 200, data: {
        challenge_id: "challenge_1",
        source: SOURCE,
        recipient: { handle: "bob", display_name: "Bob" },
        amount_micros: 5_000_000,
        binding_sha256: "binding",
        expires_at: "2099-01-01T00:00:00Z",
      } }));
    }
    if (url.includes("/wallet/transfers")) {
      return Promise.resolve(jsonResponse({ message }, { ok: false, status }));
    }
    throw new Error(`unexpected request ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<WalletOverview />);
  await waitFor(() => expect(screen.getByText("$5.00")).toBeInTheDocument());

  fireEvent.change(screen.getByLabelText("Recipient handle"), {
    target: { value: "@bob" },
  });
  const review = screen.getByRole("button", { name: "Review" });
  await waitFor(() => expect(review).toBeEnabled());
  fireEvent.click(review);
  await screen.findByRole("button", { name: "Confirm send" });
  fireEvent.click(screen.getByRole("button", { name: "Confirm send" }));
  // Throttling replies are shown as a fixed friendly sentence, not raw text.
  await screen.findByText(status === 429 ? /too many requests/i : message);

  return fetchMock;
}

describe("WalletOverview", () => {
  it("loads the balance from /wallet and renders it", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(BALANCE));
    vi.stubGlobal("fetch", fetchMock);

    render(<WalletOverview />);

    await waitFor(() => expect(screen.getByText("$5.00")).toBeInTheDocument());
    expect(fetchMock.mock.calls[0]![0]).toContain("/wallet");
    expect(screen.getByText(/pro plan/i)).toBeInTheDocument();
  });

  it("starts a real checkout POST and shows the intent outcome", async () => {
    const fetchMock = vi.fn().mockImplementation((input: string) => {
      const url = String(input);
      if (url.includes("/wallet/checkout")) {
        return Promise.resolve(jsonResponse({
          status: 200,
          data: {
            payment_intent_id: "pi_1",
            status: "pending",
            currency: "USD",
            credit_micros: 10_000_000,
            fee_micros: 0,
            tax_micros: 0,
            processor_micros: 0,
            total_charge_micros: 10_000_000,
            fee_rate_bps: 0,
            fee_schedule_version: "v1",
            credit_usd: "10.00",
            total_charge_usd: "10.00",
          },
        }));
      }
      return Promise.resolve(walletBootstrap(url) ?? jsonResponse(BALANCE));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<WalletOverview />);
    await waitFor(() => expect(screen.getByText("$5.00")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "$10" }));

    await waitFor(() =>
      expect(
        screen.getByText(/Top-up of \$10\.00 started/i),
      ).toBeInTheDocument(),
    );

    const checkoutCall = fetchMock.mock.calls.find((c) =>
      String(c[0]).includes("/wallet/checkout"),
    );
    expect(checkoutCall).toBeTruthy();
    expect(checkoutCall?.[1].method).toBe("POST");
    expect(checkoutCall?.[1].headers["Idempotency-Key"]).toBeTruthy();
    expect(JSON.parse(checkoutCall?.[1].body)).toEqual({ amount_usd: "10.00" });
  });

  it("creates a Mint-backed agent receive identity from the wallet", async () => {
    const destination = {
      destination_id: "dest_agent",
      handle: "agent:caption-bot",
      display_name: "Caption Bot",
      kind: "agent",
      scope: "personal",
      workspace_source_account_id: null,
      active: true,
      address: "ait1qagent",
    };
    const fetchMock = vi.fn().mockImplementation((input: string, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/wallet/destinations") && init?.method === "POST") {
        return Promise.resolve(jsonResponse({ status: 201, data: destination }));
      }
      if (url.includes("/wallet/destinations/dest_agent/balance")) {
        return Promise.resolve(jsonResponse({ status: 200, data: {
          destination, currency: "AIT", available_micros: 0, held_micros: 0,
        } }));
      }
      return Promise.resolve(walletBootstrap(url) ?? jsonResponse(BALANCE));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<WalletOverview />);
    await screen.findByText("Receive identities");
    fireEvent.change(screen.getByLabelText("Display name"), {
      target: { value: "Caption Bot" },
    });
    fireEvent.change(screen.getByLabelText("Public handle"), {
      target: { value: "caption-bot" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create destination" }));

    await screen.findByText("agent:caption-bot");
    expect(screen.getByText("ait1qagent")).toBeInTheDocument();
    const call = fetchMock.mock.calls.find((entry) =>
      String(entry[0]).endsWith("/wallet/destinations") && entry[1]?.method === "POST"
    );
    expect(JSON.parse(call?.[1].body)).toEqual({
      kind: "agent", slug: "caption-bot", display_name: "Caption Bot",
    });
  });

  it("shows an error state with a retry when the balance load fails", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        jsonResponse({ message: "server down" }, { ok: false, status: 500 }),
      );
    vi.stubGlobal("fetch", fetchMock);

    render(<WalletOverview />);

    await waitFor(() =>
      expect(screen.getByText(/went wrong on our side/i)).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
  });

  it("retains the submitted logical transfer and stable key after HTTP 429", async () => {
    await submitTransferReturning(429, "rate limited");

    const encoded = window.localStorage.getItem("menivor.wallet.pendingTransfer");
    expect(encoded).not.toBeNull();
    expect(JSON.parse(encoded!)).toMatchObject({
      version: 2,
      sourceAccountId: "src_personal",
      challengeId: "challenge_1",
      recipientHandle: "bob",
      amountMicros: 5_000_000,
      submitted: true,
    });
    expect(screen.getByText(/Unresolved logical transfer/i)).toBeInTheDocument();
  });

  it.each([402, 410])(
    "clears the pending logical transfer after definitive HTTP %s",
    async (status) => {
      await submitTransferReturning(status, `definitive ${status}`);

      expect(
        window.localStorage.getItem("menivor.wallet.pendingTransfer"),
      ).toBeNull();
      expect(
        screen.queryByText(/Unresolved logical transfer/i),
      ).not.toBeInTheDocument();
    },
  );

  it("retries a restored submitted command despite expired review and insufficient balance", async () => {
    window.localStorage.setItem("menivor.wallet.pendingTransfer", JSON.stringify({
      version: 2,
      sourceAccountId: "src_personal",
      sourceKind: "personal",
      sourceLabel: "Personal wallet",
      challengeId: "challenge_expired",
      challengeExpiresAt: "2020-01-01T00:00:00Z",
      recipientHandle: "bob",
      amountMicros: 5_000_000,
      idempotencyKey: "stable-retry-key",
      submitted: true,
    }));
    const zeroBalance = { ...BALANCE, data: { ...BALANCE.data, available_micros: 0 } };
    const fetchMock = vi.fn().mockImplementation((input: string) => {
      const url = String(input);
      if (url.includes("/wallet/sources")) return Promise.resolve(jsonResponse({ status: 200, data: { sources: [SOURCE] } }));
      if (url.includes("/wallet/transfers")) return Promise.resolve(jsonResponse({ message: "still unknown" }, { ok: false, status: 429 }));
      if (url.includes("/wallet/saved-recipients")) return Promise.resolve(jsonResponse({ status: 200, data: { recipients: [] } }));
      return Promise.resolve(jsonResponse(zeroBalance));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<WalletOverview />);
    const retry = await screen.findByRole("button", { name: "Retry exact send" });
    fireEvent.click(retry);
    await screen.findByText(/too many requests/i);

    const call = fetchMock.mock.calls.find((entry) => String(entry[0]).includes("/wallet/transfers"));
    expect(call?.[1].headers["Idempotency-Key"]).toBe("stable-retry-key");
    expect(JSON.parse(call?.[1].body)).toMatchObject({
      source_account_id: "src_personal",
      challenge_id: "challenge_expired",
      recipient_handle: "bob",
      amount_micros: 5_000_000,
    });
    expect(fetchMock.mock.calls.some((entry) => String(entry[0]).includes("transfer-challenges"))).toBe(false);
  });
});
