/**
 * Remembers what the buyer was purchasing across the hosted-checkout
 * round-trip, so /billing/success can tell a one-time credit pack from a
 * workspace subscription and watch for the webhook-granted credits to land.
 * Stored in sessionStorage (same tab, cleared with the tab) — no secrets.
 */

const CHECKOUT_INTENT_KEY = "menivor.checkout.intent";
/** Intents older than this are ignored (an abandoned checkout). */
const MAX_INTENT_AGE_MS = 2 * 60 * 60 * 1000;

export type CheckoutKind = "pack" | "subscription";

export interface CheckoutIntent {
  readonly kind: CheckoutKind;
  readonly planKey: string;
  /** Personal credit balance before checkout, when known. */
  readonly baselineCredits: number | null;
  readonly startedAt: number;
}

export function saveCheckoutIntent(
  intent: Omit<CheckoutIntent, "startedAt">,
): void {
  if (typeof window === "undefined") return;
  try {
    const value: CheckoutIntent = { ...intent, startedAt: Date.now() };
    window.sessionStorage.setItem(CHECKOUT_INTENT_KEY, JSON.stringify(value));
  } catch {
    // Storage unavailable: the success page falls back to a generic status.
  }
}

function isIntent(value: unknown): value is CheckoutIntent {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    (v.kind === "pack" || v.kind === "subscription") &&
    typeof v.planKey === "string" &&
    (v.baselineCredits === null || typeof v.baselineCredits === "number") &&
    typeof v.startedAt === "number"
  );
}

export function readCheckoutIntent(): CheckoutIntent | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(CHECKOUT_INTENT_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!isIntent(parsed)) return null;
    if (Date.now() - parsed.startedAt > MAX_INTENT_AGE_MS) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function clearCheckoutIntent(): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(CHECKOUT_INTENT_KEY);
  } catch {
    // Ignore.
  }
}
