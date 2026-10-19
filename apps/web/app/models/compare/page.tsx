"use client";

import * as React from "react";
import Link from "next/link";
import { useAuth, UserButton } from "@/components/auth/clerk-safe";
import { AlertTriangle, GitCompareArrows, RefreshCw } from "lucide-react";

import { ApiError } from "@/lib/api";
import { compareModels, formatUsdMicros, type CompareModel } from "@/lib/marketplace";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

type LoadState = "loading" | "ready" | "error";
type Sort = "price" | "latency";

const CAPABILITIES = ["script", "voice", "avatar", "broll", "image", "music"];
const STATE_DOT: Record<string, string> = {
  healthy: "bg-emerald-500",
  degraded: "bg-amber-500",
  down: "bg-destructive",
  unknown: "bg-muted-foreground",
};

/** Compare models for a capability by price + provider health (P2). */
export default function CompareModelsPage() {
  const { getToken, isLoaded } = useAuth();
  const [status, setStatus] = React.useState<LoadState>("loading");
  const [rows, setRows] = React.useState<CompareModel[]>([]);
  const [capability, setCapability] = React.useState("broll");
  const [sort, setSort] = React.useState<Sort>("price");
  const [errorMessage, setErrorMessage] = React.useState("");

  const load = React.useCallback(
    async (cap: string, s: Sort) => {
      setStatus("loading");
      setErrorMessage("");
      try {
        const token = (await getToken()) ?? undefined;
        setRows(await compareModels(cap, s, { token }));
        setStatus("ready");
      } catch (err) {
        setErrorMessage(
          friendlyErrorMessage(err, "Failed to load the comparison."),
        );
        setStatus("error");
      }
    },
    [getToken],
  );

  React.useEffect(() => {
    if (isLoaded) void load(capability, sort);
  }, [isLoaded, capability, sort, load]);

  return (
    <main className="mx-auto max-w-4xl px-4 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <GitCompareArrows className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-semibold">Compare models</h1>
        </div>
        <div className="flex items-center gap-2">
          <Button asChild variant="ghost" size="sm">
            <Link href="/models">All models</Link>
          </Button>
          <Button variant="outline" size="sm" onClick={() => void load(capability, sort)}>
            <RefreshCw className="mr-2 h-4 w-4" aria-hidden /> Refresh
          </Button>
          <UserButton afterSignOutUrl="/" />
        </div>
      </header>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        {CAPABILITIES.map((cap) => (
          <button
            key={cap}
            type="button"
            onClick={() => setCapability(cap)}
            className={`rounded-full border px-3 py-1 text-sm capitalize transition ${
              capability === cap
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border text-muted-foreground hover:text-foreground"
            }`}
          >
            {cap}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-1 text-sm">
          <span className="text-muted-foreground">Sort:</span>
          {(["price", "latency"] as Sort[]).map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setSort(s)}
              className={`rounded-md border px-2 py-1 capitalize ${
                sort === s ? "border-primary text-foreground" : "border-border text-muted-foreground"
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      {status === "loading" && (
        <div className="space-y-2">
          <Skeleton className="h-14 w-full" />
          <Skeleton className="h-14 w-full" />
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
            No live models for this capability yet.
          </CardContent>
        </Card>
      )}

      {status === "ready" && rows.length > 0 && (
        <div className="overflow-hidden rounded-lg border">
          <div className="grid grid-cols-[2fr_1fr_1fr_1fr] gap-2 border-b bg-muted/40 px-4 py-2 text-xs uppercase tracking-wide text-muted-foreground">
            <span>Model</span>
            <span className="text-right">Price</span>
            <span className="text-right">Uptime</span>
            <span className="text-right">Latency</span>
          </div>
          <ul className="divide-y">
            {rows.map((m) => {
              const h = m.health ?? {};
              const state = h.state ?? "unknown";
              return (
                <li key={m.model_id} className="grid grid-cols-[2fr_1fr_1fr_1fr] items-center gap-2 px-4 py-3">
                  <div className="min-w-0">
                    <p className="truncate font-medium">{m.display_name || m.model_id}</p>
                    <p className="flex items-center gap-1.5 truncate text-xs text-muted-foreground">
                      <span className={`h-2 w-2 rounded-full ${STATE_DOT[state]}`} aria-hidden />
                      {m.provider.display_name || m.provider.provider_key} · {m.latency_band || "—"}
                    </p>
                  </div>
                  <span className="text-right tabular-nums text-sm font-medium">
                    {m.price?.unit_price_micros != null
                      ? `${formatUsdMicros(m.price.unit_price_micros)}/${m.price.unit || m.metering_unit}`
                      : "—"}
                  </span>
                  <span className="text-right tabular-nums text-sm">
                    {h.samples ? `${((h.uptime ?? 0) * 100).toFixed(0)}%` : "—"}
                  </span>
                  <span className="text-right tabular-nums text-sm">
                    {h.samples ? `${h.avg_latency_ms ?? 0} ms` : "—"}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </main>
  );
}
