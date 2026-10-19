/**
 * Wallet API client — balance, ledger (burn/spend activity), and top-up.
 *
 * Typed fns over the shared `apiRequest` transport (which unwraps the envelope
 * `.data` and sends the Clerk token as `x-api-key`). Money is always integer
 * microdollars (1 USD = 1_000_000 micros) so nothing is ever lost to float.
 */

import {
  ApiError,
  apiRequest,
  type RequestOptions,
} from "@/src/shared/api";
import type {
  WalletDestinationBalance,
  WalletDestinationProfile,
  WalletDestinationProfileRequest,
  WalletReceiveAddress,
  WalletSavedRecipient,
  WalletSource,
  WalletTransferChallenge,
  WalletTransferChallengeRequest,
  WalletTransferRecipient,
  WalletTransferRequest,
  WalletTransferResult,
} from "@reelforge/api-contract";
import { WALLET_PATHS } from "@reelforge/api-contract";

export type {
  WalletDestinationBalance,
  WalletDestinationProfile,
  WalletDestinationProfileRequest,
  WalletReceiveAddress,
  WalletSavedRecipient,
  WalletSource,
  WalletTransferChallenge,
  WalletTransferChallengeRequest,
  WalletTransferRecipient,
  WalletTransferRequest,
  WalletTransferResult,
} from "@reelforge/api-contract";

/** Unified wallet balance. `plan` is present on /wallet, absent on the
 * /media/credits fallback. */
export interface WalletBalance {
  available_micros: number;
  reserved_micros: number;
  plan: string | null;
  currency: string;
}

/** One ledger row — a burn (spend/reserve) or a grant (top-up/refund). */
export interface LedgerEntry {
  id: string;
  /** grant | reserve | settle | release | refund | adjustment | topup */
  entry_type: string;
  reason: string;
  /** Signed micro delta to available balance (negative = burn/spend). */
  amount_micros: number;
  balance_after_micros: number | null;
  job_id: string | null;
  created_at: string | null;
}

/** A page of ledger rows. */
export interface LedgerPage {
  entries: LedgerEntry[];
  total: number | null;
  limit: number;
  offset: number;
}

/** Body for POST /wallet/purchase-quotes and POST /wallet/checkout.
 *
 * `amount_usd` is a decimal USD string (e.g. `"10.00"`) — the backend
 * `PurchaseQuoteRequest` / `CheckoutRequest` DTOs. There is no `package_id` or
 * `amount_micros` field on the real API. */
export interface CheckoutBody {
  amount_usd: string;
  /** Hosted payment rail (defaults to `creem` server-side). */
  provider?: "creem" | "stripe";
  /** Fund a workspace shared pool instead of the personal wallet. */
  workspace_id?: string;
}

/** POST /wallet/purchase-quotes `.data` — the pre-charge money breakdown. */
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

/** POST /wallet/checkout `.data` — the created payment intent (never a credit).
 *
 * Checkout is launch-gated: it records a durable, idempotent intent and, once a
 * Creem hosted session exists, returns its `checkout_url`. Spendable credit is
 * granted only later by the verified `POST /wallet/webhooks/creem`, so this
 * result never carries an inline balance. */
export interface CheckoutResult {
  payment_intent_id: string;
  /** e.g. `pending`. */
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
  /** Hosted-checkout redirect URL, present once a payment session is created. */
  checkout_url?: string;
}

const CREDITS_STATUSES = new Set([404, 501, 503]);

/**
 * HTTP failures that prove the transfer command did not mutate Mint.
 *
 * Everything else is treated as an unknown outcome so the caller retains the
 * original idempotency key. In particular, throttling (429), request timeout
 * (408), Too Early (425), server failures and transport failures are retryable.
 */
const DEFINITIVE_TRANSFER_FAILURE_STATUSES = new Set([
  400, 401, 402, 403, 404, 409, 410, 422,
]);

export function isDefinitiveTransferFailureStatus(status: number): boolean {
  return DEFINITIVE_TRANSFER_FAILURE_STATUSES.has(status);
}

interface CreditsShape {
  available_micros: number;
  reserved_micros: number;
  currency?: string;
}

function creditsToBalance(c: CreditsShape): WalletBalance {
  return {
    available_micros: c.available_micros ?? 0,
    reserved_micros: c.reserved_micros ?? 0,
    plan: null,
    currency: c.currency ?? "usd",
  };
}

