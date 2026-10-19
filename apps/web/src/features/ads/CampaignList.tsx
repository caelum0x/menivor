import Link from "next/link";

import { Badge, type BadgeVariant } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import type { CampaignStatus, CampaignSummary } from "./api";
import { formatMinor, formatMoney, formatPercent } from "./format";

export const STATUS_BADGE: Record<CampaignStatus, { label: string; variant: BadgeVariant }> = {
  active: { label: "Running", variant: "success" },
  paused: { label: "Paused", variant: "secondary" },
  error: { label: "Needs attention", variant: "destructive" },
  archived: { label: "Archived", variant: "outline" },
};

/** Campaign cards with spend, CTR and cost per lead. */
export function CampaignList({ campaigns }: { campaigns: CampaignSummary[] }) {
  if (campaigns.length === 0) {
    return <p className="text-sm text-muted-foreground">No paid campaigns yet.</p>;
  }
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {campaigns.map((c) => {
        const badge = STATUS_BADGE[c.status] ?? STATUS_BADGE.paused;
        return (
          <Link key={c.key} href={`/ads/${c.key}`} className="block rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            <Card className="h-full transition-colors hover:bg-secondary/40">
              <CardContent className="space-y-2 p-4">
                <div className="flex items-start justify-between gap-2">
                  <p className="line-clamp-2 font-medium">{c.name}</p>
                  <Badge variant={badge.variant}>{badge.label}</Badge>
                </div>
                <p className="text-xs text-muted-foreground">
                  {c.platform === "meta" ? "Meta" : "TikTok"} · {c.creative_count ?? 0} ads ·{" "}
                  {formatMinor(c.daily_budget_minor, c.currency)}/day
                </p>
                <dl className="grid grid-cols-3 gap-2 text-sm">
                  <div>
                    <dt className="text-xs text-muted-foreground">Spend</dt>
                    <dd>{formatMoney(c.metrics.spend, c.currency)}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">CTR</dt>
                    <dd>{formatPercent(c.metrics.ctr)}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">Cost per lead</dt>
                    <dd>{formatMoney(c.metrics.cpl, c.currency)}</dd>
                  </div>
                </dl>
              </CardContent>
            </Card>
          </Link>
        );
      })}
    </div>
  );
}
