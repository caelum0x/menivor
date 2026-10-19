import * as React from "react";
import { Eye, Flame, Heart, Percent } from "lucide-react";
import type { WinningHook } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { formatCount } from "@/components/insights/format";
import { formatRetention, formatScore } from "@/components/performance/format";

export interface WinningHooksPanelProps {
  /** Top hooks by win score, best first (already ranked server-side). */
  hooks: readonly WinningHook[];
}

/**
 * A ranked breakdown of the creator's best-performing hooks. No chart library —
 * each row is a labelled proportional bar sized against the top hook's win score,
 * plus the underlying reel/view/engagement/retention stats. Presentational only;
 * `hooks` is read-only (never mutated).
 */
export function WinningHooksPanel({
  hooks,
}: Readonly<WinningHooksPanelProps>) {
  const max = hooks.reduce((m, h) => Math.max(m, h.win_score), 0);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Flame className="size-4 text-primary" aria-hidden />
          Winning hooks
        </CardTitle>
      </CardHeader>
      <CardContent>
        {hooks.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No performance logged yet. Log a reel&apos;s metrics to see which
            hooks convert.
          </p>
        ) : (
          <ol className="space-y-4">
            {hooks.map((hook, index) => {
              const pctOfMax = max > 0 ? (hook.win_score / max) * 100 : 0;
              return (
                <li key={`${hook.hook}-${index}`}>
                  <div className="mb-1 flex items-start justify-between gap-3">
                    <div className="flex min-w-0 items-start gap-2">
                      <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold tabular-nums text-muted-foreground">
                        {index + 1}
                      </span>
                      <span className="min-w-0 break-words text-sm font-medium">
                        {hook.hook}
                      </span>
                    </div>
                    <Badge
                      variant="outline"
                      className="shrink-0 gap-1 tabular-nums"
                      title="Win score"
                    >
                      <Flame className="size-3 text-primary" aria-hidden />
                      {formatScore(hook.win_score)}
                    </Badge>
                  </div>

                  <div
                    className="h-2 w-full overflow-hidden rounded-full bg-muted"
                    role="img"
                    aria-label={`Win score ${formatScore(
                      hook.win_score,
                    )} across ${formatCount(hook.reels)} reels`}
                  >
                    <div
                      className={cn(
                        "h-full rounded-full bg-primary transition-all",
                      )}
                      style={{ width: `${Math.max(pctOfMax, 4)}%` }}
                    />
                  </div>

                  <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                    <Stat label="reels" value={formatCount(hook.reels)} />
                    <Stat
                      icon={Eye}
                      label="views"
                      value={formatCount(hook.views)}
                    />
                    <Stat
                      icon={Heart}
                      label="engagements"
                      value={formatCount(hook.engagements)}
                    />
                    <Stat
                      icon={Percent}
                      label="avg retention"
                      value={formatRetention(hook.avg_retention_pct)}
                    />
                  </dl>
                </li>
              );
            })}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}

function Stat({
  icon: Icon,
  label,
  value,
}: Readonly<{
  icon?: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
}>) {
  return (
    <div className="flex items-center gap-1">
      {Icon ? <Icon className="size-3" aria-hidden /> : null}
      <span className="tabular-nums font-medium text-foreground">{value}</span>
      <span>{label}</span>
    </div>
  );
}
