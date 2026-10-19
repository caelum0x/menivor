"use client";

import * as React from "react";
import { AlertTriangle, Gauge, KeyRound, RefreshCw } from "lucide-react";
import type { ApiKeyUsage } from "@/lib/types";
import { ApiError, getApiKeyUsage } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { UsageList } from "@/components/usage/UsageCard";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

type LoadState = "loading" | "ready" | "error";

/**
 * The caller's per-key current-month usage + quotas, reusing the Epic-3 usage
 * fetcher (GET /me/api-keys/usage) and presentational {@link UsageList}. Strictly
 * caller-scoped and token-free; read-only.
 */
export function DeveloperUsageSection() {
  const getApiToken = useApiToken();
  const [status, setStatus] = React.useState<LoadState>("loading");
  const [usage, setUsage] = React.useState<readonly ApiKeyUsage[]>([]);
  const [errorMessage, setErrorMessage] = React.useState("");

  const load = React.useCallback(async () => {
    setStatus("loading");
    setErrorMessage("");
    try {
      const token = await getApiToken();
      const result = await getApiKeyUsage({ token });
      setUsage(result);
      setStatus("ready");
    } catch (err) {
      setErrorMessage(
        friendlyErrorMessage(err, "Couldn't load your API-key usage."),
      );
      setStatus("error");
    }
  }, [getApiToken]);

  React.useEffect(() => {
    void load();
  }, [load]);

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Gauge className="size-5 text-primary" aria-hidden />
              Usage &amp; quota
            </CardTitle>
            <CardDescription>
              Per-key rate limits, monthly quotas, and requests used this month.
            </CardDescription>
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
      </CardHeader>
      <CardContent>
        {status === "loading" ? (
          <div className="grid gap-4 sm:grid-cols-2">
            <Skeleton className="h-28 w-full rounded-lg" />
            <Skeleton className="h-28 w-full rounded-lg" />
          </div>
        ) : status === "error" ? (
          <p
            className="flex items-center gap-2 text-sm text-destructive"
            role="alert"
          >
            <AlertTriangle className="size-4 shrink-0" aria-hidden />
            {errorMessage}
          </p>
        ) : usage.length === 0 ? (
          <p className="flex flex-col items-center gap-2 rounded-md border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
            <KeyRound className="size-6 text-muted-foreground" aria-hidden />
            No usage yet. Create an API key and make a request to see your
            per-key usage here.
          </p>
        ) : (
          <UsageList usage={usage} />
        )}
      </CardContent>
    </Card>
  );
}
