import * as React from "react";
import {
  Clapperboard,
  Copy,
  DollarSign,
  Globe,
  Layers,
  LayoutGrid,
  Sparkles,
} from "lucide-react";
import type { Analytics } from "@/lib/types";
import { StatCard } from "@/components/insights/StatCard";
import { formatCount, formatStateLabel, formatUsd } from "./format";
import { FunnelChart } from "./FunnelChart";
import { CostOverTime } from "./CostOverTime";
import { CreditsPanel } from "./CreditsPanel";
import { RenderTimeTiles } from "./RenderTimeTiles";
import { CountBreakdown, toBreakdownRows } from "./CountBreakdown";

export interface AnalyticsDashboardProps {
  analytics: Readonly<Analytics>;
}

/** Human label for a language code (uppercased short code, else prettified). */
function languageLabel(key: string): string {
  if (!key || key === "unknown") return "Unknown";
  return key.length <= 3 ? key.toUpperCase() : formatStateLabel(key);
}

/** Human label for a variant-count bucket (e.g. "2" -> "2 variants"). */
function variantLabel(key: string): string {
  if (!key || key === "unknown") return "Unknown";
  const n = Number(key);
  if (!Number.isFinite(n)) return formatStateLabel(key);
  return `${n} variant${n === 1 ? "" : "s"}`;
}

/**
 * The full creator BI dashboard body: headline totals, a funnel + cost-over-time
 * pair, credits + render-time, and the usage breakdowns (layout / language /
 * variants / top templates / top hooks). Presentational only — the page owns
 * loading + error + the days selector.
 */
export function AnalyticsDashboard({
  analytics,
}: Readonly<AnalyticsDashboardProps>) {
  const { totals, top_content } = analytics;

  const templateRows = top_content.templates.map((t) => ({
    label: t.name,
    count: t.count,
  }));
  const hookRows = top_content.hooks.map((h) => ({
    label: h.hook,
    count: h.count,
  }));

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <StatCard
          label="Jobs created"
          value={formatCount(totals.jobs_total)}
          hint="In the selected window"
          icon={Layers}
          accent="primary"
        />
        <StatCard
          label="Videos generated"
          value={formatCount(totals.videos_generated)}
          hint="Successfully rendered"
          icon={Clapperboard}
          accent="success"
        />
        <StatCard
          label="Total cost"
          value={formatUsd(totals.total_cost_usd)}
          hint="Render spend in window"
          icon={DollarSign}
          accent="accent"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <FunnelChart funnel={analytics.funnel} />
        <CostOverTime points={analytics.cost_by_day} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <CreditsPanel credits={analytics.credits} days={analytics.days} />
        <div className="space-y-4">
          <RenderTimeTiles renderTime={analytics.render_time} />
          <CountBreakdown
            title="By variants"
            rows={toBreakdownRows(analytics.by_variants, variantLabel)}
            icon={Copy}
            barClassName="bg-accent"
            emptyLabel="No jobs in this window."
          />
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <CountBreakdown
          title="By layout"
          rows={toBreakdownRows(analytics.by_layout, formatStateLabel)}
          icon={LayoutGrid}
          barClassName="bg-primary"
          emptyLabel="No jobs in this window."
        />
        <CountBreakdown
          title="By language"
          rows={toBreakdownRows(analytics.by_language, languageLabel)}
          icon={Globe}
          barClassName="bg-success"
          emptyLabel="No jobs in this window."
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <CountBreakdown
          title="Top templates"
          rows={templateRows}
          icon={LayoutGrid}
          barClassName="bg-primary"
          emptyLabel="No template hints recorded yet."
          maxRows={8}
        />
        <CountBreakdown
          title="Top hooks"
          rows={hookRows}
          icon={Sparkles}
          barClassName="bg-accent"
          emptyLabel="No hooks recorded yet."
          maxRows={8}
        />
      </div>
    </div>
  );
}
