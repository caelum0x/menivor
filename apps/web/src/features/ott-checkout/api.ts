/**
 * Channel sales (MV13). The creator sells through their own payment account
 * (connected on a hosted page; no key is typed here). The viewer pays on the
 * creator's own checkout page.
 */

import { API_BASE, apiRequest, type RequestOptions } from "@/src/shared/api";

export type OfferKind = "svod" | "tvod" | "rental";

export interface Offer {
  readonly id: string;
  readonly kind: OfferKind;
  readonly title_id: string | null;
  readonly sku: string;
  readonly name: string;
  readonly price_cents: number;
  readonly currency: string;
  readonly interval: "month" | "year" | null;
  readonly rental_hours: number | null;
  readonly active: boolean;
}

export interface StudioCommerce {
  readonly account: { readonly connected: boolean; readonly provider?: string; readonly mode?: string; readonly error?: string };
  readonly offers: readonly Offer[];
}

export async function publicOffers(handle: string): Promise<{ offers: readonly Offer[]; checkout_open: boolean }> {
  const h = encodeURIComponent(handle);
  const route = `/ott/c/${h}/offers`;
  const response = await fetch(`${API_BASE}${route}`);
  if (!response.ok) return { offers: [], checkout_open: false };
  return ((await response.json()) as { data: { offers: Offer[]; checkout_open: boolean } }).data;
}

export async function startCheckout(handle: string, session: string, offerId: string): Promise<string> {
  const h = encodeURIComponent(handle);
  const route = `/ott/viewers/${h}/checkout`;
  const response = await fetch(`${API_BASE}${route}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-OTT-Viewer": session },
    body: JSON.stringify({ offer_id: offerId }),
  });
  const body = (await response.json().catch(() => ({}))) as { data?: { url?: string }; message?: string };
  if (!response.ok || !body.data?.url) throw new Error(body.message || "Checkout could not open. Try again.");
  return body.data.url;
}

export const getStudioCommerce = (options?: RequestOptions) =>
  apiRequest<StudioCommerce>("/ott/studio/commerce", { options });
export const connectPayments = (options?: RequestOptions) =>
  apiRequest<{ connect_url: string }>("/ott/studio/commerce/connect", { method: "POST", options });
export const createOffer = (body: Record<string, unknown>, options?: RequestOptions) =>
  apiRequest<Offer>("/ott/studio/commerce/offers", { method: "POST", body, options });
export function stopOffer(id: string, options?: RequestOptions) {
  const oid = encodeURIComponent(id);
  return apiRequest<Offer>(`/ott/studio/commerce/offers/${oid}/deactivate`, { method: "POST", options });
}

export function formatPrice(offer: Pick<Offer, "price_cents" | "currency" | "interval" | "rental_hours" | "kind">): string {
  const amount = new Intl.NumberFormat("en-US", { style: "currency", currency: offer.currency }).format(offer.price_cents / 100);
  if (offer.kind === "svod") return `${amount} a ${offer.interval ?? "month"}`;
  if (offer.kind === "rental") return `${amount} for ${offer.rental_hours ?? 48} hours`;
  return amount;
}

/* ---- Wave Q QM1.3: per-title prices, coupons and sales ---- */

export interface Coupon {
  readonly code: string;
  readonly expires_at: string;
  readonly active: boolean;
}

export interface TitleSales {
  readonly title_id: string;
  readonly title: string;
  readonly gross_cents: number;
  readonly grants: number;
  readonly currency: string;
}

export interface Sales {
  readonly days: number;
  readonly sales: readonly TitleSales[];
  readonly sales_totals: { readonly gross_cents: number; readonly grants: number; readonly currency: string };
}

export type CouponInput =
  | { code: string; kind: "percent"; percent: number; expires_at: string }
  | { code: string; kind: "amount"; amount_cents: number; currency?: string; expires_at: string };

export const listCoupons = (options?: RequestOptions) =>
  apiRequest<{ coupons: Coupon[] }>("/ott/studio/commerce/coupons", { options });
export const createCoupon = (body: CouponInput, options?: RequestOptions) =>
  apiRequest<Coupon>("/ott/studio/commerce/coupons", { method: "POST", body, options });
export function stopCoupon(code: string, options?: RequestOptions) {
  const c = encodeURIComponent(code);
  return apiRequest<Coupon>(`/ott/studio/commerce/coupons/${c}/stop`, { method: "POST", options });
}
export const getSales = (days: number, options?: RequestOptions) =>
  apiRequest<Sales>(`/ott/studio/commerce/sales?days=${days}`, { options });

/** "9.99" to 999; null below 0.50 or when it is not a number. */
export function toCents(raw: string): number | null {
  const cents = Math.round(Number(raw.replace(",", ".")) * 100);
  return Number.isFinite(cents) && cents >= 50 ? cents : null;
}

export function formatCents(cents: number, currency: string): string {
  if (currency === "mixed") return (cents / 100).toFixed(2);
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(cents / 100);
}

/** True once a live grant unlocks `titleId` (or any title, for a subscription). */
export async function hasUnlock(handle: string, session: string, titleId?: string): Promise<boolean> {
  const h = encodeURIComponent(handle);
  const response = await fetch(`${API_BASE}/ott/viewers/${h}/entitlements`, { headers: { "X-OTT-Viewer": session } });
  if (!response.ok) return false;
  const body = (await response.json()) as { data?: { items?: { kind: string; title_id: string | null; status: string }[] } };
  return (body.data?.items ?? []).some((e) => e.status === "active" && (e.kind === "svod" || !titleId || e.title_id === titleId));
}
