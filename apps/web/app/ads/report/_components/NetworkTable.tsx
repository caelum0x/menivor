import { AlertTriangle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { DASH, formatCount, formatMinor, formatPercent } from "@/src/features/ads/format";
import type { NetworkReport } from "./api";

/** Cost per result per network, cheapest first, with sample-size warnings. */
export function NetworkTable({ report }: { report: NetworkReport }) {
  const { currency, metric } = report;
  const resultLabel = metric === "leads" ? "Leads" : "Clicks";
  const rows = [...report.networks].sort((a, b) => {
    if (a.cost_per_result_minor === null) return 1;
    if (b.cost_per_result_minor === null) return -1;
    return a.cost_per_result_minor - b.cost_per_result_minor;
  });
  const worst = Math.max(0, ...rows.map((r) => r.cost_per_result_minor ?? 0));
  const totalSpend = rows.reduce((sum, r) => sum + r.spend_minor, 0);

  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full min-w-[720px] text-sm">
        <caption className="sr-only">Cost per {metric === "leads" ? "lead" : "click"} by ad network</caption>
        <thead className="bg-secondary/40 text-left text-xs uppercase tracking-wide text-muted-foreground">
          <tr>
            <th scope="col" className="px-3 py-2">Network</th>
            <th scope="col" className="px-3 py-2 text-right">Spend</th>
            <th scope="col" className="px-3 py-2 text-right">{resultLabel}</th>
            <th scope="col" className="px-3 py-2">Cost per {metric === "leads" ? "lead" : "click"}</th>
            <th scope="col" className="px-3 py-2 text-right">CTR</th>
            <th scope="col" className="px-3 py-2 text-right">Daily budget now</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const width = row.cost_per_result_minor !== null && worst > 0 ? (row.cost_per_result_minor / worst) * 100 : 0;
            const cheapest = report.cheapest === row.network;
            return (
              <tr key={row.network} className="border-t align-top">
                <th scope="row" className="px-3 py-3 text-left font-medium">
                  <div className="flex flex-wrap items-center gap-2">
                    {row.label}
                    {row.source === "manual" ? <Badge variant="outline">Entered by you</Badge> : null}
                    {cheapest ? <Badge variant="success">Lowest cost</Badge> : null}
                  </div>
                  {row.source === "measured" ? (
                    <p className="mt-1 text-xs font-normal text-muted-foreground">
                      {row.campaigns} campaign{row.campaigns === 1 ? "" : "s"}
                      {totalSpend > 0 ? `, ${formatPercent(row.spend_minor / totalSpend, 0)} of spend` : ""}
                    </p>
                  ) : null}
                  {row.warning ? (
                    <p className="mt-1 flex items-start gap-1 text-xs font-normal text-amber-600 dark:text-amber-400">
                      <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
                      {row.warning}
                    </p>
                  ) : null}
                </th>
                <td className="px-3 py-3 text-right tabular-nums">{formatMinor(row.spend_minor, currency)}</td>
                <td className="px-3 py-3 text-right tabular-nums">{formatCount(row.results)}</td>
                <td className="px-3 py-3">
                  <div className="flex items-center gap-2">
                    <span className="w-20 shrink-0 tabular-nums">
                      {row.cost_per_result_minor === null ? DASH : formatMinor(Math.round(row.cost_per_result_minor), currency)}
                    </span>
                    <div className="h-2 flex-1 rounded-full bg-secondary" aria-hidden>
                      <div
                        className={cheapest ? "h-2 rounded-full bg-success" : "h-2 rounded-full bg-primary/60"}
                        style={{ width: `${width}%` }}
                      />
                    </div>
                  </div>
                </td>
                <td className="px-3 py-3 text-right tabular-nums">{formatPercent(row.ctr)}</td>
                <td className="px-3 py-3 text-right tabular-nums">{formatMinor(row.current_daily_minor, currency)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
