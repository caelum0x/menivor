import type { WalletSource, WalletTransferResult } from "@reelforge/api-contract";

export interface PendingTransferV2 {
  version: 2;
  sourceAccountId: string;
  sourceKind: "personal" | "workspace";
  sourceLabel: string;
  challengeId: string;
  challengeExpiresAt: string;
  recipientHandle: string;
  amountMicros: number;
  idempotencyKey: string;
  submitted: boolean;
}

export interface PendingTransferLegacy {
  version: 1;
  recipientHandle: string;
  amountMicros: number;
  idempotencyKey: string;
  submitted: true;
}

export type PendingTransfer = PendingTransferV2 | PendingTransferLegacy;

export function canonicalHandle(value: string): string {
  const destination = value.trim().replace(/^@/, "");
  return destination.startsWith("ait1")
    ? destination
    : destination.toLocaleLowerCase();
}

export function parsePendingTransfer(raw: string | null): PendingTransfer | null {
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as Record<string, unknown>;
    if (
      typeof value.recipientHandle !== "string" ||
      typeof value.amountMicros !== "number" ||
      typeof value.idempotencyKey !== "string"
    ) return null;
    if (
      value.version === 2 &&
      typeof value.sourceAccountId === "string" &&
      (value.sourceKind === "personal" || value.sourceKind === "workspace") &&
      typeof value.sourceLabel === "string" &&
      typeof value.challengeId === "string" &&
      typeof value.challengeExpiresAt === "string"
    ) {
      return {
        version: 2,
        sourceAccountId: value.sourceAccountId,
        sourceKind: value.sourceKind,
        sourceLabel: value.sourceLabel,
        challengeId: value.challengeId,
        challengeExpiresAt: value.challengeExpiresAt,
        recipientHandle: value.recipientHandle,
        amountMicros: value.amountMicros,
        idempotencyKey: value.idempotencyKey,
        submitted: value.submitted === true,
      };
    }
    // Legacy records never contain a source. They may only be rebound to the
    // personal source and fail closed as already submitted.
    return {
      version: 1,
      recipientHandle: value.recipientHandle,
      amountMicros: value.amountMicros,
      idempotencyKey: value.idempotencyKey,
      submitted: true,
    };
  } catch {
    return null;
  }
}

export function sourceForPending(
  pending: PendingTransfer | null,
  sources: WalletSource[],
): WalletSource | null {
  if (pending?.version === 2) {
    return sources.find((source) => source.source_account_id === pending.sourceAccountId) ?? null;
  }
  return sources.find((source) => source.kind === "personal") ?? null;
}

export function pendingMatchesDraft(
  pending: PendingTransfer,
  source: WalletSource,
  recipientHandle: string,
  amountMicros: number,
): boolean {
  return canonicalHandle(pending.recipientHandle) === canonicalHandle(recipientHandle) &&
    pending.amountMicros === amountMicros &&
    (pending.version === 2
      ? pending.sourceAccountId === source.source_account_id
      : source.kind === "personal");
}

export function recoveredMatchesPending(
  pending: PendingTransfer,
  recovered: WalletTransferResult,
): boolean {
  return canonicalHandle(pending.recipientHandle) === canonicalHandle(recovered.recipient.handle) &&
    pending.amountMicros === recovered.amount_micros &&
    (pending.version === 2
      ? pending.sourceAccountId === recovered.source.source_account_id
      : recovered.source.kind === "personal");
}

export function isExpiredUnsubmitted(pending: PendingTransfer, now = Date.now()): boolean {
  return pending.version === 2 &&
    !pending.submitted &&
    Date.parse(pending.challengeExpiresAt) <= now;
}
