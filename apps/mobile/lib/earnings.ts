/**
 * Read-only typed client for creator earnings — Expo.
 *
 * The ClipMarket earnings view is backed by the wallet: a clipper's paid-out
 * submissions land as wallet credits, so lifetime + recent earnings are read
 * straight off the wallet balance and activity ledger. Mirrors
 * `apps/api/app/domains/wallet/router.py` (`GET /wallet` → `balance_view`,
 * `GET /wallet/activity` → `{activity: [...]}`).
 *
 * This module is intentionally READ-ONLY — it never mutates wallet state — and
 * is kept separate from the launch-gated top-up client (`lib/wallet.ts`), which
 * it does not touch. Money is integer micros on the wire; format for display
 * with `formatUsdMicros` (`lib/clipmarket.ts`) and never derive totals locally.
 *
 * No route exists to list a clipper's own submissions, so earned-per-clip
 * history is out of scope until a backend route is added.
 */

import { apiRequest as request, type RequestOptions } from "@/src/shared/api";

// --------------------------------------------------------------------------- //
// Types
// --------------------------------------------------------------------------- //

/**
 * Wallet balance snapshot from `GET /wallet` (`balance_view`). All amounts are
 * integer micros except the pre-formatted `*_usd` display strings the server
 * computes.
 */
export interface WalletBalance {
  account_id: string;
  currency: string;
  available_micros: number;
  reserved_micros: number;
  available_usd: string;
  reserved_usd: string;
}

/**
 * One row of the wallet ledger from `GET /wallet/activity` (`entry_view`).
 * `available_delta` is the signed micros change; `available_after_usd` is the
 * server-formatted running balance after the entry.
 */
export interface WalletActivityEntry {
  id: number | null;
  entry_type: string;
  reason: string;
  available_delta: number;
  available_after_usd: string;
  job_id: string | null;
  created_at: string | null;
}

// --------------------------------------------------------------------------- //
// Client
// --------------------------------------------------------------------------- //

/** GET /wallet — the caller's balance snapshot (available + reserved). */
export function getWalletBalance(options?: RequestOptions): Promise<WalletBalance> {
  return request<WalletBalance>("/wallet", { options });
}

/**
 * GET /wallet/activity — the caller's ledger, newest first. The backend accepts
 * `limit` + `offset` for pagination and wraps rows in `{activity: [...]}`; this
 * unwraps to the row array (tolerating a bare-array response too).
 */
export async function getWalletActivity(
  limit = 50,
  offset = 0,
  options?: RequestOptions,
): Promise<WalletActivityEntry[]> {
  const boundedLimit = Math.max(1, Math.min(200, Math.trunc(limit) || 50));
  const boundedOffset = Math.max(0, Math.trunc(offset) || 0);
  const data = await request<
    WalletActivityEntry[] | { activity?: WalletActivityEntry[] }
  >(
    `/wallet/activity?limit=${boundedLimit}&offset=${boundedOffset}`,
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.activity ?? [];
}
