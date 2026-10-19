import { Film } from "lucide-react";

import { Badge, type BadgeVariant } from "@/components/ui/badge";
import { safeServerText } from "@/src/shared/errors";
import type { Allocation, Creative, CreativePhase } from "./api";
import { formatCount, formatMinor, formatMoney, formatPercent } from "./format";

const PHASE: Record<CreativePhase, { label: string; variant: BadgeVariant }> = {
  uploading: { label: "Uploading", variant: "secondary" },
  processing: { label: "Processing video", variant: "secondary" },
  live: { label: "Live", variant: "success" },
  failed: { label: "Failed", variant: "destructive" },
};

/** Per-creative spend, CTR, CPL, current budget and chance of being best. */
export function CreativeTable({
  creatives,
  currency,
  preview,
}: {
  creatives: Creative[];
  currency: string;
  preview: Allocation | null;
}) {
  const next = new Map((preview?.arms ?? []).map((a) => [a.arm_id, a]));
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full min-w-[760px] text-sm">
        <thead className="bg-secondary/40 text-left text-xs text-muted-foreground">
          <tr>
            <th className="p-2 font-medium">Ad</th>
            <th className="p-2 font-medium">State</th>
            <th className="p-2 text-right font-medium">Budget / day</th>
            <th className="p-2 text-right font-medium">Chance best</th>
            <th className="p-2 text-right font-medium">Spend</th>
            <th className="p-2 text-right font-medium">Impr.</th>
            <th className="p-2 text-right font-medium">CTR</th>
            <th className="p-2 text-right font-medium">CPL</th>
          </tr>
        </thead>
        <tbody>
          {creatives.map((c) => {
            const phase = PHASE[c.phase] ?? PHASE.processing;
            const planned = next.get(c.variant_id);
            return (
              <tr key={c.variant_id} className="border-t border-border align-top">
                <td className="p-2">
                  <div className="flex gap-2">
                    {c.poster_url ? (
                      // eslint-disable-next-line @next/next/no-img-element -- presigned media URL
                      <img src={c.poster_url} alt="" className="h-14 w-8 shrink-0 rounded object-cover" />
                    ) : (
                      <div className="flex h-14 w-8 shrink-0 items-center justify-center rounded bg-secondary/40">
                        <Film className="h-4 w-4 text-muted-foreground" aria-hidden />
                      </div>
                    )}
                    <div className="min-w-0">
                      <p className="line-clamp-2 max-w-[16rem]">{c.hook || c.variant_id}</p>
                      <p className="text-xs text-muted-foreground">{c.allocation_reason}</p>
                      {c.error ? <p className="text-xs text-destructive">{safeServerText(c.error, "This video could not be uploaded.")}</p> : null}
                    </div>
                  </div>
                </td>
                <td className="p-2">
                  <Badge variant={phase.variant}>{phase.label}</Badge>
                  {!c.active && c.phase === "live" ? <p className="mt-1 text-xs text-muted-foreground">Paused by winner loop</p> : null}
                </td>
                <td className="p-2 text-right">
                  {formatMinor(c.budget_minor, currency)}
                  {planned && planned.budget_minor !== c.budget_minor ? (
                    <p className="text-xs text-primary">next {formatMinor(planned.budget_minor, currency)}</p>
                  ) : null}
                </td>
                <td className="p-2 text-right">{formatPercent(planned?.p_best ?? c.p_best, 0)}</td>
                <td className="p-2 text-right">{formatMoney(c.metrics.spend, currency)}</td>
                <td className="p-2 text-right">{formatCount(c.metrics.impressions)}</td>
                <td className="p-2 text-right">{formatPercent(c.metrics.ctr)}</td>
                <td className="p-2 text-right">{formatMoney(c.metrics.cpl, currency)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
