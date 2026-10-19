"use client";

import * as React from "react";
import Link from "next/link";
import {
  Clapperboard,
  Download,
  Film,
  Loader2,
  RefreshCw,
  Sparkles,
} from "lucide-react";

import { Badge, type BadgeVariant } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { stashBrollAttachment } from "@/src/shared/media";
import type { BrollClip, BrollPreset } from "./api";
import {
  clipPhase,
  useBrollLibrary,
  type BrollClipPhase,
  type BrollLibraryFilter,
} from "./use-broll-library";

const FILTERS: readonly { value: BrollLibraryFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "ready", label: "Ready" },
  { value: "processing", label: "Processing" },
  { value: "failed", label: "Failed" },
];

const PHASE_BADGE: Record<BrollClipPhase, { variant: BadgeVariant; label: string }> = {
  ready: { variant: "success", label: "Ready" },
  processing: { variant: "secondary", label: "Processing" },
  failed: { variant: "destructive", label: "Failed" },
};

/** A single clip card: preview, live state/progress, and reuse actions. */
function ClipCard({ clip }: { clip: BrollClip }): React.JSX.Element {
  const phase = clipPhase(clip.state);
  const badge = PHASE_BADGE[phase];

  // Hand the clip to the reel wizard as its AI B-roll intro cutaway.
  const onUseInReel = React.useCallback(() => {
    if (!clip.broll_key) return;
    stashBrollAttachment({
      key: clip.broll_key,
      resultUrl: clip.result_url ?? "",
    });
  }, [clip.broll_key, clip.result_url]);

  return (
    <Card>
      <CardContent className="space-y-3 py-4">
        <div className="flex items-start justify-between gap-2">
          <span className="truncate font-mono text-xs text-muted-foreground">
            {clip.generation_id}
          </span>
          <Badge variant={badge.variant}>{badge.label}</Badge>
        </div>

        {phase === "ready" && clip.result_url ? (
          <video
            src={clip.result_url}
            className="aspect-[9/16] w-full rounded-md bg-muted object-cover"
            controls
            muted
            playsInline
            preload="metadata"
            aria-label={`B-roll clip ${clip.generation_id}`}
          />
        ) : (
          <div className="flex aspect-[9/16] w-full items-center justify-center rounded-md bg-muted">
            {phase === "processing" ? (
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" aria-hidden />
            ) : (
              <Clapperboard className="h-6 w-6 text-muted-foreground" aria-hidden />
            )}
          </div>
        )}

        {phase === "processing" && (
          <Progress value={clip.progress} aria-label="Generation progress" />
        )}
        {phase === "failed" && clip.error && (
          <p className="text-sm text-destructive">{clip.error}</p>
        )}
        {clip.duration > 0 && (
          <p className="text-xs text-muted-foreground">
            {clip.duration.toFixed(1)}s clip
          </p>
        )}

        {phase === "ready" && (
          <div className="flex flex-wrap gap-2">
            {clip.broll_key && (
              <Button asChild size="sm">
                <Link href="/new" onClick={onUseInReel}>
                  <Film className="mr-1 h-4 w-4" aria-hidden /> Use in a reel
                </Link>
              </Button>
            )}
            {clip.result_url && (
              <Button asChild size="sm" variant="ghost">
                <a href={clip.result_url} download target="_blank" rel="noreferrer">
                  <Download className="mr-1 h-4 w-4" aria-hidden /> Download
                </a>
              </Button>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/** Preset strip card: seeds a new generation over in the studio. */
function PresetCard({ preset }: { preset: BrollPreset }): React.JSX.Element {
  return (
    <Card>
      <CardContent className="space-y-2 py-4">
        <div className="flex items-center justify-between gap-2">
          <span className="font-medium">{preset.name}</span>
          <Badge variant="outline">{preset.mode}</Badge>
        </div>
        {preset.description && (
          <p className="line-clamp-2 text-sm text-muted-foreground">
            {preset.description}
          </p>
        )}
        <Button asChild size="sm" variant="outline">
          <Link href="/broll">
            <Sparkles className="mr-1 h-4 w-4" aria-hidden /> Use in studio
          </Link>
        </Button>
      </CardContent>
    </Card>
  );
}

/**
 * B-roll Library: browse, filter, and reuse the caller's AI B-roll clips — all
 * wired to the existing `/generation/broll/*` routes. Still-processing clips are
 * polled to completion; a ready clip can be handed to the reel wizard as its
 * intro cutaway, or downloaded directly. The preset strip links back to the studio to
 * start a new generation.
 */
export function BrollLibrary(): React.JSX.Element {
  const {
    clips,
    presets,
    loading,
    errorMessage,
    presetsError,
    filter,
    setFilter,
    counts,
    refresh,
  } = useBrollLibrary();
  const [refreshing, setRefreshing] = React.useState(false);

  const onRefresh = React.useCallback(async () => {
    setRefreshing(true);
    try {
      await refresh();
    } finally {
      setRefreshing(false);
    }
  }, [refresh]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2" role="tablist" aria-label="Filter clips">
          {FILTERS.map((f) => (
            <Button
              key={f.value}
              type="button"
              size="sm"
              role="tab"
              aria-selected={filter === f.value}
              variant={filter === f.value ? "default" : "outline"}
              onClick={() => setFilter(f.value)}
            >
              {f.label}
              <span className="ml-1 text-xs opacity-70">{counts[f.value]}</span>
            </Button>
          ))}
        </div>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={() => void onRefresh()}
          disabled={refreshing}
        >
          <RefreshCw
            className={`mr-1 h-4 w-4 ${refreshing ? "animate-spin" : ""}`}
            aria-hidden
          />
          Refresh
        </Button>
      </div>

      {errorMessage && <p className="text-sm text-destructive">{errorMessage}</p>}

      {loading ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading your
          library…
        </p>
      ) : clips.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-8 text-center">
          <Clapperboard
            className="mx-auto mb-2 h-8 w-8 text-muted-foreground"
            aria-hidden
          />
          <p className="text-sm text-muted-foreground">
            {counts.all === 0
              ? "No B-roll clips yet."
              : "No clips match this filter."}
          </p>
          <Button asChild size="sm" className="mt-4">
            <Link href="/broll">
              <Sparkles className="mr-1 h-4 w-4" aria-hidden /> Generate a clip
            </Link>
          </Button>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {clips.map((clip) => (
            <ClipCard key={clip.generation_id} clip={clip} />
          ))}
        </div>
      )}

      {presets.length > 0 && (
        <section className="space-y-3">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Sparkles className="h-4 w-4" aria-hidden /> Motion presets
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {presets.map((preset) => (
              <PresetCard key={preset.id} preset={preset} />
            ))}
          </div>
        </section>
      )}
      {presetsError && presets.length === 0 && (
        <p className="text-xs text-muted-foreground">{presetsError}</p>
      )}
    </div>
  );
}
