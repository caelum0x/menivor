"use client";

import * as React from "react";
import { Download, Loader2, Play, RotateCcw, Trash2, UserRound } from "lucide-react";

import { Badge, type BadgeVariant } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ShareToX } from "@/src/features/share-x/ShareToX";
import { safeServerText } from "@/src/shared/errors";
import type { AdVariant, VariantStatus } from "./api";

const STATUS: Record<VariantStatus, { label: string; variant: BadgeVariant }> = {
  queued: { label: "Queued", variant: "secondary" },
  rendering: { label: "Rendering", variant: "default" },
  ready: { label: "Background ready", variant: "outline" },
  submitted: { label: "Avatar reel rendering", variant: "default" },
  done: { label: "Ready", variant: "success" },
  failed: { label: "Failed", variant: "destructive" },
};

const ASPECT_CLASS: Record<string, string> = {
  "9:16": "aspect-[9/16]",
  "1:1": "aspect-square",
  "16:9": "aspect-video",
};

export interface VariantActions {
  onRetry: (ad: AdVariant) => Promise<void>;
  onDelete: (ad: AdVariant) => Promise<void>;
  onStartAvatar: (ad: AdVariant) => Promise<void>;
}

function VariantCard({
  ad,
  actions,
  sourceUrl,
}: {
  ad: AdVariant;
  actions: VariantActions;
  sourceUrl?: string | null;
}) {
  const [busy, setBusy] = React.useState(false);
  const run = (fn: (ad: AdVariant) => Promise<void>) => async () => {
    setBusy(true);
    try {
      await fn(ad);
    } finally {
      setBusy(false);
    }
  };
  const status = STATUS[ad.status];
  const media = ad.video_url ?? (ad.status === "ready" ? ad.montage_url : null);
  return (
    <Card>
      <CardContent className="space-y-3 p-3">
        <div className={`${ASPECT_CLASS[ad.aspect] ?? "aspect-video"} max-h-[420px] w-full overflow-hidden rounded-md border border-border bg-black/80`}>
          {media ? (
            <video src={media} poster={ad.poster_url ?? undefined} controls playsInline preload="metadata" className="h-full w-full object-contain" />
          ) : (
            <div className="flex h-full w-full items-center justify-center text-sm text-muted-foreground">
              {ad.status === "failed" ? "No video" : <Loader2 className="h-6 w-6 animate-spin" aria-label="Rendering" />}
            </div>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={status.variant}>{status.label}</Badge>
          {ad.test_batch_id ? <Badge variant="outline">In a test</Badge> : null}
          {ad.remake_of ? <Badge variant="outline">Remake of winner</Badge> : null}
          <span className="text-xs text-muted-foreground">
            {ad.format_label} · {ad.aspect} · {ad.angle_label}
            {ad.duration_s ? ` · ${ad.duration_s.toFixed(0)}s` : ""}
          </span>
        </div>
        {ad.hook ? <p className="text-sm">{ad.hook}</p> : null}
        {ad.error ? <p className="text-xs text-destructive">{safeServerText(ad.error, "This ad could not be rendered. Try again.")}</p> : null}
        {ad.status === "ready" ? (
          <p className="text-xs text-muted-foreground">
            The product montage is ready. Starting the avatar reel uses your normal reel credits.
          </p>
        ) : null}
        <div className="flex flex-wrap gap-2">
          {ad.status === "done" && ad.download_url ? (
            <Button asChild size="sm">
              <a href={ad.download_url} download={ad.filename}>
                <Download aria-hidden /> Download
              </a>
            </Button>
          ) : null}
          {ad.status === "done" && ad.download_url ? (
            <ShareToX
              hook={ad.hook}
              sourceUrl={sourceUrl}
              downloadUrl={ad.download_url}
              downloadFilename={ad.filename}
            />
          ) : null}
          {ad.status === "ready" ? (
            <Button size="sm" onClick={run(actions.onStartAvatar)} disabled={busy}>
              {busy ? <Loader2 className="animate-spin" aria-hidden /> : <UserRound aria-hidden />} Start avatar reel
            </Button>
          ) : null}
          {ad.status === "failed" ? (
            <Button size="sm" variant="outline" onClick={run(actions.onRetry)} disabled={busy}>
              <RotateCcw aria-hidden /> Retry
            </Button>
          ) : null}
          {ad.status !== "rendering" && ad.status !== "submitted" ? (
            <Button size="sm" variant="ghost" onClick={run(actions.onDelete)} disabled={busy} aria-label="Remove this ad">
              <Trash2 aria-hidden />
            </Button>
          ) : null}
        </div>
        <details className="text-xs text-muted-foreground">
          <summary className="cursor-pointer select-none">
            <Play className="mr-1 inline h-3 w-3" aria-hidden />
            Script
          </summary>
          <p className="mt-1 whitespace-pre-wrap">{ad.script}</p>
        </details>
      </CardContent>
    </Card>
  );
}

export function VariantGrid({
  variants,
  actions,
  sourceUrl,
}: {
  variants: AdVariant[];
  actions: VariantActions;
  sourceUrl?: string | null;
}) {
  if (variants.length === 0) {
    return <p className="text-sm text-muted-foreground">No ads rendered yet. Pick angles and formats above.</p>;
  }
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      {variants.map((ad) => (
        <VariantCard key={ad.id} ad={ad} actions={actions} sourceUrl={sourceUrl} />
      ))}
    </div>
  );
}
