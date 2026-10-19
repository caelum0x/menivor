import { afterEach, describe, expect, it, vi } from "vitest";

import {
  checkout,
  createWalletDestination,
  createTransferChallenge,
  deleteTransferRecipient,
  getBalance,
  getLedger,
  getWalletDestinationBalance,
  getWalletDestinations,
  getReceiveAddress,
  getSavedRecipients,
  getWalletSources,
  getWalletTransfer,
  isDefinitiveTransferFailureStatus,
  purchaseQuote,
  resolveTransferRecipient,
  setWalletDestinationActive,
  sendWalletTransfer,
  saveTransferRecipient,
} from "./api";

/** Build a minimal Response-like object for the shared apiRequest transport. */
function jsonResponse(
  body: unknown,
  init: { ok?: boolean; status?: number } = {},
): Response {
  const ok = init.ok ?? true;
  const status = init.status ?? (ok ? 200 : 400);
  return {
    ok,
    status,
    statusText: ok ? "OK" : "Error",
    text: async () => JSON.stringify(body),
    headers: { get: () => null },
  } as unknown as Response;
}

function mockFetch() {
  const fn = vi.fn();
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("account-source transfer contract", () => {
  const source = {
    source_account_id: "workspace_1", kind: "workspace" as const, label: "Studio",
    role: "owner", can_send: true,
    limits: { per_transfer_micros: 10_000_000, daily_micros: 20_000_000, daily_used_micros: 0, daily_remaining_micros: 20_000_000 },
  };

  it("provisions one receive address for the selected opaque source", async () => {
    const fetchMock = mockFetch();
    fetchMock.mockResolvedValueOnce(jsonResponse({
      status: 200,
      data: { address: "ait1qpersonal", source },
    }));

    const result = await getReceiveAddress(" workspace_1 ", { token: "tok" });

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/wallet/receive-addresses");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ source_account_id: "workspace_1" });
    expect(result.address).toBe("ait1qpersonal");
  });

  it("lists opaque sources and creates the challenge with the eventual send key", async () => {
    const fetchMock = mockFetch();
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ status: 200, data: { sources: [source] } }))
      .mockResolvedValueOnce(jsonResponse({ status: 200, data: {
        challenge_id: "challenge_1", source,
        recipient: { handle: "bob", display_name: "Bob" }, amount_micros: 2_000_000,
        binding_sha256: "binding", expires_at: "2099-01-01T00:00:00Z",
      } }));
    expect(await getWalletSources({ token: "tok" })).toEqual([source]);
    await createTransferChallenge({
      source_account_id: "workspace_1", recipient_handle: "bob", amount_micros: 2_000_000,
    }, "stable-key", { token: "tok" });
    const [, init] = fetchMock.mock.calls[1]!;
    expect(init.headers["Idempotency-Key"]).toBe("stable-key");
    expect(JSON.parse(init.body)).toMatchObject({ source_account_id: "workspace_1", recipient_handle: "bob" });
  });

  it("lists, saves and deletes recipients within one source", async () => {
    const saved = { saved_recipient_id: "saved_1", handle: "bob", display_name: "Bob", label: "Editor" };
    const fetchMock = mockFetch();
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ status: 200, data: { recipients: [saved] } }))
      .mockResolvedValueOnce(jsonResponse({ status: 200, data: saved }))
      .mockResolvedValueOnce(jsonResponse({ status: 200, data: { deleted: true } }));
    expect(await getSavedRecipients("workspace_1")).toEqual([saved]);
    await saveTransferRecipient("workspace_1", "bob", "Editor");
    await deleteTransferRecipient("workspace_1", "saved_1");
    expect(String(fetchMock.mock.calls[0]![0])).toContain("source_account_id=workspace_1");
    expect(fetchMock.mock.calls[2]![1].method).toBe("DELETE");
  });
});

describe("managed receive identities", () => {
  const destination = {
    destination_id: "dest_1",
    handle: "agent:caption-bot",
    display_name: "Caption Bot",
    kind: "agent" as const,
    scope: "workspace" as const,
    workspace_source_account_id: "workspace_1",
    active: true,
    address: "ait1qagent",
  };

  it("creates, lists, reads and disables a real destination", async () => {
    const fetchMock = mockFetch();
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ status: 201, data: destination }))
      .mockResolvedValueOnce(jsonResponse({ status: 200, data: { destinations: [destination] } }))
      .mockResolvedValueOnce(jsonResponse({ status: 200, data: {
        destination, currency: "AIT", available_micros: 2_000_000, held_micros: 0,
      } }))
      .mockResolvedValueOnce(jsonResponse({ status: 200, data: { ...destination, active: false } }));

    await createWalletDestination({
      kind: "agent",
      slug: "caption-bot",
      display_name: "Caption Bot",
      workspace_source_account_id: "workspace_1",
    });
    expect(await getWalletDestinations()).toEqual([destination]);
    expect((await getWalletDestinationBalance("dest_1")).available_micros).toBe(2_000_000);
    await setWalletDestinationActive("dest_1", false);

    expect(JSON.parse(fetchMock.mock.calls[0]![1].body)).toMatchObject({
      kind: "agent", workspace_source_account_id: "workspace_1",
    });
    expect(fetchMock.mock.calls[3]![1].method).toBe("PATCH");
    expect(JSON.parse(fetchMock.mock.calls[3]![1].body)).toEqual({ active: false });
  });
});

