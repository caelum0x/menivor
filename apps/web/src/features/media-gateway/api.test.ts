import { afterEach, describe, expect, it, vi } from "vitest";

import {
  getGeneration,
  getGenerationProvenance,
  listGenerations,
  listIdentityOptions,
  settlementProofView,
} from "./api";

function response(data: unknown): Response {
  return {
    ok: true,
    status: 200,
    statusText: "OK",
    text: async () => JSON.stringify({ status: 200, data }),
    headers: { get: () => null },
  } as unknown as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("durable generation timeline", () => {
  it("requests recovery and returns the canonical safe page", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      response({
        generations: [
          {
            id: "job_1",
            model: "kwaivgi/kling-v1.6",
            modality: "video",
            provider: "prism:kling-fal",
            status: "completed",
            seconds: 5,
            held_cost_micros: 420_000,
            actual_cost_micros: 400_000,
            effective_cost_micros: 400_000,
            settlement_status: "settled",
            output_url: "https://cdn.example/out.mp4",
            error: "",
            correlation_id: "gateway_job_1",
            created_at: "2026-08-27T00:00:00Z",
            updated_at: "2026-08-27T00:01:00Z",
            is_terminal: true,
          },
        ],
        limit: 24,
        offset: 0,
        has_more: false,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const page = await listGenerations(
      { limit: 24, refreshPending: true },
      { token: "token" },
    );

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(String(url)).toContain(
      "/media/generations?limit=24&refresh_pending=true",
    );
    expect(init.headers["x-api-key"]).toBe("token");
    expect(page.generations[0]!.correlation_id).toBe("gateway_job_1");
    expect(page.generations[0]!.settlement_status).toBe("settled");
  });

  it("loads owned locked identities and exports one canonical proof", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({ identities: [{ passport_id: "psp_1", version: 3 }] }))
      .mockResolvedValueOnce(response({
        schema: "menivor.media-provenance/v1",
        generation_id: "job_1",
        identity: { passport_id: "psp_1", version: 3 },
      }));
    vi.stubGlobal("fetch", fetchMock);

    const options = await listIdentityOptions({ token: "token" });
    const proof = await getGenerationProvenance("job_1", { token: "token" });

    expect(options.identities[0]!.passport_id).toBe("psp_1");
    expect(String(fetchMock.mock.calls[0]![0])).toContain("/media/identities");
    expect(String(fetchMock.mock.calls[1]![0])).toContain(
      "/media/generation/job_1/provenance",
    );
    expect(proof.schema).toBe("menivor.media-provenance/v1");
  });

  it("resumes one durable job through the canonical detail endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(response({
      id: "job_1",
      status: "in_progress",
      execution: {
        kind: "prism",
        provider_request_id: "gen_prism_1",
        resumable: true,
      },
      settlement_status: "held",
      settlement_evidence: null,
    }));
    vi.stubGlobal("fetch", fetchMock);

    const generation = await getGeneration("job_1", { token: "token" });

    expect(String(fetchMock.mock.calls[0]![0])).toContain("/media/generation/job_1");
    expect(generation.execution.provider_request_id).toBe("gen_prism_1");
    expect(generation.execution.resumable).toBe(true);
    expect(generation.settlement_status).toBe("held");
  });
});

describe("settlement proof presentation", () => {
  const generation = (overrides: Record<string, unknown> = {}) => ({
    id: "job_1",
    status: "completed",
    held_cost_micros: 420_000,
    effective_cost_micros: 420_000,
    settlement_status: "settled",
    settlement_rail: "mint",
    execution: { kind: "prism" },
    settlement_evidence: null,
    ...overrides,
  }) as never;

  it("derives capture and release only from the receipt operation", () => {
    const captured = settlementProofView(generation({
      settlement_evidence: {
        verified: true,
        receipt: {
          operation: "hold.capture",
          amount_micros: 400_000,
          receipt_hash: "receipt-hash",
          signature: "receipt-signature",
        },
      },
    }));
    const released = settlementProofView(generation({
      status: "failed",
      settlement_status: "released",
      settlement_evidence: {
        receipt: {
          operation: "hold.release",
          amount_micros: 420_000,
          receipt_hash: "release-hash",
          signature: "release-signature",
        },
      },
    }));

    expect(captured).toMatchObject({
      outcome: "captured",
      chargeLabel: "$0.40 charged",
      signed: true,
      verified: true,
      receiptHash: "receipt-hash",
      signature: "receipt-signature",
    });
    expect(released).toMatchObject({
      outcome: "released",
      chargeLabel: "$0.00 charged",
      signed: true,
    });
  });

  it("keeps desktop-local execution zero-cost and unsigned", () => {
    const proof = settlementProofView(generation({
      provider: "desktop-local",
      execution: { kind: "desktop_local" },
      settlement_rail: "desktop_local",
      settlement_status: "released",
      effective_cost_micros: 999_000,
      settlement_evidence: {
        receipt: {
          operation: "hold.capture",
          amount_micros: 999_000,
          receipt_hash: "must-not-surface",
          signature: "must-not-surface",
        },
      },
    }));

    expect(proof).toMatchObject({
      outcome: "unsigned",
      outcomeLabel: "Unsigned local execution",
      chargeLabel: "$0.00 charged",
      receiptHash: null,
      signature: null,
      signed: false,
      verified: false,
    });
  });

  it("does not claim a failed row is released or charged without evidence", () => {
    const proof = settlementProofView(generation({
      status: "failed",
      settlement_status: "released",
      settlement_evidence: null,
    }));

    expect(proof.outcome).toBe("unsigned");
    expect(proof.outcomeLabel).toBe("Settlement unverified");
    expect(proof.chargeLabel).toBe("$0.00 charged");
  });
});
