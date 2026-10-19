"use client";

import * as React from "react";
import { Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { ErrorText, errorMessage, useRequestOptions } from "@/src/features/ad-studio/shared";
import { minorFactor, toMinor } from "@/src/features/ads/format";
import { MANUAL_NETWORKS, proposeSplit, type ManualNetworkId, type NetworkReport, type Proposal } from "./api";

interface ManualRow {
  network: ManualNetworkId;
  spend: string;
  results: string;
  daily: string;
}

function initialRows(report: NetworkReport): ManualRow[] {
  const factor = minorFactor(report.currency);
  return report.networks
    .filter((n) => n.source === "manual")
    .map((n) => ({
      network: n.network as ManualNetworkId,
      spend: String(n.spend_minor / factor),
      results: String(n.results),
      daily: String(n.current_daily_minor / factor),
    }));
}

/** Build today's proposal: optional new total, optional hand-entered networks. */
export function ProposeForm({ report, onProposed }: { report: NetworkReport; onProposed: (p: Proposal) => void }) {
  const requestOptions = useRequestOptions();
  const currency = report.currency || "USD";
  const [total, setTotal] = React.useState("");
  const [rows, setRows] = React.useState<ManualRow[]>(() => initialRows(report));
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const used = new Set(rows.map((r) => r.network));
  const nextNetwork = MANUAL_NETWORKS.find((n) => !used.has(n.id));

  function update(index: number, patch: Partial<ManualRow>) {
    setRows((prev) => prev.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    const totalValue = total.trim() ? Number(total) : undefined;
    if (totalValue !== undefined && (!Number.isFinite(totalValue) || totalValue <= 0)) {
      setError("Enter a positive daily total, or leave it empty to keep today's total.");
      return;
    }
    const manual = rows.map((r) => ({
      network: r.network,
      spend_minor: toMinor(Number(r.spend) || 0, currency),
      results: Math.max(0, Math.round(Number(r.results) || 0)),
      current_daily_minor: toMinor(Number(r.daily) || 0, currency),
    }));
    setBusy(true);
    try {
      const proposal = await proposeSplit(
        { total_daily_minor: totalValue !== undefined ? toMinor(totalValue, currency) : undefined, manual_networks: manual },
        await requestOptions(),
      );
      onProposed(proposal);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4 rounded-lg border p-4">
      <div className="space-y-1">
        <Label htmlFor="alloc-total">Total daily budget ({currency})</Label>
        <Input
          id="alloc-total"
          type="number"
          min={0}
          step="0.01"
          inputMode="decimal"
          placeholder="Leave empty to keep the current total"
          value={total}
          onChange={(e) => setTotal(e.target.value)}
          className="max-w-xs"
        />
      </div>

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">Networks Menivor cannot measure</legend>
        <p className="text-xs text-muted-foreground">
          Add results you track yourself, such as boosted posts. They are labelled as entered by you and are never moved
          automatically.
        </p>
        {rows.map((row, index) => (
          <div key={row.network} className="grid grid-cols-2 items-end gap-2 sm:grid-cols-[10rem_1fr_1fr_1fr_auto]">
            <div className="space-y-1">
              <Label htmlFor={`m-net-${index}`} className="text-xs">Network</Label>
              <Select
                id={`m-net-${index}`}
                value={row.network}
                onChange={(e) => update(index, { network: e.target.value as ManualNetworkId })}
              >
                {MANUAL_NETWORKS.filter((n) => n.id === row.network || !used.has(n.id)).map((n) => (
                  <option key={n.id} value={n.id}>
                    {n.label}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1">
              <Label htmlFor={`m-spend-${index}`} className="text-xs">Total spend</Label>
              <Input id={`m-spend-${index}`} type="number" min={0} step="0.01" value={row.spend}
                onChange={(e) => update(index, { spend: e.target.value })} />
            </div>
            <div className="space-y-1">
              <Label htmlFor={`m-results-${index}`} className="text-xs">{report.metric === "leads" ? "Leads" : "Clicks"}</Label>
              <Input id={`m-results-${index}`} type="number" min={0} step={1} value={row.results}
                onChange={(e) => update(index, { results: e.target.value })} />
            </div>
            <div className="space-y-1">
              <Label htmlFor={`m-daily-${index}`} className="text-xs">Daily budget now</Label>
              <Input id={`m-daily-${index}`} type="number" min={0} step="0.01" value={row.daily}
                onChange={(e) => update(index, { daily: e.target.value })} />
            </div>
            <Button type="button" variant="ghost" aria-label="Remove network"
              onClick={() => setRows((prev) => prev.filter((_, i) => i !== index))}>
              <Trash2 className="h-4 w-4" aria-hidden />
            </Button>
          </div>
        ))}
        {nextNetwork ? (
          <Button type="button" variant="outline" size="sm"
            onClick={() => setRows((prev) => [...prev, { network: nextNetwork.id, spend: "", results: "", daily: "" }])}>
            <Plus className="mr-1 h-4 w-4" aria-hidden />
            Add a network
          </Button>
        ) : null}
      </fieldset>

      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={busy}>
          {busy ? "Working..." : "Propose today's split"}
        </Button>
        <p className="text-xs text-muted-foreground">
          Nothing changes until you approve. Moves are capped at {Math.round(report.settings.max_step * 100)}% of the budget
          per network per day.
        </p>
      </div>
      <ErrorText message={error} />
    </form>
  );
}