describe("getBalance", () => {
  it("calls GET /wallet and returns the unwrapped balance", async () => {
    const fetchMock = mockFetch();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        status: 200,
        data: {
          available_micros: 5_000_000,
          reserved_micros: 250_000,
          plan: "pro",
          currency: "usd",
        },
      }),
    );

    const balance = await getBalance({ token: "tok" });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toMatch(/\/wallet$/);
    expect(init.method).toBe("GET");
    expect(init.headers["x-api-key"]).toBe("tok");
    expect(balance).toEqual({
      available_micros: 5_000_000,
      reserved_micros: 250_000,
      plan: "pro",
      currency: "usd",
    });
  });

  it("falls back to GET /media/credits when /wallet is unavailable (404)", async () => {
    const fetchMock = mockFetch();
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({ message: "not found" }, { ok: false, status: 404 }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          status: 200,
          data: {
            available_micros: 1_200_000,
            reserved_micros: 0,
            total_gateway_spend_micros: 4_000_000,
            currency: "usd",
          },
        }),
      );

    const balance = await getBalance({ token: "tok" });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[0]![0]).toMatch(/\/wallet$/);
    expect(fetchMock.mock.calls[1]![0]).toContain("/media/credits");
    expect(balance).toEqual({
      available_micros: 1_200_000,
      reserved_micros: 0,
      plan: null,
      currency: "usd",
    });
  });

  it("propagates non-fallback errors (e.g. 500) instead of masking them", async () => {
    const fetchMock = mockFetch();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ message: "boom" }, { ok: false, status: 500 }),
    );

    await expect(getBalance({ token: "tok" })).rejects.toThrow(/boom/);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("getLedger", () => {
  it("requests GET /wallet/activity with limit + offset and normalizes rows", async () => {
    const fetchMock = mockFetch();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        status: 200,
        data: {
          entries: [
            {
              id: "e1",
              entry_type: "settle",
              reason: "render job",
              amount_micros: -84_000,
              balance_after_micros: 4_916_000,
              job_id: "job-123",
              created_at: "2026-08-19T00:00:00Z",
            },
          ],
          total: 1,
        },
      }),
    );

    const page = await getLedger({ limit: 25, offset: 0 }, { token: "tok" });

    const [url] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/wallet/activity?limit=25&offset=0");
    expect(page.entries).toHaveLength(1);
    expect(page.entries[0]!.amount_micros).toBe(-84_000);
    expect(page.total).toBe(1);
    expect(page.offset).toBe(0);
  });

  it("tolerates a bare array or an {activity} envelope", async () => {
    const fetchMock = mockFetch();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        status: 200,
        data: {
          activity: [
            {
              id: "a1",
              entry_type: "grant",
              reason: "top-up",
              amount_micros: 10_000_000,
              balance_after_micros: null,
              job_id: null,
              created_at: null,
            },
          ],
        },
      }),
    );

    const page = await getLedger({}, { token: "tok" });
    expect(page.entries).toHaveLength(1);
    expect(page.entries[0]!.entry_type).toBe("grant");
  });
});

describe("purchaseQuote", () => {
  it("POSTs /wallet/purchase-quotes with the amount_usd body and returns the breakdown", async () => {
    const fetchMock = mockFetch();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        status: 200,
        data: {
          credit_micros: 20_000_000,
          fee_micros: 1_000_000,
          tax_micros: 0,
          processor_micros: 0,
          total_charge_micros: 21_000_000,
          fee_rate_bps: 500,
          fee_schedule_version: "v1",
          currency: "USD",
        },
      }),
    );

    const quote = await purchaseQuote("20.00", { token: "tok" });

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/wallet/purchase-quotes");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ amount_usd: "20.00" });
    expect(quote.total_charge_micros).toBe(21_000_000);
  });
});

