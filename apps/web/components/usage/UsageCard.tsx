import * as React from "react";
import { Gauge, Infinity as InfinityIcon, KeyRound } from "lucide-react";
import type { ApiKeyUsage } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";
import {
  formatCount,
  formatPeriod,
  formatRateLimit,
  hasMonthlyQuota,
  quotaBadgeVariant,
  remainingRequests,
  usagePercent,
} from "./format";

export interface UsageCardProps {
  usage: Readonly<ApiKeyUsage>;
}

/**
 * A single API key's current-month usage: its label + non-secret prefix, its
 * per-minute rate limit, and a progress bar of requests consumed against the
 * monthly quota (or an "Unlimited" state when the key has no quota).
 * Presentational only — all values are derived read-only from `usage`.
 */
export function UsageCard({ usage }: Readonly<UsageCardProps>) {
  const limited = hasMonthlyQuota(usage.monthly_quota);
  const percent = usagePercent(usage);
  const remaining = remainingRequests(usage);
  const used = Math.max(0, Number.isFinite(usage.used) ? usage.used : 0);

  return (
    <Card>
      <CardContent className="space-y-4 p-5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="flex items-center gap-2 font-semibold">
              <KeyRound
                className="size-4 shrink-0 text-muted-foreground"
                aria-hidden
              />
              <span className="truncate">{usage.name || "Untitled key"}</span>
            </p>
            <p className="mt-1 truncate font-mono text-xs text-muted-foreground">
              {usage.prefix}…
            </p>
          </div>
          <Badge variant="outline" className="shrink-0">
            <Gauge className="size-3" aria-hidden />
            {formatRateLimit(usage.rate_limit_per_min)}
          </Badge>
        </div>

        {limited ? (
          <div className="space-y-2">
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">
                {formatCount(used)} / {formatCount(usage.monthly_quota)} requests
              </span>
              <Badge variant={quotaBadgeVariant(percent)}>
                {Math.round(percent)}%
              </Badge>
            </div>
            <Progress
              value={percent}
              aria-label={`Monthly quota used for ${usage.name || "this key"}`}
            />
            <p className="text-xs text-muted-foreground">
              {formatCount(remaining ?? 0)} remaining · {formatPeriod(usage.period_ym)}
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">
                {formatCount(used)} requests
              </span>
              <Badge variant="secondary">
                <InfinityIcon className="size-3" aria-hidden />
                Unlimited
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground">
              No monthly quota · {formatPeriod(usage.period_ym)}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export interface UsageListProps {
  usage: readonly ApiKeyUsage[];
  className?: string;
}

/** Responsive grid of {@link UsageCard}s, one per API key. */
export function UsageList({ usage, className }: Readonly<UsageListProps>) {
  return (
    <div className={cn("grid gap-4 sm:grid-cols-2", className)}>
      {usage.map((key) => (
        <UsageCard key={key.id} usage={key} />
      ))}
    </div>
  );
}
