"use client";

import * as React from "react";
import Link from "next/link";
import { Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { LoadError, useRequestOptions } from "@/src/features/ad-studio/shared";
import { listCampaigns, type CampaignList as CampaignListData } from "./api";
import { CampaignList } from "./CampaignList";
import { ConnectionCard } from "./ConnectionCard";
import { GateNotice } from "./GateNotice";

/** Paid ads home: platform gate, ad-account connections and campaigns. */
export function AdsHome() {
  const requestOptions = useRequestOptions();
  const [data, setData] = React.useState<CampaignListData | null>(null);
  const [error, setError] = React.useState<unknown>(null);
  const [attempt, setAttempt] = React.useState(0);
  const [showArchived, setShowArchived] = React.useState(false);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const next = await listCampaigns(await requestOptions());
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
  }, [requestOptions, attempt]);

  if (!data && !error) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-20" />
        <Skeleton className="h-40" />
      </div>
    );
  }
  if (!data) {
    return (
      <LoadError
        error={error}
        onRetry={() => {
          setError(null);
          setAttempt((n) => n + 1);
        }}
        fallback="We couldn't load your ads. Please try again."
      />
    );
  }

  const visible = data.campaigns.filter((c) => showArchived || c.status !== "archived");
  const archivedCount = data.campaigns.length - data.campaigns.filter((c) => c.status !== "archived").length;

  return (
    <div className="space-y-8">
      <GateNotice gate={data.gate} />
      <section aria-labelledby="ads-accounts" className="space-y-3">
        <h2 id="ads-accounts" className="text-lg font-semibold">
          Ad accounts
        </h2>
        <div className="grid gap-3 md:grid-cols-2">
          {data.gate.platforms.map((gate) => (
            <ConnectionCard key={gate.platform} gate={gate} />
          ))}
        </div>
        <p className="text-xs text-muted-foreground">
          Ad spend is billed by Meta or TikTok to your own ad account. Menivor adds no fee on spend.
        </p>
      </section>
      <section aria-labelledby="ads-campaigns" className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="ads-campaigns" className="text-lg font-semibold">
            Campaigns
          </h2>
          <div className="flex gap-2">
            {archivedCount > 0 ? (
              <Button variant="ghost" size="sm" onClick={() => setShowArchived((v) => !v)}>
                {showArchived ? "Hide archived" : `Show archived (${archivedCount})`}
              </Button>
            ) : null}
            {data.gate.enabled ? (
              <Button asChild size="sm">
                <Link href="/ads/new">
                  <Plus className="mr-1 h-4 w-4" aria-hidden /> New campaign
                </Link>
              </Button>
            ) : null}
          </div>
        </div>
        <CampaignList campaigns={visible} />
      </section>
    </div>
  );
}
