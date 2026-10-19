"use client";

/**
 * The paywall moment (MR2). When the last free reel finishes, one screen
 * shows that reel, then "Keep making reels" with the one-time pack as the
 * default and the monthly plan second. Prices come from plan config (see
 * offer.ts); checkout is one click on the existing hosted checkout path.
 */

import * as React from "react";
import { Loader2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { jobResultUrl, jobThumbnailUrl } from "@/lib/job-media";
import type { Job } from "@/lib/types";
import { MONTHLY_COPY_SOURCE, PACK_COPY_SOURCE } from "./offer";
import { usePaywallMoment } from "./use-paywall-moment";

export interface PaywallMomentProps {
  readonly jobIds: readonly string[];
  /** The finished reel to show first. */
  readonly job?: Job;
  /** True once the run is terminal with at least one finished reel. */
  readonly ready: boolean;
}

export function PaywallMoment({ jobIds, job, ready }: PaywallMomentProps) {
  const { open, offers, busy, error, buyPack, buyMonthly, dismiss } = usePaywallMoment(jobIds, ready);
  if (!open || !offers.pack) return null;
  const video = job ? jobResultUrl(job) : undefined;
  const poster = job ? jobThumbnailUrl(job) : undefined;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="paywall-moment-title"
      data-testid="paywall-moment"
      className="fixed inset-0 z-50 flex items-center justify-center bg-background/90 p-4 backdrop-blur"
    >
      <div className="relative w-full max-w-md space-y-5 rounded-2xl border border-border bg-card p-6 shadow-xl">
        <button
          type="button"
          onClick={dismiss}
          aria-label="Close"
          className="absolute right-3 top-3 rounded-md p-1 text-muted-foreground hover:text-foreground"
        >
          <X className="size-4" aria-hidden />
        </button>

        {video ? (
          <video
            src={video}
            poster={poster}
            controls
            playsInline
            className="mx-auto aspect-[9/16] max-h-[45dvh] rounded-lg bg-black"
          />
        ) : null}

        <div className="space-y-1 text-center">
          <h2 id="paywall-moment-title" className="text-xl font-semibold">
            Keep making reels
          </h2>
          <p className="text-sm text-muted-foreground">Your free reels are used. This one is yours to keep.</p>
        </div>

        <div className="space-y-2">
          <Button
            type="button"
            className="w-full"
            disabled={busy !== null}
            onClick={() => void buyPack()}
            data-copy-source={PACK_COPY_SOURCE}
          >
            {busy === "pack" ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
            {`${offers.pack.reels} reels for ${offers.pack.price}, one time`}
          </Button>
          {offers.monthly ? (
            <Button
              type="button"
              variant="outline"
              className="w-full"
              disabled={busy !== null}
              onClick={() => void buyMonthly()}
              data-copy-source={MONTHLY_COPY_SOURCE}
            >
              {busy === "monthly" ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
              {`${offers.monthly.name}: ${offers.monthly.reels} reels a month for ${offers.monthly.price}`}
            </Button>
          ) : null}
          <p className="text-center text-xs text-muted-foreground">
            Pack credits never expire. The monthly plan renews until you cancel.
          </p>
        </div>

        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </div>
    </div>
  );
}
