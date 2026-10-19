"use client";

import * as React from "react";
import Link from "next/link";
import { useAuth, UserButton } from "@/components/auth/clerk-safe";
import { AlertTriangle, BarChart3, RefreshCw, ShieldCheck, Wallet } from "lucide-react";

import { ApiError } from "@/lib/api";
import { BYOK_DEFAULT_FEE_BPS, BYOK_DEFAULT_MIN_FEE_MICROS } from "@/lib/byok";
import {
  formatUsdMicros,
  getSpendPolicy,
  getUsageSummary,
  updateSpendPolicy,
  type SpendPolicy,
  type UsageGroup,
  type UsageSummary,
} from "@/lib/marketplace";
import { Button } from "@/components/ui/button";
import { WalletNav } from "@/components/wallet/WalletNav";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

type LoadState = "loading" | "ready" | "error";

export default function SpendPage() {
  const { getToken, isLoaded } = useAuth();
  const [status, setStatus] = React.useState<LoadState>("loading");
  const [policy, setPolicy] = React.useState<SpendPolicy | null>(null);
  const [usage, setUsage] = React.useState<UsageSummary | null>(null);
  const [errorMessage, setErrorMessage] = React.useState("");

  const [budgetUsd, setBudgetUsd] = React.useState("0");
  const [saving, setSaving] = React.useState(false);

  const load = React.useCallback(async () => {
    setStatus("loading");
    setErrorMessage("");
    try {
      const token = (await getToken()) ?? undefined;
      const [p, u] = await Promise.all([
        getSpendPolicy({ token }),
        getUsageSummary({ token }, 30),
      ]);
      setPolicy(p);
      setUsage(u);
      setBudgetUsd((p.monthly_budget_micros / 1_000_000).toFixed(2));
      setStatus("ready");
    } catch (err) {
      setErrorMessage(
        friendlyErrorMessage(err, "Failed to load spend controls."),
      );
      setStatus("error");
    }
  }, [getToken]);

  React.useEffect(() => {
    if (isLoaded) void load();
  }, [isLoaded, load]);

  const save = React.useCallback(
    async (patch: { monthly_budget_micros?: number; byok_allowed?: boolean }) => {
      setSaving(true);
      try {
        const token = (await getToken()) ?? undefined;
        setPolicy(await updateSpendPolicy(patch, { token }));
      } catch (err) {
        setErrorMessage(friendlyErrorMessage(err, "Could not save."));
      } finally {
        setSaving(false);
      }
    },
    [getToken],
  );

  const budgetMicros = policy?.monthly_budget_micros ?? 0;
  const spent = policy?.period_spend_micros ?? 0;
  const pct = budgetMicros > 0 ? Math.min(100, (spent / budgetMicros) * 100) : 0;

  return (
    <main className="mx-auto max-w-3xl px-4 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BarChart3 className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-semibold">Spend &amp; usage</h1>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => void load()}>
            <RefreshCw className="mr-2 h-4 w-4" aria-hidden /> Refresh
          </Button>
          <Link href="/wallet" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
            <Wallet className="h-4 w-4" aria-hidden /> Wallet
          </Link>
          <UserButton afterSignOutUrl="/" />
        </div>
      </header>

      <WalletNav />

      {status === "loading" && (
        <div className="space-y-3">
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-40 w-full" />
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

      {status === "ready" && policy && usage && (
        <div className="space-y-6">
          <Card>
            <CardContent className="py-6">
              <h2 className="mb-3 text-lg font-medium">Monthly budget</h2>
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">Spent this month</span>
                <span className="tabular-nums font-medium">
                  {formatUsdMicros(spent)}
                  {budgetMicros > 0 ? ` / ${formatUsdMicros(budgetMicros)}` : " (no cap)"}
                </span>
              </div>
              {budgetMicros > 0 && (
                <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-muted">
                  <div
                    className={`h-full ${pct >= 100 ? "bg-destructive" : "bg-primary"}`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
              )}
              <div className="mt-4 flex flex-wrap items-end gap-3">
                <div className="grid gap-1">
                  <Label htmlFor="budget">Budget cap (USD/month, 0 = unlimited)</Label>
                  <Input
                    id="budget"
                    inputMode="decimal"
                    value={budgetUsd}
                    onChange={(e) => setBudgetUsd(e.target.value)}
                    className="w-40"
                  />
                </div>
                <Button
                  disabled={saving}
                  onClick={() =>
                    void save({
                      monthly_budget_micros: Math.max(
                        0,
                        Math.round(parseFloat(budgetUsd || "0") * 1_000_000),
                      ),
                    })
                  }
                >
                  Save budget
                </Button>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="flex items-center justify-between py-5">
              <div>
                <p className="flex items-center gap-2 font-medium">
                  <ShieldCheck className="h-4 w-4 text-primary" aria-hidden /> Bring your own keys
                </p>
                <p className="text-sm text-muted-foreground">
                  Allow jobs to route through your own provider credentials. The
                  provider bills you directly; Menivor charges a routing fee
                  ({BYOK_DEFAULT_FEE_BPS / 100}% of the equivalent provider price,
                  minimum {formatUsdMicros(BYOK_DEFAULT_MIN_FEE_MICROS)} per stage).
                </p>
                <Link
                  href="/settings/provider-keys"
                  className="mt-1 inline-block text-sm text-primary underline underline-offset-4"
                >
                  Manage provider keys
                </Link>
              </div>
              <Button
                variant={policy.byok_allowed ? "default" : "outline"}
                disabled={saving}
                onClick={() => void save({ byok_allowed: !policy.byok_allowed })}
              >
                {policy.byok_allowed ? "Enabled" : "Disabled"}
              </Button>
            </CardContent>
          </Card>

          <section>
            <h2 className="mb-3 text-lg font-medium">
              Cost by provider · last {usage.days} days · {usage.total_cost_usd}
            </h2>
            <UsageBreakdown title="Provider" rows={usage.by_provider} total={usage.total_cost_micros} />
            <div className="mt-4">
              <UsageBreakdown title="Model" rows={usage.by_model} total={usage.total_cost_micros} />
            </div>
            <div className="mt-4">
              <UsageBreakdown title="Stage" rows={usage.by_stage} total={usage.total_cost_micros} />
            </div>
          </section>
        </div>
      )}
    </main>
  );
}

function UsageBreakdown({
  title,
  rows,
  total,
}: {
  title: string;
  rows: UsageGroup[];
  total: number;
}) {
  if (rows.length === 0) {
    return <p className="text-sm text-muted-foreground">No {title.toLowerCase()} usage yet.</p>;
  }
  return (
    <div className="rounded-lg border">
      <p className="border-b px-4 py-2 text-xs uppercase tracking-wide text-muted-foreground">
        {title}
      </p>
      <ul className="divide-y">
        {rows.map((row) => {
          const pct = total > 0 ? (row.cost_micros / total) * 100 : 0;
          return (
            <li key={`${title}-${row.key}`} className="px-4 py-2">
              <div className="flex items-center justify-between text-sm">
                <span className="truncate font-medium">{row.key || "—"}</span>
                <span className="tabular-nums text-muted-foreground">
                  {row.cost_usd} · {row.runs} run{row.runs === 1 ? "" : "s"}
                </span>
              </div>
              <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-muted">
                <div className="h-full bg-primary/70" style={{ width: `${pct}%` }} />
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
