import { describe, expect, it } from "vitest";
import {
  isExpiredUnsubmitted,
  parsePendingTransfer,
  pendingMatchesDraft,
  recoveredMatchesPending,
  sourceForPending,
} from "./transfer-pending";

const personal = {
  source_account_id: "personal_1", kind: "personal" as const, label: "Personal",
  role: "owner", can_send: true,
  limits: { per_transfer_micros: 100, daily_micros: 200, daily_used_micros: 0, daily_remaining_micros: 200 },
};
const workspace = { ...personal, source_account_id: "workspace_1", kind: "workspace" as const, label: "Studio" };

describe("persisted mobile transfers", () => {
  it("migrates legacy sends as submitted and confines them to personal wallets", () => {
    const legacy = parsePendingTransfer(JSON.stringify({
      recipientHandle: "Bob", amountMicros: 10, idempotencyKey: "old", submitted: false,
    }))!;

    expect(legacy.version).toBe(1);
    expect(legacy.submitted).toBe(true);
    expect(sourceForPending(legacy, [workspace, personal])?.source_account_id).toBe("personal_1");
    expect(pendingMatchesDraft(legacy, workspace, "bob", 10)).toBe(false);
  });

  it("restores the exact v2 source, challenge and stable send key", () => {
    const v2 = parsePendingTransfer(JSON.stringify({
      version: 2, sourceAccountId: "workspace_1", sourceKind: "workspace", sourceLabel: "Studio",
      challengeId: "ch_1", challengeExpiresAt: "2020-01-01T00:00:00Z",
      recipientHandle: "@Bob", amountMicros: 10, idempotencyKey: "stable", submitted: false,
    }))!;

    expect(sourceForPending(v2, [personal, workspace])?.source_account_id).toBe("workspace_1");
    expect(pendingMatchesDraft(v2, workspace, "bob", 10)).toBe(true);
    expect(isExpiredUnsubmitted(v2)).toBe(true);
    expect(isExpiredUnsubmitted({ ...v2, submitted: true })).toBe(false);
    expect(pendingMatchesDraft({ ...v2, submitted: true }, workspace, "bob", 10)).toBe(true);

    const result = {
      transfer_id: "tr_1", source: { source_account_id: "workspace_1", kind: "workspace" as const, label: "Studio" },
      recipient: { handle: "bob", display_name: "Bob", kind: "personal" as const }, amount_micros: 10, amount_usd: "0.00001", status: "completed",
      mint_first_seq: 1, idempotent_replay: false, created_at: null, completed_at: null,
      receipt_proof: null, verification: { status: "pending" as const },
    };
    expect(recoveredMatchesPending(v2, result)).toBe(true);

    const legacy = parsePendingTransfer(JSON.stringify({
      recipientHandle: "Bob", amountMicros: 10, idempotencyKey: "old", submitted: false,
    }))!;
    expect(recoveredMatchesPending(legacy, result)).toBe(false);
  });

  it("matches handles case-insensitively but Mint addresses exactly", () => {
    const pending = parsePendingTransfer(JSON.stringify({
      version: 2, sourceAccountId: "personal_1", sourceKind: "personal", sourceLabel: "Personal",
      challengeId: "ch_address", challengeExpiresAt: "2099-01-01T00:00:00Z",
      recipientHandle: "ait1qAddress", amountMicros: 10, idempotencyKey: "address", submitted: true,
    }))!;

    expect(pendingMatchesDraft(pending, personal, "ait1qAddress", 10)).toBe(true);
    expect(pendingMatchesDraft(pending, personal, "ait1qaddress", 10)).toBe(false);
    expect(pendingMatchesDraft({ ...pending, recipientHandle: "Bob" }, personal, "@bob", 10)).toBe(true);
  });
});
