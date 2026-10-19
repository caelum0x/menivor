import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiRequest } from "@/src/shared/api";
import {
  getGeneration,
  getGenerationProvenance,
  listGenerations,
  listIdentityOptions,
  settlementProofView,
  type GenerationDetail,
} from "@/lib/media-gateway";

vi.mock("@/src/shared/api", () => ({ apiRequest: vi.fn() }));

describe("durable media generation timeline", () => {
  beforeEach(() => vi.mocked(apiRequest).mockReset());

  it("requests bounded pending recovery through the shared endpoint", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      generations: [],
      limit: 24,
      offset: 0,
      has_more: false,
    });

    await listGenerations(
      { limit: 24, refreshPending: true },
      { token: "mobile-token" },
    );

    expect(apiRequest).toHaveBeenCalledWith(
      "/media/generations?limit=24&refresh_pending=true",
      { options: { token: "mobile-token" } },
    );
  });

  it("uses the owner-scoped identity selector and proof export endpoints", async () => {
    vi.mocked(apiRequest)
      .mockResolvedValueOnce({ identities: [{ passport_id: "psp_1", version: 3 }] })
      .mockResolvedValueOnce({ schema: "menivor.media-provenance/v1", generation_id: "job_1" });

    await listIdentityOptions({ token: "mobile-token" });
    await getGenerationProvenance("job_1", { token: "mobile-token" });

    expect(apiRequest).toHaveBeenNthCalledWith(1, "/media/identities", {
      options: { token: "mobile-token" },
    });
    expect(apiRequest).toHaveBeenNthCalledWith(
      2,
      "/media/generation/job_1/provenance",
      { options: { token: "mobile-token" } },
    );
  });

  it("resumes one job through the same canonical detail endpoint", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      id: "job_1",
      status: "in_progress",
      execution: {
        kind: "prism",
        provider_request_id: "gen_prism_1",
        resumable: true,
      },
      settlement_status: "held",
    });

    const generation = await getGeneration("job_1", { token: "mobile-token" });

    expect(apiRequest).toHaveBeenCalledWith("/media/generation/job_1", {
      options: { token: "mobile-token" },
    });
    expect(generation.execution.resumable).toBe(true);
  });
});

describe("settlement proof presentation", () => {
  // Partial fixture: settlementProofView only reads the settlement fields.
  const generation = (overrides = {}): GenerationDetail =>
    ({
      id: "job_1",
      status: "completed",
      held_cost_micros: 300_000,
      effective_cost_micros: 300_000,
      settlement_status: "settled",
      settlement_rail: "mint",
      execution: { kind: "direct" },
      settlement_evidence: null,
      ...overrides,
    }) as unknown as GenerationDetail;

  it("shows signed captured and released receipts without charging a release", () => {
    const captured = settlementProofView(generation({
      settlement_evidence: {
        verified: true,
        receipt: {
          operation: "hold.capture",
          amount_micros: 300_000,
          receipt_hash: "hash",
          signature: "signature",
        },
      },
    }));
    const released = settlementProofView(generation({
      status: "failed",
      settlement_status: "released",
      settlement_evidence: {
        receipt: {
          operation: "hold.release",
          amount_micros: 300_000,
          receipt_hash: "release-hash",
          signature: "release-signature",
        },
      },
    }));

    expect(captured.outcome).toBe("captured");
    expect(captured.proofLabel).toBe("Verified signed settlement receipt");
    expect(captured.signature).toBe("signature");
    expect(released.outcome).toBe("released");
    expect(released.chargeLabel).toBe("$0.00 charged");
  });

  it("keeps desktop-local work unsigned and zero-cost", () => {
    const proof = settlementProofView(generation({
      execution: { kind: "desktop_local" },
      settlement_rail: "desktop_local",
      settlement_status: "released",
      effective_cost_micros: 900_000,
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

  it("labels an evidence-free failure as unverified, not captured", () => {
    const proof = settlementProofView(generation({
      status: "failed",
      settlement_status: "released",
    }));

    expect(proof.outcome).toBe("unsigned");
    expect(proof.outcomeLabel).toBe("Settlement unverified");
    expect(proof.chargeLabel).toBe("$0.00 charged");
  });
});
