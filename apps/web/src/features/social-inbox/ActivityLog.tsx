"use client";

import * as React from "react";
import { Badge, type BadgeVariant } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import type { RequestOptions } from "@/src/shared/api";
import {
  ACTION_LABELS,
  ACTION_STATUS_LABELS,
  cleanError,
  listActivity,
  type ActionKind,
  type ActionStatus,
  type EngagementAction,
} from "./autopilot-api";
import { relativeTime } from "./format";

interface ActivityLogProps {
  getOptions: () => Promise<RequestOptions>;
}

const STATUS_VARIANT: Record<ActionStatus, BadgeVariant> = {
  pending_approval: "default",
  queued: "secondary",
  done: "success",
  rejected: "secondary",
  skipped: "outline",
  failed: "destructive",
};

/** Everything the autopilot did or proposed, and every rule change, newest first. */
export function ActivityLog({ getOptions }: Readonly<ActivityLogProps>) {
  const [kind, setKind] = React.useState<ActionKind | "">("");
  const [items, setItems] = React.useState<readonly EngagementAction[] | null>(null);
  const [total, setTotal] = React.useState(0);
  const [loadingMore, setLoadingMore] = React.useState(false);
  const [error, setError] = React.useState("");

  const load = React.useCallback(
    async (offset = 0) => {
      try {
        const page = await listActivity({ kind }, offset, await getOptions());
        setItems((prev) => (offset ? [...(prev ?? []), ...page.actions] : page.actions));
        setTotal(page.total);
        setError("");
      } catch (err) {
        setError(cleanError(err, "Couldn't load activity."));
        setItems((prev) => prev ?? []);
      }
    },
    [kind, getOptions],
  );

  React.useEffect(() => {
    setItems(null);
    void load(0);
  }, [load]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          Every like, hide, flag, reply and lead, with the reason, and every change to your rules.
        </p>
        <div className="w-48">
          <Select aria-label="Filter by action" value={kind} onChange={(e) => setKind(e.target.value as ActionKind | "")}>
            <option value="">All actions</option>
            {(Object.keys(ACTION_LABELS) as ActionKind[]).map((k) => (
              <option key={k} value={k}>
                {ACTION_LABELS[k]}
              </option>
            ))}
          </Select>
        </div>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}
      {items === null ? (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-14 w-full" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">Nothing yet.</CardContent>
        </Card>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border">
          {items.map((a) => (
            <li key={a.id} className="space-y-1 p-3 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-medium">
                  {ACTION_LABELS[a.kind]}
                  <span className="font-normal text-muted-foreground">
                    {" "}
                    {a.kind === "settings" ? `for ${a.platform_label}` : `${a.author_name ? `${a.author_name}, ` : ""}${a.platform_label}`}
                    {a.actor === "creator" ? ", by you" : ""}
                  </span>
                </span>
                <span className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Badge variant={STATUS_VARIANT[a.status]}>{ACTION_STATUS_LABELS[a.status]}</Badge>
                  {relativeTime(a.executed_at ?? a.created_at)}
                </span>
              </div>
              {a.excerpt && <p className="line-clamp-2 text-muted-foreground">&quot;{a.excerpt}&quot;</p>}
              {a.kind === "reply" && a.text && <p>Reply: {a.text}</p>}
              {a.reason && <p className="text-xs text-muted-foreground">{a.reason}</p>}
              {a.error && <p className="text-xs text-destructive">{a.error}</p>}
            </li>
          ))}
        </ul>
      )}
      {items !== null && items.length < total && (
        <Button
          variant="outline"
          size="sm"
          className="w-full"
          disabled={loadingMore}
          onClick={async () => {
            setLoadingMore(true);
            await load(items.length);
            setLoadingMore(false);
          }}
        >
          {loadingMore ? "Loading..." : `Load more (${total - items.length} left)`}
        </Button>
      )}
    </div>
  );
}
