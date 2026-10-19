"use client";

import * as React from "react";
import Link from "next/link";
import { Archive, ArrowLeft, Pause, Play, RefreshCw, Scale } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorText, LoadError, errorMessage, useRequestOptions } from "@/src/features/ad-studio/shared";
import { safeServerText } from "@/src/shared/errors";
import { campaignAction, getCampaign, previewAllocation, type Allocation, type Campaign, type CampaignAction } from "./api";
import { STATUS_BADGE } from "./CampaignList";
import { CreativeTable } from "./CreativeTable";
import { formatCount, formatMinor, formatMoney, formatPercent, formatWhen } from "./format";

/** One paid campaign: totals, per-creative report, winner loop and controls. */
export function CampaignView({ campaignKey }: { campaignKey: string }) {
  const requestOptions = useRequestOptions();
  const [campaign, setCampaign] = React.useState<Campaign | null>(null);
  const [preview, setPreview] = React.useState<Allocation | null>(null);
  const [error, setError] = React.useState("");
  const [loadFailure, setLoadFailure] = React.useState<unknown>(null);
  const [attempt, setAttempt] = React.useState(0);
  const [busy, setBusy] = React.useState<CampaignAction | "preview" | "">("");
  const synced = React.useRef(false);

  const act = React.useCallback(
    async (action: CampaignAction) => {
      setBusy(action);
      setError("");
      try {
        setCampaign(await campaignAction(campaignKey, action, await requestOptions()));
        setPreview(null);
      } catch (err) {
        setError(errorMessage(err));
      } finally {
        setBusy("");
      }
    },
    [campaignKey, requestOptions],
  );

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await getCampaign(campaignKey, await requestOptions());
        if (cancelled) return;
        setCampaign(data);
        setLoadFailure(null);
        // Pull fresh numbers once per visit; archived campaigns are left alone.
        if (!synced.current && data.status !== "archived") {
          synced.current = true;
          void act("sync");
        }
      } catch (err) {
        if (!cancelled) setLoadFailure(err);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [campaignKey, requestOptions, act, attempt]);

  async function loadPreview() {
    setBusy("preview");
    setError("");
    try {
      setPreview(await previewAllocation(campaignKey, await requestOptions()));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy("");
    }
  }

  if (!campaign && !loadFailure) return <Skeleton className="h-96" />;
  if (!campaign) {
    return (
      <LoadError
        error={loadFailure}
        onRetry={() => {
          setLoadFailure(null);
          setAttempt((n) => n + 1);
        }}
        fallback="We couldn't load this campaign. Please try again."
      />
    );
  }

  const c = campaign;
  const badge = STATUS_BADGE[c.status] ?? STATUS_BADGE.paused;
  const archived = c.status === "archived";
  const allocation = preview ?? c.allocation;
  const anyLive = c.creatives.some((x) => x.phase === "live");

  return (
    <div className="space-y-6">
      <Link href="/ads" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-4 w-4" aria-hidden /> Paid ads
      </Link>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">{c.name}</h1>
          <p className="text-sm text-muted-foreground">
            {c.platform === "meta" ? "Meta" : "TikTok"} · {formatMinor(c.daily_budget_minor, c.currency)}/day ·{" "}
            {c.audience.countries?.join(", ")} · ages {c.audience.age_min}-{c.audience.age_max} · synced {formatWhen(c.synced_at)}
          </p>
        </div>
        <Badge variant={badge.variant}>{badge.label}</Badge>
      </div>
      {c.error ? <ErrorText message={safeServerText(c.error, "This campaign hit a problem. Try syncing it again.")} /> : null}
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" size="sm" onClick={() => act("sync")} disabled={!!busy || archived}>
          <RefreshCw className="mr-1 h-4 w-4" aria-hidden /> {busy === "sync" ? "Syncing" : "Sync now"}
        </Button>
        {c.status === "active" ? (
          <Button variant="outline" size="sm" onClick={() => act("pause")} disabled={!!busy}>
            <Pause className="mr-1 h-4 w-4" aria-hidden /> Pause
          </Button>
        ) : (
          <Button size="sm" onClick={() => act("start")} disabled={!!busy || archived || !anyLive} title={anyLive ? "" : "No ad is live yet"}>
            <Play className="mr-1 h-4 w-4" aria-hidden /> Start
          </Button>
        )}
        <Button variant="outline" size="sm" onClick={loadPreview} disabled={!!busy || archived || !anyLive}>
          <Scale className="mr-1 h-4 w-4" aria-hidden /> Preview budget split
        </Button>
        <Button variant="ghost" size="sm" onClick={() => act("archive")} disabled={!!busy || archived}>
          <Archive className="mr-1 h-4 w-4" aria-hidden /> Archive
        </Button>
      </div>
      <ErrorText message={error} />
      <Card>
        <CardContent className="grid grid-cols-2 gap-4 p-4 sm:grid-cols-3 lg:grid-cols-6">
          {[
            ["Spend", formatMoney(c.metrics.spend, c.currency)],
            ["Impressions", formatCount(c.metrics.impressions)],
            ["Clicks", formatCount(c.metrics.clicks)],
            ["CTR", formatPercent(c.metrics.ctr)],
            ["Cost per click", formatMoney(c.metrics.cpc, c.currency)],
            ["Cost per lead", formatMoney(c.metrics.cpl, c.currency)],
          ].map(([label, value]) => (
            <div key={label}>
              <p className="text-xs text-muted-foreground">{label}</p>
              <p className="text-lg font-semibold">{value}</p>
            </div>
          ))}
        </CardContent>
      </Card>
      {allocation ? (
        <div className="rounded-lg border border-border p-4 text-sm">
          <p className="font-medium">
            {preview ? "Next budget split (not applied)" : "Winner loop"}: {allocation.reason}
          </p>
          <p className="text-muted-foreground">
            Budget follows each ad&apos;s chance of having the best {allocation.metric === "leads" ? "lead rate" : "click-through rate"}
            {c.auto_optimize ? ", re-split at most once a day while running." : "; auto re-split is off."}
            {c.optimized_at ? ` Last applied ${formatWhen(c.optimized_at)}.` : ""}
          </p>
          {preview ? (
            <Button className="mt-2" size="sm" onClick={() => act("optimize")} disabled={!!busy}>
              Apply this split
            </Button>
          ) : null}
        </div>
      ) : null}
      <CreativeTable creatives={c.creatives} currency={c.currency} preview={preview} />
      {c.metrics.leads === null ? (
        <p className="text-xs text-muted-foreground">
          Cost per lead shows once {c.platform === "meta" ? "Meta" : "TikTok"} reports lead events from the pixel on your landing page.
        </p>
      ) : null}
    </div>
  );
}
