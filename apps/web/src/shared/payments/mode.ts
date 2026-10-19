/**
 * Payments mode: which merchant of record takes new payments, read from the
 * `payments` block of `GET /launch/status`. `provider: "none"` means paid
 * plans are paused and every account gets free monthly reels instead.
 *
 * Pure helpers (unit-tested without a network) plus a cached loader.
 */

import { getLaunchStatus } from "@/lib/api";
import type { PaymentsMode } from "@/lib/types";

export type ActivePaymentProvider = PaymentsMode["provider"];

const PROVIDERS: readonly ActivePaymentProvider[] = ["creem", "dodo", "paddle", "none"];

/** Mode used before the status loads or when it fails: the server still enforces. */
export const DEFAULT_PAYMENTS_MODE: PaymentsMode = {
  paused: false,
  provider: "dodo",
  free_monthly_reels: 0,
};

/** Normalize the raw `payments` block (defensive: network input). */
export function paymentsModeFrom(raw: unknown): PaymentsMode {
  if (typeof raw !== "object" || raw === null) return DEFAULT_PAYMENTS_MODE;
  const rec = raw as Record<string, unknown>;
  const provider = PROVIDERS.includes(rec.provider as ActivePaymentProvider)
    ? (rec.provider as ActivePaymentProvider)
    : DEFAULT_PAYMENTS_MODE.provider;
  const paused = rec.paused === true || provider === "none";
  const reels = Number(rec.free_monthly_reels);
  return {
    paused,
    provider: paused ? "none" : provider,
    free_monthly_reels: Number.isFinite(reels) && reels > 0 ? Math.floor(reels) : 0,
  };
}

/** Customer-facing name of the payment provider. */
export function providerLabel(provider: string | null | undefined): string {
  switch (provider) {
    case "dodo":
      return "Dodo Payments";
    case "paddle":
      return "Paddle";
    case "creem":
      return "Creem";
    default:
      return "our payment partner";
  }
}

/** Provider id to send to `POST /billing/checkout` for credit packs. */
export function checkoutProvider(mode: PaymentsMode): "dodo" | "paddle" | "creem" | null {
  if (mode.paused || mode.provider === "none") return null;
  return mode.provider;
}

/** Calm copy for the paused state. */
export function pausedCopy(mode: PaymentsMode): string {
  const reels = mode.free_monthly_reels;
  const allowance = reels > 0 ? `: ${reels} reels every month` : "";
  return `Paid plans are back soon. Free while we move to a new payment partner${allowance}.`;
}

let cached: Promise<PaymentsMode> | null = null;

/** Load (once per page) the payments mode; never rejects. */
export function loadPaymentsMode(): Promise<PaymentsMode> {
  if (!cached) {
    cached = getLaunchStatus()
      .then((status) => paymentsModeFrom(status?.payments))
      .catch(() => {
        cached = null;
        return DEFAULT_PAYMENTS_MODE;
      });
  }
  return cached;
}

/** Test hook: forget the cached status. */
export function resetPaymentsModeCache(): void {
  cached = null;
}
