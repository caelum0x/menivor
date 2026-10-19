import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { GatewayConsole } from "../GatewayConsole";

// Stable references so `useAuth()` does not return a fresh `getToken` on every
// render (an unstable token would loop the `load` effect and starve clicks).
const getToken = async () => "test-token";
const auth = { getToken };
vi.mock("@clerk/nextjs", () => ({
  useAuth: () => auth,
}));

function envelope(data: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "OK",
    headers: { get: () => null },
    text: async () =>
      JSON.stringify({
        status,
        data,
        message: (data as { message?: string })?.message,
      }),
  } as unknown as Response;
}

const ACTIVE_KEY = {
  id: "k1",
  label: "Acme reseller",
  daily_cap_micros: 100_000_000,
  markup_bps: 2000,
  min_fee_micros: 0,
  disabled: false,
};

describe("GatewayConsole", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    // crypto.randomUUID is used for the create idempotency key.
    if (!globalThis.crypto?.randomUUID) {
      vi.stubGlobal("crypto", { randomUUID: () => "test-uuid" });
    }
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it("loads and renders the caller's provisioning keys", async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (url.includes("/gateway/keys")) return envelope({ keys: [ACTIVE_KEY] });
      throw new Error(`unexpected fetch: ${url}`);
    });

    render(<GatewayConsole />);

    expect(await screen.findByText("Acme reseller")).toBeInTheDocument();
    expect(screen.getByText(/20.0% markup/)).toBeInTheDocument();
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/gateway/keys");
    expect(init.method).toBe("GET");
  });

  it("renders the empty state when there are no keys", async () => {
    fetchMock.mockImplementation(async () => envelope({ keys: [] }));

    render(<GatewayConsole />);

    expect(
      await screen.findByText(/No provisioning keys yet/),
    ).toBeInTheDocument();
  });

  it("surfaces an error when the list request fails", async () => {
    fetchMock.mockImplementation(async () =>
      envelope({ message: "gateway down" }, 503),
    );

    render(<GatewayConsole />);

    expect(await screen.findByText(/went wrong on our side/)).toBeInTheDocument();
  });

  it("revokes a key: POSTs the revoke endpoint then reloads", async () => {
    const listCalls: string[] = [];
    fetchMock.mockImplementation(async (url: string, init: RequestInit) => {
      if (url.includes("/revoke")) {
        return envelope({ ...ACTIVE_KEY, disabled: true });
      }
      if (url.includes("/gateway/keys")) {
        listCalls.push(url);
        // First load: active. After revoke reload: revoked.
        const key = listCalls.length > 1 ? { ...ACTIVE_KEY, disabled: true } : ACTIVE_KEY;
        return envelope({ keys: [key] });
      }
      void init;
      throw new Error(`unexpected fetch: ${url}`);
    });

    render(<GatewayConsole />);

    const revokeBtn = await screen.findByRole("button", { name: /revoke/i });
    fireEvent.click(revokeBtn);

    // The revoke endpoint was hit with POST.
    await waitFor(() => {
      const call = fetchMock.mock.calls.find((c) => String(c[0]).includes("/revoke"));
      expect(call).toBeTruthy();
      expect((call![1] as RequestInit).method).toBe("POST");
    });
    // After reload the card shows the revoked badge.
    expect(await screen.findByText("revoked")).toBeInTheDocument();
  });

  it("quotes a key: POSTs base_cost_micros and renders the customer price", async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (url.includes("/quote")) {
        return envelope({
          base_cost_micros: 1_000_000,
          customer_price_micros: 1_200_000,
          spent_today_micros: 0,
          remaining_micros: 99_000_000,
          would_allow: true,
        });
      }
      if (url.includes("/gateway/keys")) return envelope({ keys: [ACTIVE_KEY] });
      throw new Error(`unexpected fetch: ${url}`);
    });

    render(<GatewayConsole />);

    const quoteBtn = await screen.findByRole("button", { name: /quote/i });
    fireEvent.click(quoteBtn);

    const result = await screen.findByTestId("quote-result");
    expect(result).toHaveTextContent("$1.20");
    const quoteCall = fetchMock.mock.calls.find((c) => String(c[0]).includes("/quote"));
    expect(quoteCall).toBeTruthy();
    expect((quoteCall![1] as RequestInit).method).toBe("POST");
    expect(JSON.parse((quoteCall![1] as RequestInit).body as string)).toEqual({
      base_cost_micros: 1_000_000,
    });
  });
});
