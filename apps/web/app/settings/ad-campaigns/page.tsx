"use client";

import * as React from "react";
import { Megaphone } from "lucide-react";
import { SettingsHeader } from "@/components/settings/SettingsHeader";
import { WorkspacePicker } from "@/components/settings/WorkspacePicker";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useApiToken } from "@/lib/use-api-token";
import { useMyWorkspaces } from "@/lib/use-my-workspaces";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import {
  draftCampaign,
  listDraftableAccounts,
  validateDraftInput,
  type DraftableAccount,
  type DraftCampaignResult,
  type Scope,
} from "./_lib/api";

type LoadState = "loading" | "ready" | "error";

/**
 * Settings -> Ad campaigns: draft a new campaign on a connected Google Ads,
 * Meta or Apple Search Ads account. The campaign always comes back PAUSED --
 * review and launch it from the platform's own dashboard.
 */
export default function AdCampaignsPage() {
  const getApiToken = useApiToken();
  const { workspaces } = useMyWorkspaces();
  const [workspaceId, setWorkspaceId] = React.useState<string | null>(null);
  const [accounts, setAccounts] = React.useState<readonly DraftableAccount[]>([]);
  const [status, setStatus] = React.useState<LoadState>("loading");
  const [error, setError] = React.useState("");
  const [accountId, setAccountId] = React.useState("");
  const [name, setName] = React.useState("");
  const [dailyBudget, setDailyBudget] = React.useState("20");
  const [countries, setCountries] = React.useState("US");
  const [adamId, setAdamId] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [result, setResult] = React.useState<DraftCampaignResult | null>(null);

  React.useEffect(() => {
    const first = workspaces[0];
    if (workspaceId === null && first) setWorkspaceId(first.id);
  }, [workspaceId, workspaces]);

  const scope: Scope = React.useMemo(() => ({ workspaceId }), [workspaceId]);

  const load = React.useCallback(async () => {
    setError("");
    try {
      const token = (await getApiToken()) ?? "";
      const list = await listDraftableAccounts(scope, { token });
      setAccounts(list);
      setAccountId((current) => current || list[0]?.id || "");
      setStatus("ready");
    } catch (err) {
      setError(friendlyErrorMessage(err, "Could not load connected ad accounts."));
      setStatus("error");
    }
  }, [getApiToken, scope]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const selected = accounts.find((a) => a.id === accountId) ?? null;
  const isApple = selected?.provider === "Apple Search Ads";

  const submit = React.useCallback(async () => {
    setError("");
    setResult(null);
    const minor = Math.round(Number(dailyBudget) * 100);
    const problem = validateDraftInput(name, minor);
    if (problem) {
      setError(problem);
      return;
    }
    if (!accountId) {
      setError("Connect an ad account first.");
      return;
    }
    setBusy(true);
    try {
      const token = (await getApiToken()) ?? "";
      const draft = await draftCampaign(accountId, {
        name,
        dailyBudgetMinor: minor,
        countries: countries.split(",").map((c) => c.trim()).filter(Boolean),
        adamId,
      }, scope, { token });
      setResult(draft);
    } catch (err) {
      setError(friendlyErrorMessage(err, "Could not create the campaign."));
    } finally {
      setBusy(false);
    }
  }, [accountId, adamId, countries, dailyBudget, getApiToken, name, scope]);

  return (
    <main className="min-h-dvh">
      <SettingsHeader active="/settings/ad-campaigns" />
      <section className="container py-10">
        <div className="mx-auto max-w-2xl space-y-8">
          <div className="space-y-4">
            <h1 className="flex items-center gap-2 text-3xl font-bold tracking-tight">
              <Megaphone className="size-7 text-primary" aria-hidden />
              Ad campaigns
            </h1>
            <p className="text-sm text-muted-foreground">
              Draft a new campaign on a connected Google Ads, Meta or Apple Search Ads account. It is
              created PAUSED every time -- review targeting and creative, then launch it yourself on the
              platform.
            </p>
            <WorkspacePicker workspaces={workspaces} selectedId={workspaceId} onSelect={setWorkspaceId} />
          </div>

          {status === "loading" ? <Skeleton className="h-40 w-full" aria-busy /> : null}
          {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}

          {status === "ready" && accounts.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Connect a Google Ads, Meta or Apple Search Ads account in Settings {"->"} Integrations first.
            </p>
          ) : null}

          {status === "ready" && accounts.length > 0 ? (
            <Card>
              <CardHeader>
                <CardTitle>New campaign</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-1.5">
                  <Label htmlFor="draft-account">Ad account</Label>
                  <Select id="draft-account" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
                    {accounts.map((a) => (
                      <option key={a.id} value={a.id}>{a.provider} -- {a.name} ({a.currency})</option>
                    ))}
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="draft-name">Campaign name</Label>
                  <Input id="draft-name" value={name} onChange={(e) => setName(e.target.value)} />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="draft-budget">Daily budget ({selected?.currency ?? "USD"})</Label>
                  <Input
                    id="draft-budget"
                    type="number"
                    min="1"
                    step="1"
                    value={dailyBudget}
                    onChange={(e) => setDailyBudget(e.target.value)}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="draft-countries">Countries (comma-separated)</Label>
                  <Input id="draft-countries" value={countries} onChange={(e) => setCountries(e.target.value)} />
                </div>
                {isApple ? (
                  <div className="space-y-1.5">
                    <Label htmlFor="draft-adam-id">App Store app id (adamId)</Label>
                    <Input id="draft-adam-id" value={adamId} onChange={(e) => setAdamId(e.target.value)} />
                  </div>
                ) : null}
                <Button disabled={busy} onClick={() => void submit()}>
                  {busy ? "Creating..." : "Create paused draft"}
                </Button>
                {result ? (
                  <p className="text-sm text-muted-foreground">
                    Created &quot;{result.name}&quot; (paused) on {result.provider}.{" "}
                    <a className="underline" href={result.manage_url} target="_blank" rel="noreferrer">
                      Open it on the platform
                    </a>
                  </p>
                ) : null}
              </CardContent>
            </Card>
          ) : null}
        </div>
      </section>
    </main>
  );
}
