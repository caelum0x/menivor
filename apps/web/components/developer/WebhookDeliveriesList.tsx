"use client";

import * as React from "react";
import { AlertTriangle, Inbox } from "lucide-react";
import type { WebhookDelivery } from "@/lib/types";
import { ApiError, listWebhookDeliveries } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useApiToken } from "@/lib/use-api-token";
import {
  deliveryStatusLabel,
  deliveryStatusVariant,
  formatDateTime,
} from "@/components/developer/format";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

interface WebhookDeliveriesListProps {
  workspaceId: string;
  subscriptionId: string;
  /** How many deliveries to load (newest first). */
  limit?: number;
  /** Bump to force a re-fetch (e.g. after a test delivery). */
  refreshNonce?: number;
}

type LoadState = "loading" | "ready" | "error";

const DEFAULT_LIMIT = 10;

/**
 * Recent deliveries for one subscription, loaded on mount (and whenever
 * `refreshNonce` changes). Tenant-scoped server-side; the signed payload body is
 * never fetched — only delivery metadata (status, attempts, response code,
 * timestamps). Read-only.
 */
export function WebhookDeliveriesList({
  workspaceId,
  subscriptionId,
  limit = DEFAULT_LIMIT,
  refreshNonce = 0,
}: WebhookDeliveriesListProps) {
  const getApiToken = useApiToken();
  const [status, setStatus] = React.useState<LoadState>("loading");
  const [deliveries, setDeliveries] = React.useState<readonly WebhookDelivery[]>(
    [],
  );
  const [errorMessage, setErrorMessage] = React.useState("");

  React.useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    void (async () => {
      setStatus("loading");
      setErrorMessage("");
      try {
        const token = await getApiToken();
        const result = await listWebhookDeliveries(
          workspaceId,
          subscriptionId,
          limit,
          { token, signal: controller.signal },
        );
        if (cancelled) return;
        setDeliveries(result);
        setStatus("ready");
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setErrorMessage(
          friendlyErrorMessage(err, "Couldn't load recent deliveries."),
        );
        setStatus("error");
      }
    })();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [getApiToken, workspaceId, subscriptionId, limit, refreshNonce]);

  if (status === "loading") {
    return (
      <div className="space-y-2">
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-9 w-full" />
      </div>
    );
  }

  if (status === "error") {
    return (
      <p
        className="flex items-center gap-2 text-sm text-destructive"
        role="alert"
      >
        <AlertTriangle className="size-4 shrink-0" aria-hidden />
        {errorMessage}
      </p>
    );
  }

  if (deliveries.length === 0) {
    return (
      <p className="flex items-center gap-2 rounded-md border border-dashed border-border p-3 text-sm text-muted-foreground">
        <Inbox className="size-4 shrink-0" aria-hidden />
        No deliveries yet. Send a test event to see one here.
      </p>
    );
  }

  return (
    <ul className="divide-y divide-border rounded-lg border border-border">
      {deliveries.map((d) => (
        <li
          key={d.id}
          className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 p-3 text-sm"
        >
          <div className="min-w-0 space-y-0.5">
            <div className="flex items-center gap-2">
              <code className="font-mono text-xs">{d.event_type}</code>
              <Badge variant={deliveryStatusVariant(d.status)}>
                {deliveryStatusLabel(d.status)}
              </Badge>
              {typeof d.response_code === "number" ? (
                <span className="text-xs text-muted-foreground">
                  HTTP {d.response_code}
                </span>
              ) : null}
            </div>
            <p className="truncate text-xs text-muted-foreground">
              {formatDateTime(d.last_attempt_at ?? d.created_at)} ·{" "}
              {d.attempts} attempt{d.attempts === 1 ? "" : "s"}
            </p>
          </div>
        </li>
      ))}
    </ul>
  );
}
