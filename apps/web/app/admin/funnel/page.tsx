"use client";

/**
 * Funnel read-out (MR1, staff only): every user who signed up since a date,
 * with card check, first render, first kept reel, first payment, plan and
 * source. Read-only; the API re-checks `is_staff` (403 otherwise). Missing
 * data reads "unknown" or "no", never 0.
 */

import * as React from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useApiToken } from "@/lib/use-api-token";
import { STEP_LABELS, dayOrNo, fetchFunnel, type FunnelPayload, type FunnelRow } from "./funnel-data";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

function Mix({ title, counts }: { readonly title: string; readonly counts: Readonly<Record<string, number>> }) {
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  return (
    <div className="rounded-lg border border-border p-4">
      <h2 className="text-sm font-medium">{title}</h2>
      <ul className="mt-2 space-y-1 text-sm text-muted-foreground">
        {entries.length ? (
          entries.map(([label, n]) => (
            <li key={label} className="flex justify-between gap-4">
              <span>{label}</span>
              <span className="tabular-nums">{n}</span>
            </li>
          ))
        ) : (
          <li>unknown</li>
        )}
      </ul>
    </div>
  );
}

export default function AdminFunnelPage() {
  const getApiToken = useApiToken();
  const [since, setSince] = React.useState("2026-09-25");
  const [data, setData] = React.useState<FunnelPayload | null>(null);
  const [error, setError] = React.useState("");
  const [loading, setLoading] = React.useState(false);

  const load = React.useCallback(
    async (day: string) => {
      setLoading(true);
      setError("");
      try {
        setData(await fetchFunnel(day, await getApiToken()));
      } catch (err) {
        setError(friendlyErrorMessage(err, "Could not load the funnel."));
      } finally {
        setLoading(false);
      }
    },
    [getApiToken],
  );

  React.useEffect(() => {
    void load("2026-09-25");
  }, [load]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Funnel</h1>
        <p className="text-sm text-muted-foreground">
          Every user who signed up since the date, from our own records.
        </p>
      </div>

      <form
        className="flex items-end gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          void load(since);
        }}
      >
        <label className="flex flex-col gap-1 text-sm">
          Since
          <input
            type="date"
            value={since}
            onChange={(event) => setSince(event.target.value)}
            className="rounded-md border border-border bg-background px-2 py-1"
          />
        </label>
        <Button type="submit" size="sm" disabled={loading}>
          {loading ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
          Show
        </Button>
      </form>

      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}

      {data ? (
        <>
          <div className="grid gap-3 sm:grid-cols-5" data-testid="funnel-reach">
            {STEP_LABELS.map(([key, label]) => (
              <div key={key} className="rounded-lg border border-border p-4">
                <p className="text-xs text-muted-foreground">{label}</p>
                <p className="text-2xl font-semibold tabular-nums">{data.totals.reach[key] ?? "unknown"}</p>
              </div>
            ))}
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Mix title="Source" counts={data.totals.by_source} />
            <Mix title="Plan" counts={data.totals.by_plan} />
          </div>
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-sm">
              <thead className="bg-secondary/40 text-left text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2">User</th>
                  {STEP_LABELS.map(([key, label]) => (
                    <th key={key} className="px-3 py-2">
                      {label}
                    </th>
                  ))}
                  <th className="px-3 py-2">Plan</th>
                  <th className="px-3 py-2">Source</th>
                  <th className="px-3 py-2">UTM source</th>
                  <th className="px-3 py-2">Campaign</th>
                  <th className="px-3 py-2">Referrer</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <tr key={row.user_id} className="border-t border-border">
                    <td className="max-w-[14rem] truncate px-3 py-2">{row.email || row.user_id}</td>
                    {STEP_LABELS.map(([key]) => (
                      <td key={key} className="whitespace-nowrap px-3 py-2 tabular-nums">
                        {dayOrNo(row[key] as string | null)}
                      </td>
                    ))}
                    <td className="px-3 py-2">{row.plan}</td>
                    <td className="px-3 py-2">{row.source}</td>
                    <td className="px-3 py-2">{row.utm_source}</td>
                    <td className="px-3 py-2">{row.utm_campaign}</td>
                    <td className="max-w-[14rem] truncate px-3 py-2">{row.referrer}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </div>
  );
}
