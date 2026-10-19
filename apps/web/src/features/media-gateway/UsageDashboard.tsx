"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";
import { Coins, RefreshCw, Wallet } from "lucide-react";

import { ApiError } from "@/src/shared/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  formatUsdMicros,
  getCredits,
  getUsage,
  type Credits,
  type UsageRow,
} from "./api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

type LoadState = "loading" | "ready" | "error";

/** OpenRouter-style credits + usage: spendable balance + spend-by-model. */
export function UsageDashboard() {
  const { getToken } = useAuth();
  const [state, setState] = React.useState<LoadState>("loading");
  const [credits, setCredits] = React.useState<Credits | null>(null);
  const [usage, setUsage] = React.useState<UsageRow[]>([]);
  const [error, setError] = React.useState("");

  const load = React.useCallback(async () => {
    setState("loading");
    setError("");
    try {
      const token = (await getToken()) ?? undefined;
      const [c, u] = await Promise.all([getCredits({ token }), getUsage({ token })]);
      setCredits(c);
      setUsage(u.usage);
      setState("ready");
    } catch (err) {
      setError(friendlyErrorMessage(err, "Failed to load."));
      setState("error");
    }
  }, [getToken]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const totalJobs = React.useMemo(() => usage.reduce((n, r) => n + r.jobs, 0), [usage]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Credits &amp; usage</h2>
          <p className="text-sm text-muted-foreground">
            One balance for every image and video model.
          </p>
        </div>
        <Button size="sm" variant="ghost" onClick={() => void load()} aria-label="Refresh">
          <RefreshCw className="h-4 w-4" />
        </Button>
      </div>

      {state === "error" ? (
        <Card>
          <CardContent className="py-6 text-sm text-red-600">{error}</CardContent>
        </Card>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-3">
        <StatCard
          icon={<Wallet className="h-4 w-4" />}
          label="Available"
          value={credits ? formatUsdMicros(credits.available_micros) : undefined}
          hint={
            credits && credits.reserved_micros
              ? `${formatUsdMicros(credits.reserved_micros)} reserved`
              : "spendable now"
          }
        />
        <StatCard
          icon={<Coins className="h-4 w-4" />}
          label="Lifetime spend"
          value={credits ? formatUsdMicros(credits.total_gateway_spend_micros) : undefined}
          hint="across all models"
        />
        <StatCard
          icon={<Coins className="h-4 w-4" />}
          label="Generations"
          value={state === "ready" ? String(totalJobs) : undefined}
          hint={`${usage.length} models used`}
        />
      </div>

      <Card>
        <CardContent className="p-0">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="px-4 py-2 font-medium">Model</th>
                <th className="px-4 py-2 font-medium">Type</th>
                <th className="px-4 py-2 text-right font-medium">Jobs</th>
                <th className="px-4 py-2 text-right font-medium">Seconds</th>
                <th className="px-4 py-2 text-right font-medium">Spend</th>
              </tr>
            </thead>
            <tbody>
              {state === "loading"
                ? Array.from({ length: 4 }).map((_, i) => (
                    <tr key={i} className="border-b last:border-0">
                      <td className="px-4 py-3" colSpan={5}>
                        <Skeleton className="h-4 w-full" />
                      </td>
                    </tr>
                  ))
                : usage.map((r) => (
                    <tr key={r.model} className="border-b last:border-0">
                      <td className="px-4 py-3 font-mono">{r.model}</td>
                      <td className="px-4 py-3">
                        <Badge variant="secondary">{r.modality}</Badge>
                      </td>
                      <td className="px-4 py-3 text-right">{r.jobs}</td>
                      <td className="px-4 py-3 text-right">{r.seconds || "—"}</td>
                      <td className="px-4 py-3 text-right font-medium">
                        {formatUsdMicros(r.spend_micros)}
                      </td>
                    </tr>
                  ))}
              {state === "ready" && usage.length === 0 ? (
                <tr>
                  <td className="px-4 py-6 text-center text-muted-foreground" colSpan={5}>
                    No usage yet — run a generation to see spend here.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
  hint,
}: {
  icon: React.ReactNode;
  label: string;
  value?: string;
  hint: string;
}) {
  return (
    <Card>
      <CardContent className="space-y-1 py-4">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          {icon}
          {label}
        </div>
        {value === undefined ? (
          <Skeleton className="h-7 w-24" />
        ) : (
          <div className="text-2xl font-semibold">{value}</div>
        )}
        <div className="text-xs text-muted-foreground">{hint}</div>
      </CardContent>
    </Card>
  );
}
