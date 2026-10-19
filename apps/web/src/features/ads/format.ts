/** Display helpers for paid-ads numbers. `null` means "not reported" and renders as a dash. */

const ZERO_DECIMAL = new Set(["BIF", "CLP", "DJF", "GNF", "ISK", "JPY", "KMF", "KRW", "PYG", "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF"]);

export const DASH = "—";

export function minorFactor(currency: string): number {
  return ZERO_DECIMAL.has((currency || "").toUpperCase()) ? 1 : 100;
}

export function formatMoney(amount: number | null | undefined, currency: string): string {
  if (amount === null || amount === undefined || Number.isNaN(amount)) return DASH;
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency: currency || "USD" }).format(amount);
  } catch {
    return `${amount.toFixed(2)} ${currency}`;
  }
}

export function formatMinor(minor: number | null | undefined, currency: string): string {
  if (minor === null || minor === undefined) return DASH;
  return formatMoney(minor / minorFactor(currency), currency);
}

export function toMinor(amount: number, currency: string): number {
  return Math.round(amount * minorFactor(currency));
}

export function formatPercent(rate: number | null | undefined, digits = 2): string {
  if (rate === null || rate === undefined) return DASH;
  return `${(rate * 100).toFixed(digits)}%`;
}

export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined) return DASH;
  return new Intl.NumberFormat().format(value);
}

export function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "never";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "never" : date.toLocaleString();
}
