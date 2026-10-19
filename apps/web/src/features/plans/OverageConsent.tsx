"use client";

import * as React from "react";
import { Loader2 } from "lucide-react";
import { apiRequest, type RequestOptions } from "@/src/shared/api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import type { PlanInterval, PlanKey } from "./api";

/**
 * Extra reels past a monthly plan (MG6). Off for everyone until the subscriber
 * turns it on here; the server only grants overage when the newest
 * `plan_overage` consent matches the terms version shown (see
 * apps/api/app/services/billing/dodo_usage.py).
 */
export interface OverageTerms {
  readonly available: boolean;
  readonly cap: number;
  readonly consentKind: string;
  readonly version: string;
  /** Dollars per extra reel as a decimal string, e.g. "0.4285", per plan and interval. */
  readonly perReelUsd: Readonly<Partial<Record<PlanKey, Readonly<Partial<Record<PlanInterval, string>>>>>>;
}

/** Normalize the `overage` block of `GET /billing/monthly-plans` (network input). */
export function overageTermsFrom(raw: unknown): OverageTerms | null {
  if (typeof raw !== "object" || raw === null) return null;
  const rec = raw as Record<string, unknown>;
  const cap = Number(rec.cap);
  const version = typeof rec.version === "string" ? rec.version : "";
  const kind = typeof rec.consent_kind === "string" ? rec.consent_kind : "";
  if (!Number.isFinite(cap) || !version || !kind) return null;
  const prices: Record<string, Record<string, string>> = {};
  const table = (rec.per_reel_usd ?? {}) as Record<string, unknown>;
  for (const [plan, row] of Object.entries(table)) {
    if (typeof row !== "object" || row === null) continue;
    const clean: Record<string, string> = {};
    for (const [interval, price] of Object.entries(row as Record<string, unknown>)) {
      if (typeof price === "string" && /^\d+(\.\d+)?$/.test(price)) clean[interval] = price;
    }
    prices[plan] = clean;
  }
  return {
    available: rec.available === true && cap > 0,
    cap: Math.floor(cap),
    consentKind: kind,
    version,
    perReelUsd: prices,
  };
}

/** `$0.4285`, `$0.39`: exact to the meter price, trailing zeros dropped. */
export function formatRate(usd: string): string {
  const value = Number(usd);
  if (!Number.isFinite(value)) return "";
  let text = value.toFixed(4);
  while (text.endsWith("0") && text.length - text.indexOf(".") > 3) text = text.slice(0, -1);
  return `$${text}`;
}

export async function getOverageTerms(): Promise<OverageTerms | null> {
  const data = await apiRequest<Record<string, unknown> | null>("/billing/monthly-plans", {
    anonymous: true,
  });
  return overageTermsFrom(data?.overage);
}

interface ConsentRow {
  readonly granted?: boolean;
  readonly version?: string;
}

/** True when the caller's newest decision grants exactly these terms. */
export async function getOverageOptIn(terms: OverageTerms, options: RequestOptions): Promise<boolean> {
  const row = await apiRequest<ConsentRow | null>(
    `/me/consent?kind=${encodeURIComponent(terms.consentKind)}`,
    { options },
  );
  return Boolean(row?.granted) && row?.version === terms.version;
}

export async function setOverageOptIn(
  terms: OverageTerms,
  on: boolean,
  options: RequestOptions,
): Promise<void> {
  await apiRequest("/me/consent", {
    method: "PUT",
    body: { kind: terms.consentKind, granted: on, version: terms.version },
    options,
  });
}

/** Live overage terms (public); `null` until loaded or when the API has none. */
export function useOverageTerms(): OverageTerms | null {
  const [terms, setTerms] = React.useState<OverageTerms | null>(null);
  React.useEffect(() => {
    let active = true;
    void getOverageTerms()
      .then((next) => {
        if (active) setTerms(next);
      })
      .catch(() => {
        // No terms -> the page says extra reels are off, which is the server default.
      });
    return () => {
      active = false;
    };
  }, []);
  return terms;
}

/** One sentence for the pricing fine print. */
export function overageDisclosure(terms: OverageTerms | null, interval: PlanInterval): string {
  if (!terms?.available) {
    return "Reels past your plan are never charged automatically; add a credit pack when you need more.";
  }
  const rates = Object.entries(terms.perReelUsd)
    .map(([plan, row]) => {
      const price = row?.[interval];
      return price ? `${plan[0]!.toUpperCase()}${plan.slice(1)} ${formatRate(price)}` : "";
    })
    .filter(Boolean)
    .join(", ");
  return (
    `Extra reels past your plan are off until you turn them on under your plan. ` +
    `When on, each extra reel costs ${rates || "your plan's per-reel rate"} (${interval === "year" ? "yearly" : "monthly"} plans), ` +
    `up to ${terms.cap} a period, and is billed at the end of the billing period.`
  );
}

/**
 * The single opt-in switch for a subscriber. Shows the exact rate before the
 * user turns it on; turning it off takes effect on the next reel.
 */
export function OverageToggle({
  terms,
  planKey,
  planName,
  interval,
  getToken,
}: Readonly<{
  terms: OverageTerms;
  planKey: PlanKey;
  planName: string;
  interval: PlanInterval;
  getToken: () => Promise<string | undefined>;
}>) {
  const [on, setOn] = React.useState<boolean | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const rate = terms.perReelUsd[planKey]?.[interval] ?? "";

  React.useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const token = await getToken();
        if (!token) return;
        const granted = await getOverageOptIn(terms, { token });
        if (active) setOn(granted);
      } catch {
        if (active) setOn(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [terms, getToken]);

  if (!terms.available || !rate) return null;

  const flip = async () => {
    const next = !on;
    setError("");
    setBusy(true);
    try {
      const token = await getToken();
      await setOverageOptIn(terms, next, { token });
      setOn(next);
    } catch (err) {
      setError(friendlyErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-wrap items-start justify-between gap-3 rounded-lg border border-border p-4">
      <div className="max-w-prose space-y-1">
        <p id="overage-title" className="text-sm font-medium">
          Keep making reels past your plan
        </p>
        <p className="text-sm text-muted-foreground">
          {`Off by default. When on, each reel past your ${planName} plan costs ${formatRate(rate)}, up to ${terms.cap} a period, billed at the end of the billing period. Credits you already have are used first.`}
        </p>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={on === true}
        aria-labelledby="overage-title"
        disabled={on === null || busy}
        onClick={() => void flip()}
        className="inline-flex min-w-16 items-center justify-center gap-2 rounded-md border border-border px-3 py-1.5 text-sm disabled:opacity-60 aria-checked:bg-primary aria-checked:text-primary-foreground"
      >
        {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
        {on ? "On" : "Off"}
      </button>
    </div>
  );
}