describe("checkout", () => {
  it("POSTs /wallet/checkout with amount_usd and an Idempotency-Key header", async () => {
    const fetchMock = mockFetch();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        status: 200,
        data: {
          payment_intent_id: "pi_1",
          status: "pending",
          currency: "USD",
          credit_micros: 20_000_000,
          fee_micros: 1_000_000,
          tax_micros: 0,
          processor_micros: 0,
          total_charge_micros: 21_000_000,
          fee_rate_bps: 500,
          fee_schedule_version: "v1",
          credit_usd: "20.00",
          total_charge_usd: "21.00",
        },
      }),
    );

    const result = await checkout(
      { amount_usd: "20.00" },
      { token: "tok", idempotencyKey: "key-abc" },
    );

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/wallet/checkout");
    expect(init.method).toBe("POST");
    expect(init.headers["Idempotency-Key"]).toBe("key-abc");
    expect(JSON.parse(init.body)).toEqual({ amount_usd: "20.00" });
    expect(result.payment_intent_id).toBe("pi_1");
    expect(result.credit_micros).toBe(20_000_000);
  });

  it("surfaces a hosted checkout_url when the payment session exists", async () => {
    const fetchMock = mockFetch();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        status: 200,
        data: {
          payment_intent_id: "pi_2",
          status: "pending",
          currency: "USD",
          credit_micros: 100_000_000,
          fee_micros: 0,
          tax_micros: 0,
          processor_micros: 0,
          total_charge_micros: 100_000_000,
          fee_rate_bps: 0,
          fee_schedule_version: "v1",
          credit_usd: "100.00",
          total_charge_usd: "100.00",
          checkout_url: "https://pay.example/abc",
        },
      }),
    );

    const result = await checkout(
      { amount_usd: "100.00", provider: "creem" },
      { token: "tok", idempotencyKey: "key-xyz" },
    );

    const [, init] = fetchMock.mock.calls[0]!;
    expect(JSON.parse(init.body)).toEqual({
      amount_usd: "100.00",
      provider: "creem",
    });
    expect(result.checkout_url).toBe("https://pay.example/abc");
  });
});

describe("wallet transfers", () => {
  it("preserves ambiguous throttling/timeouts and clears only explicit non-mutating failures", () => {
    for (const status of [400, 401, 402, 403, 404, 409, 410, 422]) {
      expect(isDefinitiveTransferFailureStatus(status)).toBe(true);
    }
    for (const status of [0, 408, 425, 429, 500, 502, 503]) {
      expect(isDefinitiveTransferFailureStatus(status)).toBe(false);
    }
  });

  it("resolves only the encoded public handle", async () => {
    const fetchMock = mockFetch();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        status: 200,
        data: { handle: "bob smith", display_name: "Bob", can_receive: true },
      }),
    );

    const recipient = await resolveTransferRecipient("@bob smith", {
      token: "tok",
    });

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/wallet/recipients/bob%20smith");
    expect(init.headers["x-api-key"]).toBe("tok");
    expect(recipient.handle).toBe("bob smith");
  });

  it("sends integer micros with a stable Idempotency-Key", async () => {
    const fetchMock = mockFetch();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        status: 200,
        data: {
          transfer_id: "tr_1",
          recipient: { handle: "bob" },
          amount_micros: 5_000_000,
          amount_usd: "5.00",
          status: "completed",
          mint_first_seq: 42,
          idempotent_replay: false,
          created_at: "2026-08-27T00:00:00Z",
          completed_at: "2026-08-27T00:00:01Z",
          receipt_proof: {
            sequence: 42,
            operation: "transfer",
            operation_hash: "op-hash",
            amount_micros: -5_000_000,
            receipt_hash: "receipt-hash",
            signature: "signature",
          },
        },
      }),
    );

    const result = await sendWalletTransfer(
      {
        source_account_id: "src_personal",
        challenge_id: "challenge_1",
        recipient_handle: "bob",
        amount_micros: 5_000_000,
      },
      "transfer-key",
      { token: "tok" },
    );

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/wallet/transfers");
    expect(init.method).toBe("POST");
    expect(init.headers["Idempotency-Key"]).toBe("transfer-key");
    expect(JSON.parse(init.body)).toEqual({
      source_account_id: "src_personal",
      challenge_id: "challenge_1",
      recipient_handle: "bob",
      amount_micros: 5_000_000,
    });
    expect(result.status).toBe("completed");
    expect(result.receipt_proof?.receipt_hash).toBe("receipt-hash");
  });

  it("recovers an existing transfer by encoded id using GET only", async () => {
    const fetchMock = mockFetch();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        status: 200,
        data: {
          transfer_id: "tr/ambiguous",
          recipient: { handle: "bob" },
          amount_micros: 5_000_000,
          amount_usd: "5.00",
          status: "completed",
          mint_first_seq: 42,
          idempotent_replay: false,
          created_at: null,
          completed_at: null,
          receipt_proof: null,
        },
      }),
    );

    const result = await getWalletTransfer(" tr/ambiguous ", { token: "tok" });

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/wallet/transfers/tr%2Fambiguous");
    expect(init.method).toBe("GET");
    expect(init.body).toBeUndefined();
    expect(result.transfer_id).toBe("tr/ambiguous");
  });
});
