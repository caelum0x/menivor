"use client";

import * as React from "react";
import Link from "next/link";
import { Activity, Loader2, Sparkles } from "lucide-react";

import { Badge, type BadgeVariant } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ErrorText, errorMessage } from "@/src/features/ad-studio/shared";
import { useStableRequestOptions } from "@/src/features/review-queue/use-stable-options";
import { getReport, makeVariations, pct, type FatigueCreative, type FatigueReport, type FatigueStatus } from "./api";

const DAYS = [7, 14, 30] as const;
const STATUS: Record<FatigueStatus, { label: string; variant: BadgeVariant }> = {
  fatigued: { label: "Fatigued", variant: "destructive" },
  watch: { label: "Watch", variant: "default" },
  fresh: { label: "Fresh", variant: "success" },
  not_enough_data: { label: "Not enough data", variant: "outline" },
};

export function Sparkline({ values, label }: { values: (number | null)[]; label: string }) {
  const points = values.map((v, i) => [i, v] as const).filter((p): p is readonly [number, number] => p[1] !== null);
  if (points.length < 2) return <span className="text-xs text-muted-foreground">-</span>;
  const max = Math.max(...points.map((p) => p[1])) || 1;
  const w = 120;
  const h = 32;
  const step = w / Math.max(values.length - 1, 1);
  const d = points.map(([i, v], n) => `${n ? "L" : "M"}${(i * step).toFixed(1)},${(h - (v / max) * (h - 4) - 2).toFixed(1)}`).join(" ");
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label={label}>
      <path d={d} fill="none" stroke="currentColor" strokeWidth={1.5} className="text-primary" />
    </svg>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={cn("text-sm font-medium", value === "not reported" && "font-normal text-muted-foreground")}>{value}</dd>
    </div>
  );
}

function CreativeCard({ c }: { c: FatigueCreative }) {
  const requestOptions = useStableRequestOptions();
  const [busy, setBusy] = React.useState(false);
  const [queued, setQueued] = React.useState<number | null>(null);
  const [error, setError] = React.useState("");
  const status = STATUS[c.status];

  const vary = async () => {
    setBusy(true);
    setError("");
    try {
      const out = await makeVariations(c.ad_account_id, c.entity_id, await requestOptions());
      setQueued(out.action.credits_estimate);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <article className="glass-subtle space-y-3 rounded-2xl p-4" aria-label={c.entity_name}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-medium">{c.entity_name}</p>
          <p className="text-xs text-muted-foreground">
            {c.ad_account_name} - {c.days} days, {c.impressions.toLocaleString("en-US")} impressions
          </p>
        </div>
        <Badge variant={status.variant}>{status.label}</Badge>
      </div>
      <div className="space-y-1">
        <div className="flex justify-between text-xs text-muted-foreground">
          <span>Fatigue score</span>
          <span>{c.score === null ? "-" : `${c.score} / 100`}</span>
        </div>
        <div className="h-1.5 overflow-hidden rounded-full bg-white/10" aria-hidden>
          <div
            className={cn("h-full rounded-full", c.status === "fatigued" ? "bg-destructive" : c.status === "watch" ? "bg-primary" : "bg-success")}
            style={{ width: `${c.score ?? 0}%` }}
          />
        </div>
      </div>
      <dl className="grid grid-cols-3 gap-3">
        <Metric label="Frequency" value={c.frequency === null ? "not reported" : c.frequency.toFixed(1)} />
        <Metric label="CTR decay" value={pct(c.ctr_decay)} />
        <Metric label="CPA drift" value={pct(c.cpa_drift)} />
      </dl>
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span>Daily CTR</span>
        <Sparkline values={c.series.map((s) => s.ctr)} label={`Daily CTR for ${c.entity_name}`} />
      </div>
      {c.reasons.length ? (
        <ul className="list-disc space-y-0.5 pl-5 text-xs text-muted-foreground">
          {c.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      ) : null}
      {queued !== null ? (
        <p className="text-sm" role="status">
          3 variations queued for approval ({queued} credits).{" "}
          <Link href="/agent" className="text-primary underline-offset-4 hover:underline">
            Approve in Agent
          </Link>
        </p>
      ) : c.status === "fatigued" || c.status === "watch" ? (
        <Button size="sm" variant="outline" onClick={() => void vary()} disabled={busy}>
          {busy ? <Loader2 className="animate-spin" aria-hidden /> : <Sparkles aria-hidden />} Make variations
        </Button>
      ) : null}
      {error ? <ErrorText message={error} /> : null}
    </article>
  );
}

/** Creatify-AdMax-style fatigue view: which ads are wearing out, and fresh variations behind approval. */
export function AdFatigue() {
  const requestOptions = useStableRequestOptions();
  const [days, setDays] = React.useState<number>(14);
  const [report, setReport] = React.useState<FatigueReport | null>(null);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const data = await getReport(days, await requestOptions());
        if (live) setReport(data);
      } catch (err) {
        if (live) setError(errorMessage(err));
      }
    })();
    return () => {
      live = false;
    };
  }, [days, requestOptions]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-1">
          <h1 className="flex items-center gap-2 text-2xl font-semibold">
            <Activity className="size-6 text-primary" aria-hidden /> Ad fatigue
          </h1>
          <p className="max-w-2xl text-sm text-muted-foreground">
            Ads wear out when the same people see them too often. Watch frequency, CTR and CPA, and refresh tired ads
            before they cost more.
          </p>
        </div>
        <div className="flex gap-2" role="group" aria-label="Window">
          {DAYS.map((d) => (
            <button
              key={d}
              type="button"
              aria-pressed={days === d}
              onClick={() => setDays(d)}
              className={cn("glass-subtle rounded-full px-3 py-1.5 text-xs", days === d && "border-primary/70 font-medium text-primary")}
            >
              {d} days
            </button>
          ))}
        </div>
      </div>
      {error ? <ErrorText message={error} /> : null}
      {!report && !error ? <Loader2 className="size-5 animate-spin" aria-label="Loading" /> : null}
      {report && report.accounts.length === 0 ? (
        <div className="glass-subtle space-y-2 rounded-2xl p-8 text-center">
          <p className="font-medium">No ad account connected</p>
          <p className="text-sm text-muted-foreground">Connect Meta, TikTok or another ad account to see fatigue.</p>
          <Link href="/settings/integrations" className="text-sm text-primary underline-offset-4 hover:underline">
            Connect an ad account
          </Link>
        </div>
      ) : null}
      {report && report.accounts.length > 0 ? (
        <>
          <p className="text-sm text-muted-foreground">
            {report.counts.fatigued} fatigued, {report.counts.watch} to watch, {report.counts.fresh} fresh
          </p>
          {report.creatives.length ? (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {report.creatives.map((c) => (
                <CreativeCard key={`${c.ad_account_id}:${c.entity_id}`} c={c} />
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No delivery in this window. Refresh reports in Integrations.</p>
          )}
        </>
      ) : null}
    </div>
  );
}
