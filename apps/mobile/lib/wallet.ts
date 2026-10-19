/**
 * Typed client for wallet top-up (purchase quote + checkout) — Expo.
 *
 * Mirrors `apps/api/app/domains/wallet/router.py` and the web client. Money is
 * integer microdollars on the wire and the **server quote is authoritative** —
 * this client never computes fees, tax or totals locally. Use
 * `formatUsdMicros` (lib/marketplace.ts) for display only.
 *
 * Two endpoints:
 * - `POST /wallet/purchase-quotes` → {@link purchaseQuote}: money breakdown, no
 *   charge. Always available so a client can show a fresh quote.
 * - `POST /wallet/checkout` → {@link createWalletCheckout}: LAUNCH-GATED. Creates
 *   an idempotent payment intent and (when payment rails are live) a hosted
 *   `checkout_url` to redirect the buyer to. During pilot this path is
 *   fail-closed and returns a 403 {@link ApiError} — callers MUST catch it and
 *   render a "top-up not yet enabled" state rather than crash.
 *
 * The checkout requires a stable `Idempotency-Key` so a repeated submit resolves
 * to a single intent (never two charges); {@link newIdempotencyKey} mints one.
 */

import { apiRequest as request, type RequestOptions } from "@/src/shared/api";
import type {
  WalletDestinationBalance,
  WalletDestinationProfile,
  WalletDestinationProfileRequest,
  WalletSavedRecipient,
  WalletReceiveAddress,
  WalletSource,
  WalletTransferChallenge,
  WalletTransferChallengeRequest,
  WalletTransferPolicyRequest,
  WalletTransferPolicyResult,
  WalletTransferRecipient,
  WalletTransferRequest,
  WalletTransferResult,
} from "@reelforge/api-contract";
import { WALLET_PATHS } from "@reelforge/api-contract";

export { isDefinitiveTransferFailureStatus } from "./transfer-outcome";

/**
 * Re-exported pure helpers from the shared contract so wallet screens have a
 * single import surface (`@/lib/wallet`) and never reach into the contract
 * package directly. `parseUsdMicros` turns a decimal USD string into exact
 * integer micros (or `null` when invalid); `formatWalletDestination` renders a
 * handle with `@` while leaving a Mint address intact.
 */
export { formatWalletDestination, parseUsdMicros } from "@reelforge/api-contract";

export type {
  WalletDestinationBalance,
  WalletDestinationProfile,
  WalletDestinationProfileRequest,
  WalletTransferRecipient,
  WalletSavedRecipient,
  WalletSource,
  WalletTransferChallenge,
  WalletTransferChallengeRequest,
  WalletTransferPolicyRequest,
  WalletTransferPolicyResult,
  WalletTransferRequest,
  WalletTransferResult,
} from "@reelforge/api-contract";

// --------------------------------------------------------------------------- //
// Types
// --------------------------------------------------------------------------- //

/**
 * Server-authoritative checkout money breakdown from `POST /wallet/purchase-quotes`.
 * All amounts are integer microdollars; the client renders them but never derives
 * a total itself.
 */
export interface PurchaseQuote {
  credit_micros: number;
  fee_micros: number;
  tax_micros: number;
  processor_micros: number;
  total_charge_micros: number;
  fee_rate_bps: number;
  fee_schedule_version: string;
  currency: string;
}

/** Request body for `POST /wallet/checkout`. */
export interface WalletCheckoutRequest {
  /** Wallet credit to add, as a decimal USD string (e.g. "25"). */
  amount_usd: string;
  /** Hosted payment rail; omitted defaults to "creem" server-side. */
  provider?: "creem" | "stripe";
  /** Fund a workspace shared pool instead of the personal wallet (requires role). */
  workspace_id?: string;
}

/**
 * Checkout intent snapshot from `POST /wallet/checkout`. Carries the same
 * server-computed money breakdown as the quote plus intent identity. When a
 * hosted checkout session was created, `checkout_url` is the provider redirect
 * the buyer must be sent to (via `Linking.openURL`). No credit is granted here —
 * a verified payment webhook fulfils the grant.
 */
export interface WalletCheckoutIntent {
  payment_intent_id: string;
  status: string;
  currency: string;
  credit_micros: number;
  fee_micros: number;
  tax_micros: number;
  processor_micros: number;
  total_charge_micros: number;
  fee_rate_bps: number;
  fee_schedule_version: string;
  payment_provider: "creem" | "stripe";
  settlement_rail: "local" | "mint";
  credit_usd: string;
  total_charge_usd: string;
  /** Provider redirect URL when a hosted session exists; open with Linking. */
  checkout_url?: string;
}

