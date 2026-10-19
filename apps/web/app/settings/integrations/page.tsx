"use client";

import * as React from "react";
import { Plug } from "lucide-react";
import { SettingsHeader } from "@/components/settings/SettingsHeader";
import { WorkspacePicker } from "@/components/settings/WorkspacePicker";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useApiToken } from "@/lib/use-api-token";
import { useMyWorkspaces } from "@/lib/use-my-workspaces";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import { AdAccountsSection } from "./_components/AdAccountsSection";
import { AgentSection } from "./_components/AgentSection";
import { ProductSourcesSection } from "./_components/ProductSourcesSection";
import { SocialSection } from "./_components/SocialSection";
import { StoreConnectSection } from "./_components/StoreConnectSection";
import { getIntegrations, type IntegrationsOverview, type Scope } from "./_lib/api";

type LoadState = "loading" | "ready" | "error";

/**
 * Settings -> Integrations (Creatify parity): Ad Accounts, the Ads agent with
 * Slack, Social accounts and Product sources. Everything is scoped to the
 * selected workspace; a Brand space narrows which ad accounts are visible.
 */
export default function IntegrationsPage() {
  const getApiToken = useApiToken();
  const { workspaces } = useMyWorkspaces();
  const [workspaceId, setWorkspaceId] = React.useState<string | null>(null);
  const [brandSpaceId, setBrandSpaceId] = React.useState<string>("");
  const [data, setData] = React.useState<IntegrationsOverview | null>(null);
  const [status, setStatus] = React.useState<LoadState>("loading");
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    const first = workspaces[0];
    if (workspaceId === null && first) setWorkspaceId(first.id);
  }, [workspaceId, workspaces]);

  const scope: Scope = React.useMemo(
    () => ({ workspaceId, brandSpaceId: brandSpaceId || null }),
    [workspaceId, brandSpaceId],
  );

  const load = React.useCallback(async () => {
    setError("");
    try {
      setData(await getIntegrations(scope, { token: (await getApiToken()) ?? "" }));
      setStatus("ready");
    } catch (err) {
      setError(friendlyErrorMessage(err, "Could not load integrations."));
      setStatus("error");
    }
  }, [getApiToken, scope]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const props = data ? { data, scope, getToken: getApiToken, onChanged: () => void load() } : null;

  return (
    <main className="min-h-dvh">
      <SettingsHeader active="/settings/integrations" />
      <section className="container py-10">
        <div className="mx-auto max-w-5xl space-y-10">
          <div className="space-y-4">
            <h1 className="flex items-center gap-2 text-3xl font-bold tracking-tight">
              <Plug className="size-7 text-primary" aria-hidden />
              Integrations
            </h1>
            <div className="flex flex-wrap gap-4">
              <WorkspacePicker
                workspaces={workspaces}
                selectedId={workspaceId}
                onSelect={(id) => {
                  setWorkspaceId(id);
                  setBrandSpaceId("");
                }}
              />
              {data && data.brand_spaces.length > 0 ? (
                <div className="flex flex-col gap-1.5 sm:max-w-xs">
                  <Label htmlFor="brand-space-picker">Brand space</Label>
                  <Select id="brand-space-picker" value={brandSpaceId} onChange={(e) => setBrandSpaceId(e.target.value)}>
                    <option value="">All accounts</option>
                    {data.brand_spaces.map((brand) => (
                      <option key={brand.id} value={brand.id}>{brand.name}</option>
                    ))}
                  </Select>
                </div>
              ) : null}
            </div>
          </div>

          {status === "loading" ? (
            <div className="grid gap-4 sm:grid-cols-3" aria-busy>
              {[0, 1, 2].map((i) => <Skeleton key={i} className="h-36 w-full" />)}
            </div>
          ) : null}

          {status === "error" ? (
            <div className="space-y-3">
              <p role="alert" className="text-sm text-destructive">{error}</p>
              <Button variant="outline" size="sm" onClick={() => void load()}>Try again</Button>
            </div>
          ) : null}

          {props ? (
            <>
              <AdAccountsSection {...props} />
              <AgentSection {...props} />
              <SocialSection {...props} />
              <ProductSourcesSection {...props} />
              <StoreConnectSection getToken={getApiToken} />
            </>
          ) : null}
        </div>
      </section>
    </main>
  );
}
