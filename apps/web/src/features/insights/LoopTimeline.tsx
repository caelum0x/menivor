"use client";

import * as React from "react";
import {
  AlertTriangle,
  BarChart3,
  CalendarClock,
  CircleDot,
  ExternalLink,
  RefreshCw,
  Send,
  Settings2,
  ShieldAlert,
  Trophy,
  Wallet,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatWhen, platformLabel } from "./format";
import type { LineageEntry, TimelineItem } from "./types";

type IconType = React.ComponentType<{ className?: string }>;

const KIND_META: Record<string, { icon: IconType; label: string }> = {
  configured: { icon: Settings2, label: "Loop updated" },
  scheduled: { icon: CalendarClock, label: "Post scheduled" },
  published: { icon: Send, label: "Posted" },
  failed: { icon: AlertTriangle, label: "Post failed" },
  held: { icon: ShieldAlert, label: "Held for review" },
  measured: { icon: BarChart3, label: "Early read" },
  extended: { icon: BarChart3, label: "Not decisive yet" },
  inconclusive: { icon: AlertTriangle, label: "No usable data" },
  winner: { icon: Trophy, label: "Winner picked" },
  remake_started: { icon: RefreshCw, label: "Remake started" },
  remake_failed: { icon: AlertTriangle, label: "Remake problem" },
  cap_reached: { icon: Wallet, label: "Spend cap reached" },
};

export interface LoopTimelineProps {
  items: readonly TimelineItem[];
  lineage: readonly LineageEntry[];
  onSelectBatch?: (batchId: string) => void;
}

/** Chronological loop history (newest first) across every round of remakes. */
export function LoopTimeline({ items, lineage, onSelectBatch }: Readonly<LoopTimelineProps>) {
  const roundOf = React.useMemo(() => {
    const map = new Map<string, number>();
    lineage.forEach((entry) => map.set(entry.batch_id, entry.generation));
    return map;
  }, [lineage]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Loop timeline</CardTitle>
        {lineage.length > 1 && (
          <div className="flex flex-wrap gap-2 pt-1">
            {lineage.map((entry) => (
              <button
                key={entry.batch_id}
                type="button"
                onClick={() => onSelectBatch?.(entry.batch_id)}
                disabled={entry.current}
                className="rounded-full border border-border px-2.5 py-0.5 text-xs text-muted-foreground transition-colors hover:bg-secondary/40 disabled:border-primary disabled:text-foreground"
              >
                Round {entry.generation}
              </button>
            ))}
          </div>
        )}
      </CardHeader>
      <CardContent>
        {items.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nothing has happened in this loop yet.</p>
        ) : (
          <ol className="relative space-y-4 border-l border-border pl-5">
            {items.map((item, index) => {
              const meta = KIND_META[item.kind] ?? { icon: CircleDot, label: item.kind };
              const Icon = meta.icon;
              const round = roundOf.get(item.batch_id);
              return (
                <li key={`${item.at}-${item.kind}-${index}`} className="relative">
                  <span className="absolute -left-[29px] top-0.5 flex size-4 items-center justify-center rounded-full bg-background">
                    <Icon className="size-4 text-primary" aria-hidden />
                  </span>
                  <p className="text-sm font-medium">
                    {meta.label}
                    {item.platform ? ` · ${platformLabel(item.platform)}` : ""}
                    {round && lineage.length > 1 ? ` · round ${round}` : ""}
                  </p>
                  <p className="text-xs text-muted-foreground">{formatWhen(item.at)}</p>
                  {item.message && (
                    <p className="mt-0.5 break-words text-sm text-muted-foreground">{item.message}</p>
                  )}
                  {item.url && (
                    <a
                      href={item.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="mt-0.5 inline-flex items-center gap-1 text-xs text-primary"
                    >
                      View post <ExternalLink className="size-3" aria-hidden />
                    </a>
                  )}
                </li>
              );
            })}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}