/** Mint-authoritative balance for one authorized personal/workspace source. */
export interface WalletSourceBalance {
  available_micros: number;
  reserved_micros: number;
  plan?: string | null;
  currency: string;
}

// --------------------------------------------------------------------------- //
// Client
// --------------------------------------------------------------------------- //

/**
 * POST /wallet/purchase-quotes — compute the checkout money breakdown
 * (credit + fee + tax + total). No charge is made. The `amountUsd` is a decimal
 * USD string; the server owns all arithmetic (fee schedule, tax, rounding).
 */
export function purchaseQuote(
  amountUsd: string,
  options?: RequestOptions,
): Promise<PurchaseQuote> {
  return request<PurchaseQuote>(WALLET_PATHS.purchaseQuotes, {
    method: "POST",
    body: { amount_usd: amountUsd },
    options,
  });
}

/**
 * POST /wallet/checkout — create (or return the existing) idempotent checkout
 * intent. LAUNCH-GATED: during pilot the server returns a 403 {@link ApiError};
 * callers MUST catch that and render a "not yet enabled" state.
 *
 * `idempotencyKey` is sent as the `Idempotency-Key` header (via the shared
 * client) so a repeated submit never mints a second charge — reuse the same key
 * across retries of one logical top-up.
 */
export function createWalletCheckout(
  body: WalletCheckoutRequest,
  idempotencyKey: string,
  options?: RequestOptions,
): Promise<WalletCheckoutIntent> {
  return request<WalletCheckoutIntent>(WALLET_PATHS.checkout, {
    method: "POST",
    body,
    options: { ...options, idempotencyKey },
  });
}

/** Resolve an exact public handle without returning email or Mint identifiers. */
export function resolveTransferRecipient(
  handle: string,
  options?: RequestOptions,
): Promise<WalletTransferRecipient> {
  const normalized = handle.trim().replace(/^@/, "");
  return request<WalletTransferRecipient>(WALLET_PATHS.recipients(normalized), {
    options,
  });
}

interface SourcesData { sources?: WalletSource[] }

export async function getWalletSources(options?: RequestOptions): Promise<WalletSource[]> {
  const data = await request<SourcesData | WalletSource[]>(WALLET_PATHS.sources, { options });
  return Array.isArray(data) ? data : data.sources ?? [];
}

/** GET /wallet scoped to one opaque source already authorized by the backend. */
export function getWalletSourceBalance(
  sourceAccountId: string,
  options?: RequestOptions,
): Promise<WalletSourceBalance> {
  const query = `?source_account_id=${encodeURIComponent(sourceAccountId.trim())}`;
  return request<WalletSourceBalance>(`${WALLET_PATHS.wallet}${query}`, { options });
}

/** Provision/replay the stable public Mint destination for one source. */
export function getWalletReceiveAddress(
  sourceAccountId: string,
  options?: RequestOptions,
): Promise<WalletReceiveAddress> {
  return request<WalletReceiveAddress>(WALLET_PATHS.receiveAddresses, {
    method: "POST",
    body: { source_account_id: sourceAccountId.trim() },
    options,
  });
}

interface DestinationsData { destinations?: WalletDestinationProfile[] }

/** List every managed workspace, agent, and service receive identity visible to the actor. */
export async function getWalletDestinations(
  options?: RequestOptions,
): Promise<WalletDestinationProfile[]> {
  const data = await request<DestinationsData | WalletDestinationProfile[]>(
    WALLET_PATHS.destinations,
    { options },
  );
  return Array.isArray(data) ? data : data.destinations ?? [];
}

/** Provision a real Mint-backed managed receive identity. */
export function createWalletDestination(
  body: WalletDestinationProfileRequest,
  options?: RequestOptions,
): Promise<WalletDestinationProfile> {
  return request<WalletDestinationProfile>(WALLET_PATHS.destinations, {
    method: "POST",
    body,
    options,
  });
}

/** Disable or re-enable a destination without deleting its account or history. */
export function setWalletDestinationActive(
  destinationId: string,
  active: boolean,
  options?: RequestOptions,
): Promise<WalletDestinationProfile> {
  return request<WalletDestinationProfile>(WALLET_PATHS.destination(destinationId.trim()), {
    method: "PATCH",
    body: { active },
    options,
  });
}

