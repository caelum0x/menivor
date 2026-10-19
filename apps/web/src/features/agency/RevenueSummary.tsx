"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";
import { TrendingUp } from "lucide-react";

import { ApiError } from "@/src/shared/api";
import { Card, CardContent } from "@/components/ui/card";
import { bpsToPercent, formatUsdMicros, listKeys, type ProvisioningKey } from "./api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

/** Revenue projection across active client keys (margin at each key's markup). */
export function RevenueSummary() {
  const { getToken } = useAuth();
  const [keys, setKeys] = React.useState<ProvisioningKey[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    (async () => {
      try {
        const token = (await getToken()) ?? undefined;
        const { keys: rows } = await listKeys({ token });
        setKeys(rows);
      } catch (err) {
        setError(friendlyErrorMessage(err, "Failed to load revenue."));
      } finally {
        setLoading(false);
      }
    })();
  }, [getToken]);

  const active = keys.filter((k) => !k.disabled);
  // Projected margin if each active client spends its full daily cap for 30 days,
  // at that key's markup (base_at_cap = cap; margin = base·markup_bps).
  const monthlyMargin = active.reduce(
    (sum, k) => sum + Math.round((k.daily_cap_micros * k.markup_bps) / 10_000) * 30,
    0,
  );
  const avgMarkup = active.length
    ? Math.round(active.reduce((s, k) => s + k.markup_bps, 0) / active.length)
    : 0;

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Revenue</h2>

      <div className="grid gap-3 sm:grid-cols-3">
        <Stat label="Active clients" value={loading ? "…" : String(active.length)} />
        <Stat label="Avg markup" value={loading ? "…" : bpsToPercent(avgMarkup)} />
        <Stat label="Projected / mo" value={loading ? "…" : formatUsdMicros(monthlyMargin)} accent />
      </div>

      <Card>
        <CardContent className="p-0">
          <div className="border-b px-4 py-2 text-xs text-muted-foreground">
            Projection assumes each client spends its full daily cap. Actual margin bills only on success.
          </div>
          {active.map((k) => (
            <div key={k.id} className="flex items-center justify-between border-b px-4 py-3 text-sm last:border-0">
              <span>{k.label}</span>
              <span className="text-muted-foreground">
                {bpsToPercent(k.markup_bps)} · ~{formatUsdMicros(Math.round((k.daily_cap_micros * k.markup_bps) / 10_000) * 30)}/mo
              </span>
            </div>
          ))}
          {!loading && active.length === 0 ? (
            <div className="flex items-center gap-2 px-4 py-6 text-sm text-muted-foreground"><TrendingUp className="h-4 w-4" /> No active client keys yet.</div>
          ) : null}
        </CardContent>
      </Card>
      {error ? <div className="text-sm text-red-600">{error}</div> : null}
    </div>
  );
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <Card>
      <CardContent className="py-4">
        <div className="text-sm text-muted-foreground">{label}</div>
        <div className={`text-2xl font-semibold ${accent ? "text-green-600" : ""}`}>{value}</div>
      </CardContent>
    </Card>
  );
}
