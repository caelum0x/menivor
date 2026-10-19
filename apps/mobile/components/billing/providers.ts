/**
 * Pure, dependency-free helpers for presenting payment providers in the
 * checkout UI. The set of providers actually offered to a buyer comes from
 * GET /billing/providers (only rails whose secrets are configured server-side);
 * these helpers just turn a provider id into display copy and pick a sensible
 * default. No secrets and no network here.
 */

import { PAYMENT_PROVIDERS, type PaymentProvider } from "@/lib/types";

/** Human-readable label for a provider id (widened `string` tolerated). */
export function providerLabel(provider: PaymentProvider | string): string {
  switch (provider) {
    case "stripe":
      return "Stripe";
    case "iyzico":
      return "iyzico";
    case "creem":
      return "Creem";
    case "polar":
      return "Polar";
    default:
      return provider
        ? provider.charAt(0).toUpperCase() + provider.slice(1)
        : "Card";
  }
}

/** Short one-line hint about a provider (for a subtitle under a chip row). */
export function providerHint(provider: PaymentProvider | string): string {
  switch (provider) {
    case "stripe":
      return "Card checkout via Stripe.";
    case "iyzico":
      return "Local card checkout for Turkey.";
    case "creem":
      return "Merchant-of-record checkout via Creem.";
    case "polar":
      return "Merchant-of-record checkout via Polar.";
    default:
      return "";
  }
}

/**
 * Order the enabled providers for display, keeping the canonical
 * {@link PAYMENT_PROVIDERS} order and appending any unknown (forward-compat)
 * providers the backend may return after them. Pure — never mutates `enabled`.
 */
export function orderProviders(
  enabled: readonly (PaymentProvider | string)[],
): (PaymentProvider | string)[] {
  const set = new Set(enabled);
  const known = PAYMENT_PROVIDERS.filter((p) => set.has(p));
  const extras = enabled.filter(
    (p) => !(PAYMENT_PROVIDERS as readonly string[]).includes(p),
  );
  return [...known, ...extras];
}

/**
 * Pick the default provider to pre-select from the enabled set: prefer Stripe
 * when available, otherwise the first enabled provider (in display order).
 * Returns `null` when nothing is enabled.
 */
export function defaultProvider(
  enabled: readonly (PaymentProvider | string)[],
): PaymentProvider | string | null {
  const ordered = orderProviders(enabled);
  if (ordered.length === 0) return null;
  return ordered.includes("stripe") ? "stripe" : ordered[0];
}
