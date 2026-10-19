/**
 * Store-billed generation credits (App Store / Play consumables via RevenueCat).
 *
 * Store builds cannot open the hosted wallet checkout (App Store 3.1.1 / Play
 * payments policy), so credits are sold as consumable in-app products. The flow
 * is server-authoritative end to end:
 *
 *   1. GET  /billing/store/credit-packs — the backend lists which store product
 *      ids it will honour and how many credits each grants. The client never
 *      decides a credit amount.
 *   2. The store sheet completes the purchase (RevenueCat, App User ID = the
 *      backend user id).
 *   3. POST /billing/store/credit-packs/redeem — the backend verifies the
 *      transaction against RevenueCat's subscriber record for the caller and
 *      grants the pack exactly once (the transaction id is the idempotency key).
 *
 * A purchase whose redeem call fails (offline, server hiccup) is persisted
 * locally per account and retried the next time the credits screen opens, so a
 * paid purchase is never silently lost on the client.
 */

import AsyncStorage from "@react-native-async-storage/async-storage";
import { Platform } from "react-native";

import { ApiError, apiRequest, type RequestOptions } from "@/src/shared/api";

import type { StoreCreditPurchase } from "./revenuecat-adapter";

/** A pack the backend honours, keyed by the store product id. */
export interface StoreCreditPack {
  product_id: string;
  credits: number;
  label?: string | null;
}

export interface StoreCreditPacksResponse {
  packs: StoreCreditPack[];
}

export interface StoreCreditRedemption {
  credits_granted: number;
  /** True when this transaction had already been redeemed (idempotent replay). */
  already_redeemed?: boolean;
  balance?: number | null;
}

const PENDING_KEY_PREFIX = "menivor.store-credit-pending.v1.";

/**
 * Packs the backend will redeem. Returns `null` when the backend has no
 * store-credit rail (404/501/503): callers hide the purchase UI entirely, so a
 * buyer can never pay for credits the server cannot grant.
 */
export async function listStoreCreditPacks(
  options?: RequestOptions,
): Promise<StoreCreditPack[] | null> {
  try {
    const result = await apiRequest<StoreCreditPacksResponse>(
      "/billing/store/credit-packs",
      { options },
    );
    const packs = Array.isArray(result?.packs) ? result.packs : [];
    return packs.filter(
      (pack) =>
        typeof pack?.product_id === "string" &&
        pack.product_id.trim().length > 0 &&
        Number.isFinite(pack.credits) &&
        pack.credits > 0,
    );
  } catch (error) {
    if (
      error instanceof ApiError &&
      (error.status === 404 || error.status === 501 || error.status === 503)
    ) {
      return null;
    }
    throw error;
  }
}

/** Ask the backend to verify a store transaction and grant its credits. */
export function redeemStoreCreditPurchase(
  purchase: StoreCreditPurchase,
  options?: RequestOptions,
): Promise<StoreCreditRedemption> {
  return apiRequest<StoreCreditRedemption>("/billing/store/credit-packs/redeem", {
    method: "POST",
    body: {
      product_id: purchase.productId,
      transaction_id: purchase.transactionId,
      purchased_at: purchase.purchasedAt,
      platform: Platform.OS,
    },
    options: { ...options, idempotencyKey: `store-credit-${purchase.transactionId}` },
  });
}

function pendingKey(accountId: string): string {
  return `${PENDING_KEY_PREFIX}${accountId}`;
}

function isPurchase(value: unknown): value is StoreCreditPurchase {
  if (!value || typeof value !== "object") return false;
  const row = value as Record<string, unknown>;
  return (
    typeof row.productId === "string" &&
    typeof row.transactionId === "string" &&
    typeof row.purchasedAt === "string"
  );
}

/** Purchases paid in the store but not yet confirmed by the backend. */
export async function loadPendingStoreCredits(
  accountId: string,
): Promise<StoreCreditPurchase[]> {
  const raw = await AsyncStorage.getItem(pendingKey(accountId));
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter(isPurchase) : [];
  } catch {
    return [];
  }
}

async function savePendingStoreCredits(
  accountId: string,
  rows: readonly StoreCreditPurchase[],
): Promise<void> {
  if (rows.length === 0) {
    await AsyncStorage.removeItem(pendingKey(accountId));
    return;
  }
  await AsyncStorage.setItem(pendingKey(accountId), JSON.stringify(rows));
}

export async function addPendingStoreCredit(
  accountId: string,
  purchase: StoreCreditPurchase,
): Promise<StoreCreditPurchase[]> {
  const current = await loadPendingStoreCredits(accountId);
  const next = [
    ...current.filter((row) => row.transactionId !== purchase.transactionId),
    purchase,
  ];
  await savePendingStoreCredits(accountId, next);
  return next;
}

export async function removePendingStoreCredit(
  accountId: string,
  transactionId: string,
): Promise<StoreCreditPurchase[]> {
  const current = await loadPendingStoreCredits(accountId);
  const next = current.filter((row) => row.transactionId !== transactionId);
  await savePendingStoreCredits(accountId, next);
  return next;
}

/** A redeem failure that will not succeed on retry (the backend rejected it). */
export function isDefinitiveRedeemRejection(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    (error.status === 400 || error.status === 403 || error.status === 409 || error.status === 422)
  );
}
