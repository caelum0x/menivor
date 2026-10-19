"use client";

import * as React from "react";
import { ImageIcon, Music, ShieldCheck, Video } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import {
  formatUsdMicros,
  settlementProofView,
  type GenerationDetail,
  type Modality,
} from "./api";
import { safeServerText } from "@/src/shared/errors/friendly";

export type HistoryEntry = GenerationDetail;

const ICON: Record<Modality, React.ComponentType<{ className?: string }>> = {
  image: ImageIcon,
  video: Video,
  audio: Music,
};

/**
 * Durable account generation history. Rows come from the canonical backend
 * timeline, so in-progress and completed work survives browser/device restarts.
 */
export function GenerationHistory({
  items,
  onSelect,
}: {
  items: HistoryEntry[];
  onSelect: (entry: HistoryEntry) => void;
}) {
  if (items.length === 0) return null;
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium text-muted-foreground">
        History <span className="text-xs">({items.length})</span>
      </h3>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {items.map((entry) => {
          const Icon = ICON[entry.modality];
          const ready = entry.status === "completed" && Boolean(entry.output_url);
          const settlement = settlementProofView(entry);
          return (
            <Card key={entry.id} className="transition-colors hover:border-primary">
              <CardContent className="p-2">
                <button
                  type="button"
                  onClick={() => onSelect(entry)}
                  className="block w-full text-left"
                  aria-label={`${ready ? "Re-open" : "Inspect"} ${entry.modality} from ${entry.model}`}
                >
                  {entry.modality === "image" && entry.output_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={entry.output_url} alt="" className="mb-2 h-24 w-full rounded object-cover" />
                  ) : (
                    <div className="mb-2 flex h-24 w-full items-center justify-center rounded bg-muted">
                      <Icon className="h-6 w-6 text-muted-foreground" />
                    </div>
                  )}
                  <div className="flex items-center justify-between gap-1">
                    <span className="truncate text-xs" title={entry.model}>
                      {entry.model}
                    </span>
                    {settlement.outcome === "captured" ? (
                      <span className="shrink-0 text-xs text-muted-foreground">
                        {formatUsdMicros(entry.settlement_evidence?.receipt.amount_micros || 0)}
                      </span>
                    ) : null}
                  </div>
                  <div className="mt-1 truncate text-[11px] text-muted-foreground">
                    {entry.status === "failed" && entry.error
                      ? `${safeServerText(entry.error, "Generation failed")} · ${settlement.chargeLabel}`
                      : `${settlement.outcomeLabel} · ${settlement.chargeLabel}`}
                  </div>
                  {entry.identity ? (
                    <div className="mt-1 flex items-center gap-1 truncate text-[11px] text-emerald-700 dark:text-emerald-400">
                      <ShieldCheck className="h-3 w-3 shrink-0" />
                      v{entry.identity.version} · {entry.identity.status}
                    </div>
                  ) : null}
                </button>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
