/**
 * Web access = signed-in account + the $1 card check (the active merchant of
 * record: Dodo Payments, or legacy Creem) that unlocks the free reels, plus
 * one-click credit packs. Thin wrappers over the Menivor API.
 */

import { ApiError, apiRequest, type RequestOptions } from "@/src/shared/api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import { checkoutProvider, loadPaymentsMode } from "@/src/shared/payments/mode";

export interface CardCheckStatus {
  /** The account has its free reels (card checked) or has paid before. */
  readonly unlocked: boolean;
  /** Creem is configured, so the $1 check can start. */
  readonly available: boolean;
  readonly credits: number;
  readonly price_usd: number;
  /** Reel credits the $1 itself becomes. */
  readonly card_check_credits: number;
  /** Free reels unlocked by the card check. */
  readonly free_credits: number;
  /** Payments paused: no card check, free monthly reels instead. */
  readonly paused?: boolean;
  /** Active merchant of record ("dodo" | "creem" | "paddle" | "none"). */
  readonly provider?: string;
  /** Free reels per month while paused. */
  readonly free_monthly_reels?: number;
  /** A new account may make its free first reel before the card check. */
  readonly first_reel_ready?: boolean;
}

/** Whether this account may open the create surfaces now, or must unlock first. */
export function accessStatusFor(card: CardCheckStatus): "ready" | "locked" {
  return card.unlocked || card.paused || card.first_reel_ready ? "ready" : "locked";
}

/**
 * Reels one create run starts: the full hook test once unlocked, a single reel
 * on the free first reel (it is one credit, granted before the card check).
 */
export function runSizeFor(card: CardCheckStatus | null, fullRun: number): number {
  if (card && !card.unlocked && !card.paused && card.first_reel_ready) return 1;
  return fullRun;
}

/** Status for an API that predates the card check (404): nothing to unlock. */
export const LEGACY_UNLOCKED: CardCheckStatus = {
  unlocked: true,
  available: false,
  credits: -1,
  price_usd: 1,
  card_check_credits: 1,
  free_credits: 3,
};

export async function getCardCheckStatus(options: RequestOptions): Promise<CardCheckStatus> {
  try {
    return await apiRequest<CardCheckStatus>("/billing/card-check", { options });
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return LEGACY_UNLOCKED;
    throw err;
  }
}

export function startCardCheck(
  next: string,
  options: RequestOptions,
): Promise<{ checkout_url: string; checkout_id?: string }> {
  return apiRequest("/billing/card-check", { method: "POST", body: { next }, options });
}

export interface CreemConfirmResult {
  readonly plan_key: string;
  readonly credits: number;
  readonly balance: number;
  /** Dodo only: the payment has not settled yet (credits follow by webhook). */
  readonly pending?: boolean;
  readonly unlocked?: boolean;
  /** Present when the payment started a monthly plan. */
  readonly subscription?: { readonly plan_key: string; readonly interval: string };
}

/** Credit a Creem payment from its signed return URL (idempotent). */
export function confirmCreemReturn(query: string, options: RequestOptions): Promise<CreemConfirmResult> {
  return apiRequest("/billing/creem/confirm", { method: "POST", body: { query }, options });
}

/** Neutral alias: a confirmed checkout return from any provider. */
export type PaymentConfirmResult = CreemConfirmResult;

export interface DodoReturnIds {
  readonly payment_id?: string;
  readonly subscription_id?: string;
}

/**
 * Credit a Dodo payment/subscription from its return URL. Dodo's redirect is
 * not signed: the API re-reads the payment from Dodo with our key and checks
 * it belongs to the signed-in account (idempotent with the webhook).
 */
export function confirmDodoReturn(ids: DodoReturnIds, options: RequestOptions): Promise<CreemConfirmResult> {
  const body: Record<string, string> = {};
  if (ids.payment_id) body.payment_id = ids.payment_id;
  if (ids.subscription_id) body.subscription_id = ids.subscription_id;
  return apiRequest("/billing/dodo/confirm", { method: "POST", body, options });
}

export type PackKey = "starter" | "pro";

export const CHECKOUT_PAUSED_MESSAGE =
  "Paid plans are back soon. Checkout is paused while we move to a new payment partner. Email support@menivor.com if you need credits now.";

/** Open a credit-pack checkout with the active payment provider. */
export async function startPackCheckout(
  planKey: PackKey,
  options: RequestOptions,
): Promise<{ checkout_url: string }> {
  const provider = checkoutProvider(await loadPaymentsMode());
  if (!provider) {
    throw new ApiError(CHECKOUT_PAUSED_MESSAGE, 403);
  }
  return apiRequest("/billing/checkout", {
    method: "POST",
    body: { plan_key: planKey, provider },
    options,
  });
}

/** True when the current URL is a signed Creem return (checkout id + signature). */
export function isCreemReturn(search: string): boolean {
  const params = new URLSearchParams(search);
  return Boolean(params.get("checkout_id") && params.get("signature"));
}

/** Dodo return ids when the URL is a Dodo checkout return, else null. */
export function dodoReturnIds(search: string): DodoReturnIds | null {
  const params = new URLSearchParams(search);
  if (params.get("provider") !== "dodo") return null;
  const payment = params.get("payment_id")?.trim() ?? "";
  const subscription = params.get("subscription_id")?.trim() ?? "";
  if (!payment && !subscription) return null;
  return {
    ...(payment ? { payment_id: payment } : {}),
    ...(subscription ? { subscription_id: subscription } : {}),
  };
}

/** True when the URL is a Dodo return that failed or was cancelled at checkout. */
export function isFailedDodoReturn(search: string): boolean {
  const params = new URLSearchParams(search);
  const status = (params.get("status") ?? "").toLowerCase();
  return params.get("provider") === "dodo" && (status === "failed" || status === "cancelled");
}

/** Readable, fix-it-yourself copy for access/payment errors. */
export function accessErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 0) return "We could not reach Menivor. Check your connection and try again.";
    if (err.status === 401) return "Your session expired. Sign in again to continue.";
    if (err.status === 403) return CHECKOUT_PAUSED_MESSAGE;
    if (err.status >= 500) return friendlyErrorMessage(err, "The payment page did not open. Try again in a minute.");
    return friendlyErrorMessage(err);
  }
  return friendlyErrorMessage(err, "Something went wrong. Try again.");
}
