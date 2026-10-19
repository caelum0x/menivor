"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";
import { DollarSign, Loader2, Megaphone } from "lucide-react";

import { ApiError } from "@/src/shared/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { createCampaign, listCampaigns, usd, type Campaign } from "./api";
import { ClipSubmitForm } from "./ClipSubmitForm";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

/** Clipmarket: brands post CPM campaigns; clippers earn on verified views. */
export function ClipmarketDashboard() {
  const { getToken } = useAuth();
  const [campaigns, setCampaigns] = React.useState<Campaign[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [title, setTitle] = React.useState("");
  const [cpm, setCpm] = React.useState("2");
  const [budget, setBudget] = React.useState("500");
  const [busy, setBusy] = React.useState(false);

  const load = React.useCallback(async () => {
    try {
      const token = (await getToken()) ?? undefined;
      const res = await listCampaigns({ token });
      setCampaigns(res.campaigns);
    } catch (err) {
      setError(friendlyErrorMessage(err, "Failed to load."));
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const onCreate = React.useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const token = (await getToken()) ?? undefined;
      await createCampaign(
        {
          title: title.trim(),
          cpm_micros: Math.round(parseFloat(cpm || "0") * 1_000_000),
          budget_micros: Math.round(parseFloat(budget || "0") * 1_000_000),
        },
        { token },
      );
      setTitle("");
      await load();
    } catch (err) {
      setError(friendlyErrorMessage(err, "Failed to create."));
    } finally {
      setBusy(false);
    }
  }, [title, cpm, budget, getToken, load]);

  return (
    <div className="space-y-6">
      <Card>
        <CardContent className="space-y-3 py-5">
          <div className="flex items-center gap-2">
            <Megaphone className="h-4 w-4 text-primary" aria-hidden />
            <h2 className="font-semibold">New campaign</h2>
          </div>
          <Input placeholder="Campaign title" value={title} onChange={(e) => setTitle(e.target.value)} />
          <div className="flex gap-2">
            <label className="flex-1 text-xs text-muted-foreground">
              CPM (USD / 1k views)
              <Input inputMode="decimal" value={cpm} onChange={(e) => setCpm(e.target.value)} />
            </label>
            <label className="flex-1 text-xs text-muted-foreground">
              Budget (USD)
              <Input inputMode="decimal" value={budget} onChange={(e) => setBudget(e.target.value)} />
            </label>
          </div>
          <Button onClick={() => void onCreate()} disabled={busy}>
            {busy ? <Loader2 className="mr-1 h-4 w-4 animate-spin" aria-hidden /> : null}
            Launch campaign
          </Button>
          {error && <p className="text-sm text-destructive">{error}</p>}
        </CardContent>
      </Card>

      <div>
        <div className="mb-2 flex items-center gap-2 text-sm text-muted-foreground">
          <DollarSign className="h-4 w-4" aria-hidden /> Active campaigns
        </div>
        {loading ? (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading…
          </p>
        ) : campaigns.length === 0 ? (
          <p className="text-sm text-muted-foreground">No active campaigns yet.</p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {campaigns.map((c) => (
              <Card key={c.id}>
                <CardContent className="space-y-2 py-4">
                  <div className="flex items-center justify-between">
                    <p className="font-medium">{c.title || "Untitled"}</p>
                    <Badge variant="secondary">{c.status}</Badge>
                  </div>
                  <p className="text-sm text-muted-foreground">
                    {usd(c.cpm_micros)} CPM · {usd(c.spent_micros)} / {usd(c.budget_micros)} spent
                  </p>
                  <ClipSubmitForm campaignId={c.id} />
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
