"use client";

import * as React from "react";
import Link from "next/link";

import { Skeleton } from "@/components/ui/skeleton";
import { LoadError, useRequestOptions } from "@/src/features/ad-studio/shared";
import { formatPercent } from "@/src/features/ads/format";
import { getNetworkReport, type NetworkReport as ReportData, type Proposal } from "./api";
import { NetworkTable } from "./NetworkTable";
import { ProposalCard } from "./ProposalCard";
import { ProposeForm } from "./ProposeForm";

/** Which network pays off, plus today's proposed budget split. */
export function NetworkReport() {
  const requestOptions = useRequestOptions();
  const [data, setData] = React.useState<ReportData | null>(null);
  const [error, setError] = React.useState<unknown>(null);
  const [reloadKey, setReloadKey] = React.useState(0);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const next = await getNetworkReport(await requestOptions());
        if (!cancelled) {
          setData(next);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError(err);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [requestOptions, reloadKey]);

  const onProposal = React.useCallback((_p: Proposal) => setReloadKey((k) => k + 1), []);

  if (!data && !error) {
    return (
      <div className="space-y-3" aria-busy="true">
        <Skeleton className="h-40" />
        <Skeleton className="h-56" />
      </div>
    );
  }
  if (!data) {
    return (
      <LoadError
        error={error}
        onRetry={() => {
          setError(null);
          setReloadKey((k) => k + 1);
        }}
        fallback="We couldn't load the network report. Please try again."
      />
    );
  }

  const hasData = data.networks.length > 0;
  return (
    <div className="space-y-8">
      {!data.gate.enabled ? (
        <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
          {data.gate.reason}. The report still reads campaigns you already synced, and hand-entered networks work now.
          Applying a split to Meta or TikTok needs the ad platform connection.
        </p>
      ) : null}

      <section aria-labelledby="report-networks" className="space-y-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="report-networks" className="text-lg font-semibold">
            Cost per {data.metric === "leads" ? "lead" : "click"} by network
          </h2>
          <p className="text-xs text-muted-foreground">
            Lifetime totals from each campaign&apos;s last sync, in {data.currency}.{" "}
            {data.metric === "clicks" ? "Leads are compared only when every network reports them." : ""}
          </p>
        </div>
        {hasData ? (
          <NetworkTable report={data} />
        ) : (
          <div className="rounded-lg border border-dashed p-6 text-sm text-muted-foreground">
            No campaign data yet. <Link href="/ads/new" className="underline">Launch a campaign</Link> and sync it, or add
            results for a network you run by hand below.
          </div>
        )}
        {data.excluded.length ? (
          <ul className="space-y-1 text-xs text-muted-foreground">
            {data.excluded.map((e) => (
              <li key={e.key}>
                {e.name || e.key}: {e.reason}
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      <section aria-labelledby="report-split" className="space-y-3">
        <h2 id="report-split" className="text-lg font-semibold">
          Budget split
        </h2>
        <p className="max-w-3xl text-sm text-muted-foreground">
          Menivor estimates each network&apos;s chance of having the lowest cost per result and suggests moving budget toward
          it. Every network keeps at least {formatPercent(data.settings.min_share, 0)} so it can keep proving itself. A new
          proposal is made each day once you have created one.
        </p>
        {data.latest ? <ProposalCard proposal={data.latest} onChange={onProposal} /> : null}
        <ProposeForm report={data} onProposed={onProposal} />
      </section>

      {data.history.length > 1 ? (
        <section aria-labelledby="report-history" className="space-y-2">
          <h2 id="report-history" className="text-lg font-semibold">
            Earlier proposals
          </h2>
          <ul className="divide-y rounded-lg border text-sm">
            {data.history.slice(1).map((h) => (
              <li key={h.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
                <span className="tabular-nums">{h.run_date}</span>
                <span className="text-muted-foreground">
                  {Object.entries(h.proposed_split)
                    .map(([n, s]) => `${n} ${formatPercent(s, 0)}`)
                    .join(", ")}
                </span>
                <span className="text-xs uppercase tracking-wide text-muted-foreground">{h.status}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
