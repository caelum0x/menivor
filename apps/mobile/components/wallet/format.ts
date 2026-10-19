/**
 * Pure presentation helpers for the wallet & billing screens. No network, no
 * secrets, no local money arithmetic beyond display formatting — every amount
 * on the wire is already a server-authoritative integer (microdollars for the
 * wallet, cents for invoices) and these helpers only render it.
 */

const MICRODOLLARS_PER_USD = 1_000_000;
const CENTS_PER_UNIT = 100;

/** Signed USD from integer microdollars, e.g. -1_500_000 → "-$1.50". */
export function formatMicrosSigned(micros: number | undefined | null): string {
  const value = (micros ?? 0) / MICRODOLLARS_PER_USD;
  const sign = value > 0 ? "+" : "";
  return `${sign}$${value.toFixed(2)}`;
}

/** Display-only USD from an integer-cents amount, e.g. 2599 → "$25.99". */
export function formatCents(
  cents: number | undefined | null,
  currency = "USD",
): string {
  const value = (cents ?? 0) / CENTS_PER_UNIT;
  const symbol = currency.toUpperCase() === "USD" ? "$" : `${currency.toUpperCase()} `;
  return `${symbol}${value.toFixed(2)}`;
}

/** Compact human date from an ISO-8601 string, e.g. "Sep 8, 2026". "" when blank. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const parsed = Date.parse(iso);
  if (!Number.isFinite(parsed)) return "";
  const d = new Date(parsed);
  const months = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
  ] as const;
  return `${months[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`;
}

/** Title-case a lower_snake or lowercase status token, e.g. "past_due" → "Past due". */
export function formatStatus(status: string | null | undefined): string {
  const raw = (status ?? "").trim();
  if (!raw) return "Unknown";
  const spaced = raw.replace(/[_-]+/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}
