"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";
import { Crown, RefreshCw } from "lucide-react";
import { ApiError, getLeaderboard } from "@/lib/api";
import {
  LEADERBOARD_DEFAULT_LIMIT,
  LEADERBOARD_DEFAULT_METRIC,
} from "@/lib/types";
import type { LeaderboardEntry, LeaderboardMetric } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { CreatorsHeader } from "@/components/creators/CreatorsHeader";
import { LeaderboardTable } from "@/components/creators/LeaderboardTable";
import { MetricTabs } from "@/components/creators/MetricTabs";
import { EmptyPanel, ErrorPanel } from "@/components/creators/StatePanels";
import { metricLabel } from "@/components/creators/format";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

type LoadState = "loading" | "ready" | "error";

export default function LeaderboardPage() {
  const { getToken, isLoaded } = useAuth();

  const [metric, setMetric] = React.useState<LeaderboardMetric>(
    LEADERBOARD_DEFAULT_METRIC,
  );
  const [status, setStatus] = React.useState<LoadState>("loading");
  const [entries, setEntries] = React.useState<readonly LeaderboardEntry[]>([]);
  const [errorMessage, setErrorMessage] = React.useState<string>("");

  const load = React.useCallback(async () => {
    setStatus("loading");
    setErrorMessage("");
    try {
      // The leaderboard is PUBLIC; a signed-in caller's token is attached when
      // available but is not required (getLeaderboard falls back to the app key).
      const token = (await getToken()) ?? undefined;
      const result = await getLeaderboard(
        { metric, limit: LEADERBOARD_DEFAULT_LIMIT },
        { token },
      );
      setEntries(result);
      setStatus("ready");
    } catch (err) {
      const message =
        friendlyErrorMessage(err, "Something went wrong loading the leaderboard.");
      setErrorMessage(message);
      setStatus("error");
    }
  }, [getToken, metric]);

  React.useEffect(() => {
    if (isLoaded) void load();
  }, [isLoaded, load]);

  return (
    <main className="min-h-dvh">
      <CreatorsHeader showLeaderboardLink={false} />

      <section className="container py-8">
        <div className="mb-6 flex items-end justify-between gap-4">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
              <Crown className="size-6 text-primary" aria-hidden />
              Creator Leaderboard
            </h1>
            <p className="text-sm text-muted-foreground">
              The community&apos;s top creators, ranked by{" "}
              {metricLabel(metric).toLowerCase()}.
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void load()}
            disabled={status === "loading"}
          >
            <RefreshCw
              className={status === "loading" ? "size-4 animate-spin" : "size-4"}
              aria-hidden
            />
            Refresh
          </Button>
        </div>

        <div className="mb-6">
          <MetricTabs
            value={metric}
            onChange={setMetric}
            disabled={status === "loading"}
          />
        </div>

        {status === "loading" && <LeaderboardSkeleton />}

        {status === "error" && (
          <ErrorPanel
            title="Couldn't load the leaderboard"
            message={errorMessage}
            onRetry={() => void load()}
          />
        )}

        {status === "ready" && entries.length === 0 && (
          <EmptyPanel
            icon={<Crown className="size-6 text-primary" aria-hidden />}
            title="No ranked creators yet"
            description="Publish templates and log real-world performance to climb the board."
          />
        )}

        {status === "ready" && entries.length > 0 && (
          <LeaderboardTable entries={entries} metric={metric} />
        )}
      </section>
    </main>
  );
}

function LeaderboardSkeleton() {
  return (
    <Card>
      <CardContent className="p-0">
        <ul className="divide-y divide-border">
          {Array.from({ length: 8 }).map((_, i) => (
            <li key={i} className="flex items-center gap-3 px-4 py-3">
              <Skeleton className="size-8 rounded-full" />
              <Skeleton className="size-10 rounded-full" />
              <div className="flex-1 space-y-2">
                <Skeleton className="h-4 w-40" />
                <Skeleton className="h-3 w-56" />
              </div>
              <Skeleton className="h-8 w-14" />
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
