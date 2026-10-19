"use client";

import * as React from "react";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import { connectPayments, createCoupon, createOffer, formatCents, formatPrice, getSales, getStudioCommerce, listCoupons,
  stopCoupon, stopOffer, type Coupon, type CouponInput, type Sales, type StudioCommerce } from "./api";
import { TitleOffers, type PricedTitle } from "./TitleOffers";

/**
 * Sell on my channel: connect my own payment account, then set a monthly price for members,
 * per-title buy and rental prices, coupons, and see gross sales per title.
 */
export function StudioSales({ titles = [] }: Readonly<{ titles?: readonly PricedTitle[] }>) {
  const getApiToken = useApiToken();
  const [view, setView] = React.useState<StudioCommerce | null>(null);
  const [price, setPrice] = React.useState("5");
  const [error, setError] = React.useState("");

  const load = React.useCallback(async () => {
    try {
      setView(await getStudioCommerce({ token: await getApiToken() }));
    } catch (err) {
      setError(friendlyErrorMessage(err, "Sales could not load."));
    }
  }, [getApiToken]);

  React.useEffect(() => {
    void load();
  }, [load]);

  if (!view) return error ? <p role="alert" className="text-sm">{error}</p> : null;

  const connect = async () => {
    try {
      const { connect_url } = await connectPayments({ token: await getApiToken() });
      window.location.assign(connect_url);
    } catch (err) {
      setError(friendlyErrorMessage(err, "The payment connection could not open."));
    }
  };
  const addMembers = async () => {
    const cents = Math.round(Number(price) * 100);
    if (!Number.isFinite(cents) || cents < 50) {
      setError("Set a price of at least 0.50.");
      return;
    }
    try {
      await createOffer({ kind: "svod", name: "Members", price_cents: cents, interval: "month" }, { token: await getApiToken() });
      setError("");
      await load();
    } catch (err) {
      setError(friendlyErrorMessage(err, "The offer could not be saved."));
    }
  };

  return (
    <section aria-label="Sell on my channel" className="space-y-3 rounded-xl border border-border p-3">
      <h2 className="text-sm font-semibold">Sell on my channel</h2>
      {!view.account.connected ? (
        <button type="button" className="rounded-lg bg-foreground px-3 py-1 text-sm text-background" onClick={() => void connect()}>
          Connect my payment account
        </button>
      ) : (
        <>
          <p className="text-sm">Payments go to your own account. We never hold your viewers&apos; money.</p>
          <label className="text-sm">
            Monthly price for members
            <input className="ml-2 w-20 rounded border px-2 py-1" inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} />
          </label>
          <button type="button" className="ml-2 rounded-lg border px-3 py-1 text-sm" onClick={() => void addMembers()}>Save</button>
          <TitleOffers titles={titles} offers={view.offers} onSave={async (body) => {
            await createOffer(body, { token: await getApiToken() });
            await load();
          }} />
          <ul className="space-y-1 text-sm">
            {view.offers.map((offer) => (
              <li key={offer.id} data-offer={offer.id}>
                {offer.name}: {formatPrice(offer)} {offer.active ? (
                  <button type="button" className="underline" onClick={async () => {
                    await stopOffer(offer.id, { token: await getApiToken() }).catch(() => undefined);
                    await load();
                  }}>Stop selling</button>
                ) : "(stopped)"}
              </li>
            ))}
          </ul>
          <Coupons />
          <SalesTable />
        </>
      )}
      {error ? <p role="alert" className="text-sm">{error}</p> : null}
    </section>
  );
}

function useToken() {
  const getApiToken = useApiToken();
  return React.useCallback(async () => ({ token: await getApiToken() }), [getApiToken]);
}

/** Coupons are discounts on the creator's own payment account; only the code is kept here. */
function Coupons() {
  const auth = useToken();
  const [coupons, setCoupons] = React.useState<readonly Coupon[]>([]);
  const [code, setCode] = React.useState("");
  const [off, setOff] = React.useState("");
  const [ends, setEnds] = React.useState("");
  const [error, setError] = React.useState("");

  const load = React.useCallback(async () => {
    try {
      setCoupons((await listCoupons(await auth())).coupons);
    } catch (err) {
      setError(friendlyErrorMessage(err, "Coupons could not load."));
    }
  }, [auth]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const add = async () => {
    const value = off.trim();
    const percent = value.endsWith("%");
    const number = Number(value.replace("%", "").replace(",", "."));
    if (!/^[A-Za-z0-9]{3,16}$/.test(code.trim())) return setError("A code is 3 to 16 letters or digits.");
    if (!Number.isFinite(number) || number <= 0 || (percent && number > 100)) {
      return setError("Write a percent with a % sign at the end, or an amount in dollars.");
    }
    if (!ends) return setError("Pick an end date.");
    const expires = new Date(`${ends}T23:59:59Z`).toISOString();
    const body: CouponInput = percent
      ? { code: code.trim(), kind: "percent", percent: number, expires_at: expires }
      : { code: code.trim(), kind: "amount", amount_cents: Math.round(number * 100), expires_at: expires };
    try {
      await createCoupon(body, await auth());
      setCode("");
      setOff("");
      setError("");
      await load();
    } catch (err) {
      setError(friendlyErrorMessage(err, "The coupon could not be saved."));
    }
  };

  return (
    <div aria-label="Coupons" className="space-y-2 text-sm">
      <h3 className="font-semibold">Coupons</h3>
      <div className="flex flex-wrap items-center gap-2">
        <label>Code<input className="ml-1 w-28 rounded border px-2 py-1" value={code} onChange={(e) => setCode(e.target.value)} /></label>
        <label>Off<input className="ml-1 w-20 rounded border px-2 py-1" value={off} onChange={(e) => setOff(e.target.value)} /></label>
        <label>Ends<input type="date" className="ml-1 rounded border px-2 py-1" value={ends} onChange={(e) => setEnds(e.target.value)} /></label>
        <button type="button" className="rounded-lg border px-3 py-1" onClick={() => void add()}>Add coupon</button>
      </div>
      <ul className="space-y-1">
        {coupons.map((c) => (
          <li key={c.code} data-coupon={c.code}>
            {c.code}, ends {c.expires_at.slice(0, 10)} {c.active ? (
              <button type="button" className="underline" onClick={async () => {
                await stopCoupon(c.code, await auth()).catch(() => undefined);
                await load();
              }}>Stop</button>
            ) : "(stopped)"}
          </li>
        ))}
      </ul>
      {error ? <p role="alert">{error}</p> : null}
    </div>
  );
}

/** Gross sales per title from purchase grants (refunds and disputes taken out). */
function SalesTable() {
  const auth = useToken();
  const [sales, setSales] = React.useState<Sales | null>(null);

  React.useEffect(() => {
    let live = true;
    void (async () => {
      const data = await getSales(30, await auth()).catch(() => null);
      if (live) setSales(data);
    })();
    return () => {
      live = false;
    };
  }, [auth]);

  if (!sales) return null;
  return (
    <div aria-label="Sales per title" className="space-y-1 text-sm">
      <h3 className="font-semibold">Sales, last {sales.days} days</h3>
      <p>{formatCents(sales.sales_totals.gross_cents, sales.sales_totals.currency)} from {sales.sales_totals.grants} sales</p>
      <ul className="space-y-1">
        {sales.sales.filter((row) => row.grants > 0).map((row) => (
          <li key={row.title_id} data-sales={row.title_id}>
            {row.title}: {formatCents(row.gross_cents, row.currency)} ({row.grants})
          </li>
        ))}
      </ul>
    </div>
  );
}
