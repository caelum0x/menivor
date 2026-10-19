"use client";

import * as React from "react";
import { Activity, AlertTriangle, RefreshCw } from "lucide-react";

import { ApiError } from "@/lib/api";
import { getProviderHealth, type ProviderHealth } from "@/lib/marketplace";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

type LoadState = "loading" | "ready" | "error";

const STATE_STYLE: Record<ProviderHealth["state"], { label: string; className: string }> = {
  healthy: { label: "Operational", className: "text-emerald-600" },
  degraded: { label: "Degraded", className: "text-amber-600" },
  down: { label: "Down", className: "text-destructive" },
  unknown: { label: "No data", className: "text-muted-foreground" },
};

const DOT: Record<ProviderHealth["state"], string> = {
  healthy: "bg-emerald-500",
  degraded: "bg-amber-500",
  down: "bg-destructive",
  unknown: "bg-muted-foreground",
};

/** Public provider status page (no auth) — uptime + latency per provider. */
export default function StatusPage() {
  const [status, setStatus] = React.useState<LoadState>("loading");
  const [rows, setRows] = React.useState<ProviderHealth[]>([]);
  const [errorMessage, setErrorMessage] = React.useState("");

  const load = React.useCallback(async () => {
    setStatus("loading");
    setErrorMessage("");
    try {
      setRows(await getProviderHealth(undefined, 24));
      setStatus("ready");
    } catch (err) {
      setErrorMessage(
        friendlyErrorMessage(err, "Failed to load provider status."),
      );
      setStatus("error");
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  return (
    <main className="mx-auto max-w-3xl px-4 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Activity className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-semibold">Provider status</h1>
        </div>
        <Button variant="outline" size="sm" onClick={() => void load()}>
          <RefreshCw className="mr-2 h-4 w-4" aria-hidden /> Refresh
        </Button>
      </header>

      <p className="mb-4 text-sm text-muted-foreground">
        Rolling 24-hour uptime and average latency observed across generation runs.
      </p>

      {status === "loading" && (
        <div className="space-y-2">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      )}

      {status === "error" && (
        <Card>
          <CardContent className="flex items-center gap-3 py-6 text-destructive">
            <AlertTriangle className="h-5 w-5" aria-hidden />
            <p>{errorMessage}</p>
          </CardContent>
        </Card>
      )}

      {status === "ready" && rows.length === 0 && (
        <Card>
          <CardContent className="py-10 text-center text-muted-foreground">
            No provider observations yet.
          </CardContent>
        </Card>
      )}

      {status === "ready" && rows.length > 0 && (
        <ul className="divide-y rounded-lg border">
          {rows.map((p) => {
            const s = STATE_STYLE[p.state];
            return (
              <li key={p.provider_key} className="flex items-center justify-between gap-4 px-4 py-3">
                <div className="flex items-center gap-3">
                  <span className={`h-2.5 w-2.5 rounded-full ${DOT[p.state]}`} aria-hidden />
                  <div>
                    <p className="font-medium capitalize">{p.provider_key}</p>
                    <p className={`text-xs ${s.className}`}>{s.label}</p>
                  </div>
                </div>
                <div className="text-right text-sm text-muted-foreground tabular-nums">
                  <p>{(p.uptime * 100).toFixed(1)}% uptime</p>
                  <p>{p.avg_latency_ms} ms · {p.samples} runs</p>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </main>
  );
}
