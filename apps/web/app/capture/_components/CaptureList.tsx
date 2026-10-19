"use client";

import * as React from "react";
import Link from "next/link";
import { Film, RefreshCw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorText, errorMessage, useRequestOptions } from "@/src/features/ad-studio/shared";
import { POLL_INTERVAL_MS } from "@/src/shared/api";
import { KIND_LABELS, isActive, listCaptures, type CaptureStatus, type CaptureSummary } from "./api";

export function StatusBadge({ status }: { status: CaptureStatus }) {
  const variant =
    status === "succeeded" ? "success" : status === "failed" ? "destructive" : status === "canceled" ? "outline" : "default";
  const label =
    status === "queued" ? "Queued" : status === "running" ? "Recording" : status === "succeeded" ? "Ready" : status === "failed" ? "Failed" : "Canceled";
  return <Badge variant={variant}>{label}</Badge>;
}

/** The caller's captures; polls while any is queued or recording. */
export function CaptureList() {
  const requestOptions = useRequestOptions();
  const [items, setItems] = React.useState<CaptureSummary[] | null>(null);
  const [error, setError] = React.useState("");

  const load = React.useCallback(async () => {
    try {
      const data = await listCaptures(await requestOptions());
      setItems(data.captures);
      setError("");
    } catch (err) {
      setError(errorMessage(err));
      setItems((cur) => cur ?? []);
    }
  }, [requestOptions]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const polling = (items ?? []).some((c) => isActive(c.status));
  React.useEffect(() => {
    if (!polling) return;
    const timer = window.setInterval(() => void load(), POLL_INTERVAL_MS + 1000);
    return () => window.clearInterval(timer);
  }, [polling, load]);

  return (
    <section aria-labelledby="captures-heading" className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 id="captures-heading" className="text-lg font-semibold">
          Your captures
        </h2>
        <Button variant="ghost" size="sm" onClick={() => void load()} aria-label="Refresh captures">
          <RefreshCw className="h-4 w-4" aria-hidden />
        </Button>
      </div>
      <ErrorText message={error} />
      {items === null ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-28 w-full" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <p className="rounded-md border border-dashed p-6 text-sm text-muted-foreground">
          No captures yet. Paste the link to one of your sites or store listings above, or record a mobile game from a simulator.
        </p>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {items.map((c) => (
            <li key={c.id}>
              <Link
                href={`/capture/${encodeURIComponent(c.id)}`}
                className="flex gap-3 rounded-lg border p-3 transition-colors hover:bg-secondary/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <div className="flex h-20 w-14 shrink-0 items-center justify-center overflow-hidden rounded bg-secondary">
                  {c.poster_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={c.poster_url} alt="" className="h-full w-full object-cover" />
                  ) : (
                    <Film className="h-5 w-5 text-muted-foreground" aria-hidden />
                  )}
                </div>
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex items-center gap-2">
                    <StatusBadge status={c.status} />
                    <span className="text-xs text-muted-foreground">{KIND_LABELS[c.source_kind]}</span>
                  </div>
                  <p className="truncate text-sm font-medium">{c.title || c.source_url}</p>
                  <p className="truncate text-xs text-muted-foreground">{c.source_url}</p>
                  {isActive(c.status) ? <Progress value={c.progress} className="h-1.5" /> : null}
                  {c.status === "failed" && c.error ? (
                    <p className="line-clamp-2 text-xs text-destructive">{c.error}</p>
                  ) : null}
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
