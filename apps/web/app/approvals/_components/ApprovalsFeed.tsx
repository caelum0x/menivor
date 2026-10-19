"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorText, useRequestOptions } from "@/src/features/ad-studio/shared";
import { readableApiError, useLaunchGate } from "@/src/shared/launch-gate";
import { ApprovalItemCard } from "./ApprovalItemCard";
import { AutoSourcesSettings } from "./AutoSourcesSettings";
import {
  SOURCE_LABELS,
  listApprovals,
  type ApprovalItem,
  type ApprovalList,
  type ApprovalSource,
  type StatusFilter,
} from "./api";

const PAGE_SIZE = 25;
const SOURCES = Object.keys(SOURCE_LABELS) as ApprovalSource[];

/** Unified queue: reply drafts, held posts, budget splits and publish requests waiting on a decision. */
export function ApprovalsFeed() {
  const launch = useLaunchGate();
  const requestOptions = useRequestOptions();
  const [status, setStatus] = React.useState<StatusFilter>("pending");
  const [source, setSource] = React.useState<ApprovalSource | "">("");
  const [offset, setOffset] = React.useState(0);
  const [data, setData] = React.useState<ApprovalList | null>(null);
  const [error, setError] = React.useState("");
  const [loading, setLoading] = React.useState(true);
  const [reloadKey, setReloadKey] = React.useState(0);

  React.useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const next = await listApprovals({ status, source, offset, limit: PAGE_SIZE }, await requestOptions());
        if (!cancelled) {
          setData(next);
          setError("");
        }
      } catch (err) {
        if (!cancelled) setError(readableApiError(err, "Couldn't load your approvals. Try again."));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [requestOptions, status, source, offset, reloadKey]);

  const onDecided = React.useCallback(
    (next: ApprovalItem) => {
      setData((prev) => {
        if (!prev) return prev;
        const items =
          status === "pending"
            ? prev.items.filter((item) => item.id !== next.id)
            : prev.items.map((item) => (item.id === next.id ? next : item));
        const wasPending = prev.items.some((item) => item.id === next.id && item.can_decide) && !next.can_decide;
        return { ...prev, items, pending_count: Math.max(0, prev.pending_count - (wasPending ? 1 : 0)) };
      });
    },
    [status],
  );

  const changeFilter = (nextStatus: StatusFilter, nextSource: ApprovalSource | "") => {
    setStatus(nextStatus);
    setSource(nextSource);
    setOffset(0);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <div role="group" aria-label="Status" className="flex gap-1">
          <Button size="sm" variant={status === "pending" ? "default" : "outline"} onClick={() => changeFilter("pending", source)}>
            Pending{data ? ` (${data.pending_count})` : ""}
          </Button>
          <Button size="sm" variant={status === "all" ? "default" : "outline"} onClick={() => changeFilter("all", source)}>
            History
          </Button>
        </div>
        <label className="ml-auto flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">Source</span>
          <select
            className="h-8 rounded-md border bg-background px-2 text-sm"
            value={source}
            onChange={(event) => changeFilter(status, event.target.value as ApprovalSource | "")}
          >
            <option value="">All sources</option>
            {SOURCES.map((key) => (
              <option key={key} value={key}>
                {SOURCE_LABELS[key]}
                {data?.pending_by_source[key] ? ` (${data.pending_by_source[key]})` : ""}
              </option>
            ))}
          </select>
        </label>
        <Button size="sm" variant="ghost" onClick={() => setReloadKey((k) => k + 1)} disabled={loading}>
          Refresh
        </Button>
      </div>

      <AutoSourcesSettings onChanged={() => setReloadKey((k) => k + 1)} />

      {data?.unavailable_sources.length ? (
        <p className="text-xs text-muted-foreground">
          Could not refresh: {data.unavailable_sources.join(", ")}. Showing what was already queued.
        </p>
      ) : null}

      {error ? <ErrorText message={error} /> : null}

      {loading && !data ? (
        <div className="space-y-3" aria-busy="true">
          <Skeleton className="h-32" />
          <Skeleton className="h-32" />
        </div>
      ) : data && data.items.length === 0 ? (
        <div className="rounded-lg border border-dashed p-6 text-sm text-muted-foreground">
          {status === "pending"
            ? "Nothing is waiting on you. Reply drafts, held posts and budget changes show up here before anything is sent or spent."
            : "No decisions recorded yet."}
        </div>
      ) : data ? (
        <div className="space-y-3" aria-busy={loading}>
          {data.items.map((item) => (
            <ApprovalItemCard
              key={item.id}
              item={item}
              onDecided={onDecided}
              publishGate={launch.gate.publishing}
              gateLoading={launch.status === "loading"}
            />
          ))}
        </div>
      ) : null}

      {data && data.total > PAGE_SIZE ? (
        <div className="flex items-center justify-between text-sm">
          <Button size="sm" variant="outline" disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
            Previous
          </Button>
          <span className="text-muted-foreground">
            {offset + 1}-{Math.min(offset + PAGE_SIZE, data.total)} of {data.total}
          </span>
          <Button
            size="sm"
            variant="outline"
            disabled={offset + PAGE_SIZE >= data.total || loading}
            onClick={() => setOffset(offset + PAGE_SIZE)}
          >
            Next
          </Button>
        </div>
      ) : null}
    </div>
  );
}
