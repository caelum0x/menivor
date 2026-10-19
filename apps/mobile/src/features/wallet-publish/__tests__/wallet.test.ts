/**
 * Unit tests for the wallet top-up client (lib/wallet.ts). The shared transport
 * is mocked (mock lives here in the test only) so we assert the exact endpoint,
 * method, body and idempotency wiring — the client must never compute money and
 * must forward the launch-gate error unchanged.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiRequest } from "@/src/shared/api";
import {
  createWalletDestination,
  createWalletCheckout,
  createTransferChallenge,
  deleteTransferRecipient,
  getSavedRecipients,
  getWalletDestinationBalance,
  getWalletDestinations,
  getWalletSourceBalance,
  getWalletReceiveAddress,
  getWalletSources,
  getWalletTransfer,
  isDefinitiveTransferFailureStatus,
  newIdempotencyKey,
  newTransferIdempotencyKey,
  purchaseQuote,
  resolveTransferRecipient,
  setWalletDestinationActive,
  sendWalletTransfer,
  saveTransferRecipient,
  type PurchaseQuote,
  type WalletCheckoutIntent,
} from "@/lib/wallet";

vi.mock("@/src/shared/api", () => ({
  apiRequest: vi.fn(),
}));

const mockRequest = apiRequest as unknown as {
  mockResolvedValueOnce: (v: unknown) => void;
  mockRejectedValueOnce: (v: unknown) => void;
  mock: { calls: unknown[][] };
};

class FakeApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const QUOTE: PurchaseQuote = {
  credit_micros: 25_000_000,
  fee_micros: 900_000,
  tax_micros: 0,
  processor_micros: 750_000,
  total_charge_micros: 25_900_000,
  fee_rate_bps: 300,
  fee_schedule_version: "2026-01",
  currency: "USD",
};

const INTENT: WalletCheckoutIntent = {
  ...QUOTE,
  payment_provider: "creem",
  settlement_rail: "local",
  payment_intent_id: "pi_123",
  status: "pending",
  credit_usd: "$25.00",
  total_charge_usd: "$25.90",
  checkout_url: "https://checkout.example/session/abc",
};

beforeEach(() => {
  (apiRequest as unknown as { mockReset: () => void }).mockReset();
});

describe("purchaseQuote", () => {
  it("POSTs the amount to /wallet/purchase-quotes and returns the server quote", async () => {
    mockRequest.mockResolvedValueOnce(QUOTE);

    const result = await purchaseQuote("25", { token: "k" });

    expect(result).toEqual(QUOTE);
    const [path, init] = mockRequest.mock.calls[0];
    expect(path).toBe("/wallet/purchase-quotes");
    expect(init).toEqual({
      method: "POST",
      body: { amount_usd: "25" },
      options: { token: "k" },
    });
  });

  it("does not derive any money locally (forwards server totals verbatim)", async () => {
    mockRequest.mockResolvedValueOnce(QUOTE);
    const result = await purchaseQuote("25");
    expect(result.total_charge_micros).toBe(25_900_000);
    expect(result.fee_micros).toBe(900_000);
  });
});

describe("createWalletCheckout", () => {
  it("POSTs to /wallet/checkout and threads the idempotency key into options", async () => {
    mockRequest.mockResolvedValueOnce(INTENT);

    const result = await createWalletCheckout(
      { amount_usd: "25" },
      "idem-key-1",
      { token: "k" },
    );

    expect(result.checkout_url).toBe("https://checkout.example/session/abc");
    const [path, init] = mockRequest.mock.calls[0] as [string, any];
    expect(path).toBe("/wallet/checkout");
    expect(init.method).toBe("POST");
    expect(init.body).toEqual({ amount_usd: "25" });
    expect(init.options.idempotencyKey).toBe("idem-key-1");
    expect(init.options.token).toBe("k");
  });

  it("propagates a 403 launch-gate error to the caller (never swallowed)", async () => {
    mockRequest.mockRejectedValueOnce(new FakeApiError(403, "checkout disabled"));

    await expect(
      createWalletCheckout({ amount_usd: "25" }, "idem-key-2"),
    ).rejects.toMatchObject({ status: 403 });
  });
});

describe("newIdempotencyKey", () => {
  it("returns distinct, non-empty keys", () => {
    const a = newIdempotencyKey();
    const b = newIdempotencyKey();
    expect(a.length).toBeGreaterThan(0);
    expect(a).not.toBe(b);
  });
});

describe("wallet transfers", () => {
  it("manages Mint-backed workspace, agent, and service receive identities", async () => {
    const destination = {
      destination_id: "dest_agent",
      handle: "agent:caption-bot",
      display_name: "Caption Bot",
      kind: "agent",
      scope: "workspace",
      workspace_source_account_id: "workspace_1",
      active: true,
      address: "ait1qcaption",
    };
    mockRequest.mockResolvedValueOnce({ destinations: [destination] });
    mockRequest.mockResolvedValueOnce(destination);
    mockRequest.mockResolvedValueOnce({
      destination,
      currency: "AIT",
      available_micros: 3_000_000,
      held_micros: 250_000,
    });
    mockRequest.mockResolvedValueOnce({ ...destination, active: false });

    expect(await getWalletDestinations({ token: "k" })).toEqual([destination]);
    await createWalletDestination(
      {
        kind: "agent",
        slug: "caption-bot",
        display_name: "Caption Bot",
        workspace_source_account_id: "workspace_1",
      },
      { token: "k" },
    );
    const balance = await getWalletDestinationBalance(" dest_agent ", { token: "k" });
    await setWalletDestinationActive(" dest_agent ", false, { token: "k" });

    expect(balance.available_micros).toBe(3_000_000);
    expect(mockRequest.mock.calls[0]).toEqual([
      "/wallet/destinations",
      { options: { token: "k" } },
    ]);
    expect((mockRequest.mock.calls[1] as any)[1]).toMatchObject({
      method: "POST",
      body: {
        kind: "agent",
        slug: "caption-bot",
        display_name: "Caption Bot",
        workspace_source_account_id: "workspace_1",
      },
    });
    expect(mockRequest.mock.calls[2][0]).toBe(
      "/wallet/destinations/dest_agent/balance",
    );
    expect((mockRequest.mock.calls[3] as any)[1]).toMatchObject({
      method: "PATCH",
      body: { active: false },
    });
  });

  it("preserves ambiguous throttling/timeouts and clears only explicit non-mutating failures", () => {
    for (const status of [400, 401, 402, 403, 404, 409, 410, 422]) {
      expect(isDefinitiveTransferFailureStatus(status)).toBe(true);
    }
    for (const status of [0, 408, 425, 429, 500, 502, 503]) {
      expect(isDefinitiveTransferFailureStatus(status)).toBe(false);
    }
  });

  it("resolves an encoded public handle", async () => {
    mockRequest.mockResolvedValueOnce({
      handle: "bob smith",
      display_name: "Bob",
      can_receive: true,
    });

    await resolveTransferRecipient("@bob smith", { token: "k" });

    const [path, init] = mockRequest.mock.calls[0] as [string, any];
    expect(path).toBe("/wallet/recipients/bob%20smith");
    expect(init.options.token).toBe("k");
  });

  it("sends integer micros and the caller's stable idempotency key", async () => {
    mockRequest.mockResolvedValueOnce({
      transfer_id: "tr_1",
      recipient: { handle: "bob" },
      amount_micros: 2_000_000,
      amount_usd: "2.00",
      status: "completed",
      mint_first_seq: 7,
      idempotent_replay: false,
      created_at: null,
      completed_at: null,
      receipt_proof: null,
    });

    await sendWalletTransfer(
      {
        source_account_id: "src_personal",
        challenge_id: "challenge_1",
        recipient_handle: "bob",
        amount_micros: 2_000_000,
      },
      "send-key",
      { token: "k" },
    );

    const [path, init] = mockRequest.mock.calls[0] as [string, any];
    expect(path).toBe("/wallet/transfers");
    expect(init.body).toEqual({
      source_account_id: "src_personal",
      challenge_id: "challenge_1",
      recipient_handle: "bob",
      amount_micros: 2_000_000,
    });
    expect(init.options.idempotencyKey).toBe("send-key");
    expect(init.options.token).toBe("k");
  });

  it("recovers an existing transfer by encoded id with GET semantics", async () => {
    mockRequest.mockResolvedValueOnce({
      transfer_id: "tr/ambiguous",
      recipient: { handle: "bob" },
      amount_micros: 2_000_000,
      amount_usd: "2.00",
      status: "completed",
      mint_first_seq: 7,
      idempotent_replay: false,
      created_at: null,
      completed_at: null,
      receipt_proof: {
        sequence: 7,
        operation: "transfer",
        operation_hash: "op-hash",
        amount_micros: -2_000_000,
        receipt_hash: "receipt-hash",
        signature: "signature",
      },
    });

    const result = await getWalletTransfer(" tr/ambiguous ", { token: "k" });

    const [path, init] = mockRequest.mock.calls[0] as [string, any];
    expect(path).toBe("/wallet/transfers/tr%2Fambiguous");
    expect(init).toEqual({ options: { token: "k" } });
    expect(result.receipt_proof?.receipt_hash).toBe("receipt-hash");
  });

  it("generates distinct transfer keys", () => {
    expect(newTransferIdempotencyKey()).not.toBe(newTransferIdempotencyKey());
  });

  it("uses source, challenge and saved-recipient endpoints without exposing refs", async () => {
    const source = { source_account_id: "workspace_1", kind: "workspace", label: "Studio", role: "owner", can_send: true, limits: { per_transfer_micros: 10, daily_micros: 20, daily_used_micros: 0, daily_remaining_micros: 20 } };
    mockRequest.mockResolvedValueOnce({ sources: [source] });
    mockRequest.mockResolvedValueOnce({ challenge_id: "ch_1", source, recipient: { handle: "bob", display_name: "Bob" }, amount_micros: 2, binding_sha256: "hash", expires_at: "2099-01-01T00:00:00Z" });
    mockRequest.mockResolvedValueOnce({ recipients: [] });
    mockRequest.mockResolvedValueOnce({ saved_recipient_id: "saved_1", handle: "bob", display_name: "Bob", label: "" });
    mockRequest.mockResolvedValueOnce({ deleted: true });
    expect(await getWalletSources()).toEqual([source]);
    await createTransferChallenge({ source_account_id: "workspace_1", recipient_handle: "bob", amount_micros: 2 }, "stable");
    await getSavedRecipients("workspace_1");
    await saveTransferRecipient("workspace_1", "bob");
    await deleteTransferRecipient("workspace_1", "saved_1");
    expect((mockRequest.mock.calls[1] as any)[1].options.idempotencyKey).toBe("stable");
    expect((mockRequest.mock.calls[4] as any)[1].method).toBe("DELETE");
  });

  it("loads the authoritative balance for the selected opaque source", async () => {
    mockRequest.mockResolvedValueOnce({
      available_micros: 7_000_000,
      reserved_micros: 1_000_000,
      currency: "usd",
    });

    const balance = await getWalletSourceBalance(" workspace/alpha ", { token: "k" });

    const [path, init] = mockRequest.mock.calls[0] as [string, any];
    expect(path).toBe("/wallet?source_account_id=workspace%2Falpha");
    expect(init).toEqual({ options: { token: "k" } });
    expect(balance.available_micros).toBe(7_000_000);
  });

  it("provisions the stable receive address for the selected source", async () => {
    mockRequest.mockResolvedValueOnce({
      address: "ait1qworkspace",
      source: { source_account_id: "workspace_1" },
    });

    const result = await getWalletReceiveAddress(" workspace_1 ", { token: "k" });

    const [path, init] = mockRequest.mock.calls[0] as [string, any];
    expect(path).toBe("/wallet/receive-addresses");
    expect(init.method).toBe("POST");
    expect(init.body).toEqual({ source_account_id: "workspace_1" });
    expect(result.address).toBe("ait1qworkspace");
  });
});
