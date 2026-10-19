"use client";

import * as React from "react";
import { toCents, type Offer } from "./api";

export interface PricedTitle {
  readonly id: string;
  readonly title: string;
}

/**
 * One row per title: a buy price (one field) and a rental (price and hours, two fields).
 * Saving calls `onSave` with the offer body; empty fields are left as they are.
 */
export function TitleOffers({ titles, offers, onSave }: Readonly<{
  titles: readonly PricedTitle[];
  offers: readonly Offer[];
  onSave: (body: Record<string, unknown>) => Promise<void>;
}>) {
  if (titles.length === 0) return null;
  return (
    <ul aria-label="Prices per title" className="space-y-2">
      {titles.map((title) => (
        <TitleRow key={title.id} title={title} offers={offers.filter((o) => o.title_id === title.id && o.active)}
          onSave={onSave} />
      ))}
    </ul>
  );
}

function TitleRow({ title, offers, onSave }: Readonly<{
  title: PricedTitle;
  offers: readonly Offer[];
  onSave: (body: Record<string, unknown>) => Promise<void>;
}>) {
  const buy = offers.find((o) => o.kind === "tvod");
  const rent = offers.find((o) => o.kind === "rental");
  const [buyPrice, setBuyPrice] = React.useState(buy ? (buy.price_cents / 100).toFixed(2) : "");
  const [rentPrice, setRentPrice] = React.useState(rent ? (rent.price_cents / 100).toFixed(2) : "");
  const [hours, setHours] = React.useState(String(rent?.rental_hours ?? 48));
  const [error, setError] = React.useState("");

  const save = async () => {
    const bodies: Record<string, unknown>[] = [];
    if (buyPrice.trim()) {
      const cents = toCents(buyPrice);
      if (cents === null) return setError("Set a buy price of at least 0.50.");
      bodies.push({ kind: "tvod", name: `Own ${title.title}`.slice(0, 120), price_cents: cents, title_id: title.id });
    }
    if (rentPrice.trim()) {
      const cents = toCents(rentPrice);
      const h = Math.round(Number(hours));
      if (cents === null) return setError("Set a rental price of at least 0.50.");
      if (!Number.isFinite(h) || h < 1 || h > 720) return setError("A rental lasts 1 to 720 hours.");
      bodies.push({ kind: "rental", name: `Rent ${title.title}`.slice(0, 120), price_cents: cents, title_id: title.id,
        rental_hours: h });
    }
    if (bodies.length === 0) return setError("Set a buy or a rental price.");
    setError("");
    try {
      for (const body of bodies) await onSave(body);
    } catch (err) {
      setError(err instanceof Error ? err.message : "The prices could not be saved.");
    }
  };

  return (
    <li className="flex flex-wrap items-center gap-2 text-sm" data-title={title.id}>
      <span className="min-w-32 flex-1 truncate">{title.title}</span>
      <label>
        Buy
        <input className="ml-1 w-20 rounded border px-2 py-1" inputMode="decimal" value={buyPrice}
          onChange={(e) => setBuyPrice(e.target.value)} />
      </label>
      <label>
        Rent
        <input className="ml-1 w-20 rounded border px-2 py-1" inputMode="decimal" value={rentPrice}
          onChange={(e) => setRentPrice(e.target.value)} />
      </label>
      <label>
        Hours
        <input className="ml-1 w-16 rounded border px-2 py-1" inputMode="numeric" value={hours}
          onChange={(e) => setHours(e.target.value)} />
      </label>
      <button type="button" className="rounded-lg border px-3 py-1" onClick={() => void save()}>Save prices</button>
      {error ? <p role="alert" className="w-full">{error}</p> : null}
    </li>
  );
}
