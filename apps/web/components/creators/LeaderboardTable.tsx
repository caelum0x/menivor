import type { LeaderboardEntry, LeaderboardMetric } from "@/lib/types";
import { Card, CardContent } from "@/components/ui/card";
import { LeaderboardRow } from "@/components/creators/LeaderboardRow";

export interface LeaderboardTableProps {
  entries: readonly LeaderboardEntry[];
  /** The metric the board is ranked by (passed through to each row). */
  metric: LeaderboardMetric;
}

/**
 * The ranked creator list. A thin wrapper that renders one {@link LeaderboardRow}
 * per entry, keyed by the stable `user_id`, inside a divided card.
 */
export function LeaderboardTable({
  entries,
  metric,
}: Readonly<LeaderboardTableProps>) {
  return (
    <Card>
      <CardContent className="p-0">
        <ul className="divide-y divide-border">
          {entries.map((entry) => (
            <LeaderboardRow key={entry.user_id} entry={entry} metric={metric} />
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