/**
 * Fetch the wallet balance from GET /wallet (the real balance route). When that
 * route is not yet live (404/501/503), fall back to the media gateway's GET
 * /media/credits shape so the UI still shows a real, live balance.
 */
export async function getBalance(options?: RequestOptions): Promise<WalletBalance> {
  try {
    return await apiRequest<WalletBalance>(WALLET_PATHS.wallet, { options });
  } catch (err) {
    if (err instanceof ApiError && CREDITS_STATUSES.has(err.status)) {
      const credits = await apiRequest<CreditsShape>("/media/credits", { options });
      return creditsToBalance(credits);
    }
    throw err;
  }
}

/** Fetch the Mint-authoritative balance for one authorized opaque source. */
export function getSourceBalance(
  sourceAccountId: string,
  options?: RequestOptions,
): Promise<WalletBalance> {
  const query = `?source_account_id=${encodeURIComponent(sourceAccountId.trim())}`;
  return apiRequest<WalletBalance>(`${WALLET_PATHS.wallet}${query}`, { options });
}

/** Provision/replay the stable public Mint destination for one source. */
export function getReceiveAddress(
  sourceAccountId: string,
  options?: RequestOptions,
): Promise<WalletReceiveAddress> {
  return apiRequest<WalletReceiveAddress>(WALLET_PATHS.receiveAddresses, {
    method: "POST",
    body: { source_account_id: sourceAccountId.trim() },
    options,
  });
}

interface WalletSourcesData {
  sources?: WalletSource[];
}

/** List personal/workspace sources already filtered by backend authorization. */
export async function getWalletSources(
  options?: RequestOptions,
): Promise<WalletSource[]> {
  const data = await apiRequest<WalletSourcesData | WalletSource[]>(WALLET_PATHS.sources, {
    options,
  });
  return Array.isArray(data) ? data : data.sources ?? [];
}

interface WalletDestinationsData {
  destinations?: WalletDestinationProfile[];
}

export async function getWalletDestinations(
  options?: RequestOptions,
): Promise<WalletDestinationProfile[]> {
  const data = await apiRequest<WalletDestinationsData | WalletDestinationProfile[]>(
    WALLET_PATHS.destinations,
    { options },
  );
  return Array.isArray(data) ? data : data.destinations ?? [];
}

export function createWalletDestination(
  body: WalletDestinationProfileRequest,
  options?: RequestOptions,
): Promise<WalletDestinationProfile> {
  return apiRequest<WalletDestinationProfile>(WALLET_PATHS.destinations, {
    method: "POST",
    body,
    options,
  });
}

export function setWalletDestinationActive(
  destinationId: string,
  active: boolean,
  options?: RequestOptions,
): Promise<WalletDestinationProfile> {
  return apiRequest<WalletDestinationProfile>(WALLET_PATHS.destination(destinationId), {
    method: "PATCH",
    body: { active },
    options,
  });
}

export function getWalletDestinationBalance(
  destinationId: string,
  options?: RequestOptions,
): Promise<WalletDestinationBalance> {
  return apiRequest<WalletDestinationBalance>(
    WALLET_PATHS.destinationBalance(destinationId),
    { options },
  );
}

interface RawLedger {
  entries?: LedgerEntry[];
  activity?: LedgerEntry[];
  rows?: LedgerEntry[];
  total?: number;
}

/** Fetch a page of burn/spend ledger rows (newest first), GET /wallet/activity. */
export async function getLedger(
  params: { limit?: number; offset?: number } = {},
  options?: RequestOptions,
): Promise<LedgerPage> {
  const limit = params.limit ?? 25;
  const offset = params.offset ?? 0;
  const query = `?limit=${encodeURIComponent(limit)}&offset=${encodeURIComponent(offset)}`;
  const raw = await apiRequest<RawLedger | LedgerEntry[]>(`${WALLET_PATHS.activity}${query}`, {
    options,
  });
  const entries = Array.isArray(raw)
    ? raw
    : raw.entries ?? raw.activity ?? raw.rows ?? [];
  const total = Array.isArray(raw) ? null : raw.total ?? null;
  return { entries, total, limit, offset };
}

/**
 * Quote a wallet top-up via POST /wallet/purchase-quotes (no charge). Returns
 * the credit/fee/tax/total breakdown so the UI can show the real total before a
 * checkout is started.
 */
export function purchaseQuote(
  amountUsd: string,
  options?: RequestOptions,
): Promise<PurchaseQuote> {
  return apiRequest<PurchaseQuote>(WALLET_PATHS.purchaseQuotes, {
    method: "POST",
    body: { amount_usd: amountUsd },
    options,
  });
}