/** Read the Mint-authoritative balance for one managed destination. */
export function getWalletDestinationBalance(
  destinationId: string,
  options?: RequestOptions,
): Promise<WalletDestinationBalance> {
  return request<WalletDestinationBalance>(
    WALLET_PATHS.destinationBalance(destinationId.trim()),
    { options },
  );
}

export function createTransferChallenge(
  body: WalletTransferChallengeRequest,
  idempotencyKey: string,
  options?: RequestOptions,
): Promise<WalletTransferChallenge> {
  return request<WalletTransferChallenge>(WALLET_PATHS.transferChallenges, {
    method: "POST",
    body,
    options: { ...options, idempotencyKey },
  });
}

interface SavedRecipientsData { recipients?: WalletSavedRecipient[] }

export async function getSavedRecipients(
  sourceAccountId: string,
  options?: RequestOptions,
): Promise<WalletSavedRecipient[]> {
  const query = `?source_account_id=${encodeURIComponent(sourceAccountId.trim())}`;
  const data = await request<SavedRecipientsData | WalletSavedRecipient[]>(
    `${WALLET_PATHS.savedRecipients}${query}`,
    { options },
  );
  return Array.isArray(data) ? data : data.recipients ?? [];
}

export function saveTransferRecipient(
  sourceAccountId: string,
  recipientHandle: string,
  label = "",
  options?: RequestOptions,
): Promise<WalletSavedRecipient> {
  return request<WalletSavedRecipient>(WALLET_PATHS.savedRecipients, {
    method: "POST",
    body: { source_account_id: sourceAccountId, recipient_handle: recipientHandle, label },
    options,
  });
}

export function deleteTransferRecipient(
  sourceAccountId: string,
  savedRecipientId: string,
  options?: RequestOptions,
): Promise<{ deleted: boolean }> {
  const query = `?source_account_id=${encodeURIComponent(sourceAccountId.trim())}`;
  return request<{ deleted: boolean }>(
    `${WALLET_PATHS.savedRecipient(savedRecipientId)}${query}`,
    { method: "DELETE", options },
  );
}

/** Send Mint-backed AI tokens exactly once for one logical client operation. */
export function sendWalletTransfer(
  body: WalletTransferRequest,
  idempotencyKey: string,
  options?: RequestOptions,
): Promise<WalletTransferResult> {
  return request<WalletTransferResult>(WALLET_PATHS.transfers, {
    method: "POST",
    body,
    options: { ...options, idempotencyKey },
  });
}

/**
 * GET /wallet/transfer-policy — read the per-workspace/personal send guardrails
 * (per-transfer + UTC-daily ceilings) currently in force for one source.
 *
 * The `source_account_id` selects which authorized source's policy to read.
 * The result mirrors the `limits` block carried on a {@link WalletSource}; a
 * `daily_micros` / `per_transfer_micros` of `0` means "no configured ceiling"
 * (the global hard maximum still applies server-side).
 */
export function getTransferPolicy(
  sourceAccountId: string,
  options?: RequestOptions,
): Promise<WalletTransferPolicyResult> {
  const query = `?source_account_id=${encodeURIComponent(sourceAccountId.trim())}`;
  return request<WalletTransferPolicyResult>(
    `${WALLET_PATHS.transferPolicy}${query}`,
    { options },
  );
}

/**
 * PUT /wallet/transfer-policy — set the send guardrails for one source. Amounts
 * are integer microdollars; pass `0` to disable that specific ceiling. The
 * server re-validates the ranges and returns the authoritative applied limits.
 */
export function setTransferPolicy(
  body: WalletTransferPolicyRequest,
  options?: RequestOptions,
): Promise<WalletTransferPolicyResult> {
  return request<WalletTransferPolicyResult>(WALLET_PATHS.transferPolicy, {
    method: "PUT",
    body,
    options,
  });
}

/** Recover one existing sender-owned transfer without making another send. */
export function getWalletTransfer(
  transferId: string,
  options?: RequestOptions,
): Promise<WalletTransferResult> {
  return request<WalletTransferResult>(WALLET_PATHS.transfer(transferId.trim()), {
    options,
  });
}

/**
 * Mint a stable idempotency key for one logical top-up attempt. Generated once
 * per confirm flow and reused across ambiguous transport retries so the backend
 * collapses them to a single payment intent.
 */
export function newIdempotencyKey(): string {
  const rand = Math.random().toString(36).slice(2, 10);
  return `wallet-topup-${Date.now().toString(36)}-${rand}`;
}

export function newTransferIdempotencyKey(): string {
  const rand = Math.random().toString(36).slice(2, 10);
  return `wallet-transfer-${Date.now().toString(36)}-${rand}`;
}
