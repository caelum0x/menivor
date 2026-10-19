"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowRight, GitCompare, Loader2, RefreshCw, Type } from "lucide-react";

import { ApiError } from "@/src/shared/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useApiToken } from "@/lib/use-api-token";
import { getCaptionSafezones, type SafezoneEntry, type SafezonesResult } from "./api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

function errText(err: unknown, fallback: string): string {
  if (err instanceof ApiError || err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

function SafezoneCard({
  surface,
  zone,
}: {
  surface: string;
  zone: SafezoneEntry;
}): React.JSX.Element {
  const label = surface
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
  return (
    <Card>
      <CardContent className="space-y-2 py-4">
        <div className="flex items-center gap-2">
          <Type className="h-4 w-4 text-primary" aria-hidden />
          <span className="font-medium">{label}</span>
        </div>
        <div className="grid grid-cols-3 gap-2 text-sm">
          <div className="space-y-0.5">
            <p className="text-xs text-muted-foreground">Font size</p>
            <p className="font-mono font-semibold">{zone.fontsize}px</p>
          </div>
          <div className="space-y-0.5">
            <p className="text-xs text-muted-foreground">Margin</p>
            <p className="font-mono font-semibold">{zone.margin_v}px</p>
          </div>
          <div className="space-y-0.5">
            <p className="text-xs text-muted-foreground">Y position</p>
            <p className="font-mono font-semibold">
              {(zone.y_frac * 100).toFixed(0)}%
            </p>
          </div>
        </div>
        {/* Visual position indicator */}
        <div className="relative h-16 overflow-hidden rounded-md bg-neutral-900">
          <div
            className="absolute left-1/2 -translate-x-1/2 rounded bg-white/90 px-2 py-0.5 text-center text-neutral-900"
            style={{
              top: `${zone.y_frac * 100}%`,
              transform: `translateX(-50%) translateY(-50%)`,
              fontSize: Math.max(8, Math.min(14, zone.fontsize / 8)),
              fontWeight: 700,
            }}
          >
            Caption line
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

interface CaptionToolLinkProps {
  href: string;
  title: string;
  description: string;
}

const CAPTION_TOOLS: CaptionToolLinkProps[] = [
  {
    href: "/captions",
    title: "Caption styles",
    description:
      "Browse the full preset registry — Hormozi, karaoke, brainrot. Preview the ASS style before rendering.",
  },
  {
    href: "/hook-lab",
    title: "Hook score lab",
    description:
      "Tune the first-3s signals and check whether a reel clears the 70% hook gate, live.",
  },
  {
    href: "/ab-lab",
    title: "A/B winner lab",
    description:
      "Compare caption-variant reels by retention score and see which cut the pipeline promotes.",
  },
];

/**
 * Captions browser — loads the real per-platform caption safe-zones from
 * GET /captions/safezones and shows each platform surface's font size, vertical
 * margin, and Y-position. Links out to the hook-lab and A/B lab for deeper
 * caption tuning. No fabricated data — all from the real captions domain.
 */
export function CaptionsBrowser(): React.JSX.Element {
  const getApiToken = useApiToken();
  const [result, setResult] = React.useState<SafezonesResult | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [refreshing, setRefreshing] = React.useState(false);

  const load = React.useCallback(
    async (signal?: AbortSignal) => {
      setError("");
      const token = await getApiToken();
      try {
        const data = await getCaptionSafezones(1920, { token, signal });
        if (!signal?.aborted) setResult(data);
      } catch (err) {
        if (!signal?.aborted) {
          setError(errText(err, "Failed to load caption safe-zones."));
        }
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [getApiToken],
  );

  React.useEffect(() => {
    const ctrl = new AbortController();
    void load(ctrl.signal);
    return () => ctrl.abort();
  }, [load]);

  const onRefresh = React.useCallback(async () => {
    setRefreshing(true);
    setLoading(true);
    try {
      await load();
    } finally {
      setRefreshing(false);
    }
  }, [load]);

  const surfaces = result
    ? Object.entries(result.safezones)
    : ([] as [string, SafezoneEntry][]);

  return (
    <div className="space-y-8">
      {/* Safe-zones grid */}
      <section className="space-y-4">
        <div className="flex items-center justify-between gap-3">
          <div className="space-y-0.5">
            <h2 className="font-semibold">
              Per-platform safe-zones
              {result && (
                <span className="ml-1 font-normal text-muted-foreground">
                  ({result.play_h}px reference height)
                </span>
              )}
            </h2>
            <p className="text-sm text-muted-foreground">
              Caption placement the renderer burns in for each platform surface
              — font size, vertical margin, and Y-fraction.
            </p>
          </div>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => void onRefresh()}
            disabled={refreshing || loading}
          >
            <RefreshCw
              className={`mr-1 h-4 w-4 ${refreshing ? "animate-spin" : ""}`}
              aria-hidden
            />
            Refresh
          </Button>
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        {loading ? (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading
            safe-zones…
          </p>
        ) : surfaces.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No safe-zone data returned.
          </p>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {surfaces.map(([surface, zone]) => (
              <SafezoneCard key={surface} surface={surface} zone={zone} />
            ))}
          </div>
        )}
      </section>

      {/* Caption tool links */}
      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <GitCompare className="h-4 w-4 text-muted-foreground" aria-hidden />
          <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
            Caption tools
          </h2>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          {CAPTION_TOOLS.map((tool) => (
            <Link
              key={tool.href}
              href={tool.href}
              className="group block rounded-lg border bg-card p-4 transition-colors hover:border-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium">{tool.title}</span>
                <ArrowRight
                  className="h-4 w-4 text-muted-foreground group-hover:text-primary"
                  aria-hidden
                />
              </div>
              <p className="mt-1 text-sm text-muted-foreground">
                {tool.description}
              </p>
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}