/**
 * Start a wallet top-up via POST /wallet/checkout. Sends an `Idempotency-Key`
 * so an ambiguous retry resolves to a single intent (never two charges). The
 * response is a payment intent + (when a hosted session exists) a
 * `checkout_url`; spendable credit is granted later by the payment webhook.
 */
export function checkout(
  body: CheckoutBody,
  options?: RequestOptions,
): Promise<CheckoutResult> {
  return apiRequest<CheckoutResult>(WALLET_PATHS.checkout, {
    method: "POST",
    body,
    options,
  });
}

/** Resolve an exact public handle without exposing email or Mint account ids. */
export function resolveTransferRecipient(
  handle: string,
  options?: RequestOptions,
): Promise<WalletTransferRecipient> {
  const normalized = handle.trim().replace(/^@/, "");
  return apiRequest<WalletTransferRecipient>(WALLET_PATHS.recipients(normalized), {
    options,
  });
}

/** Create the server-bound review using the same key as the eventual send. */
export function createTransferChallenge(
  body: WalletTransferChallengeRequest,
  idempotencyKey: string,
  options?: RequestOptions,
): Promise<WalletTransferChallenge> {
  return apiRequest<WalletTransferChallenge>(WALLET_PATHS.transferChallenges, {
    method: "POST",
    body,
    options: { ...options, idempotencyKey },
  });
}

interface SavedRecipientsData {
  recipients?: WalletSavedRecipient[];
}

export async function getSavedRecipients(
  sourceAccountId: string,
  options?: RequestOptions,
): Promise<WalletSavedRecipient[]> {
  const query = `?source_account_id=${encodeURIComponent(sourceAccountId.trim())}`;
  const data = await apiRequest<SavedRecipientsData | WalletSavedRecipient[]>(
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
  return apiRequest<WalletSavedRecipient>(WALLET_PATHS.savedRecipients, {
    method: "POST",
    body: {
      source_account_id: sourceAccountId,
      recipient_handle: recipientHandle,
      label,
    },
    options,
  });
}

export function deleteTransferRecipient(
  sourceAccountId: string,
  savedRecipientId: string,
  options?: RequestOptions,
): Promise<{ deleted: boolean }> {
  const query = `?source_account_id=${encodeURIComponent(sourceAccountId.trim())}`;
  return apiRequest<{ deleted: boolean }>(
    `${WALLET_PATHS.savedRecipient(savedRecipientId)}${query}`,
    { method: "DELETE", options },
  );
}

/** Atomically send Mint-backed AI tokens; reuse the key for transport retries. */
export function sendWalletTransfer(
  body: WalletTransferRequest,
  idempotencyKey: string,
  options?: RequestOptions,
): Promise<WalletTransferResult> {
  return apiRequest<WalletTransferResult>(WALLET_PATHS.transfers, {
    method: "POST",
    body,
    options: { ...options, idempotencyKey },
  });
}

/** Recover one existing sender-owned transfer without creating or retrying it. */
export function getWalletTransfer(
  transferId: string,
  options?: RequestOptions,
): Promise<WalletTransferResult> {
  return apiRequest<WalletTransferResult>(WALLET_PATHS.transfer(transferId.trim()), {
    options,
  });
}

/** Integer microdollars → "$0.084" / "$12.50" display. */
export function formatUsdMicros(micros: number): string {
  const usd = (micros || 0) / 1_000_000;
  const digits = usd !== 0 && Math.abs(usd) < 0.1 ? 3 : 2;
  return `$${usd.toFixed(digits)}`;
}

/** Integer microdollars → a decimal USD string (e.g. `"10.00"`) for the API. */
export function microsToUsdString(micros: number): string {
  return ((micros || 0) / 1_000_000).toFixed(2);
}

/** Generate an Idempotency-Key for a top-up submission. */
export function newIdempotencyKey(): string {
  const g = globalThis as { crypto?: { randomUUID?: () => string } };
  if (g.crypto?.randomUUID) return g.crypto.randomUUID();
  return `topup-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

/** Generate one stable key for a logical person-to-person send attempt. */
export function newTransferIdempotencyKey(): string {
  const g = globalThis as { crypto?: { randomUUID?: () => string } };
  if (g.crypto?.randomUUID) return `transfer-${g.crypto.randomUUID()}`;
  return `transfer-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}
