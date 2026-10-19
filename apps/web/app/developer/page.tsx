"use client";

import * as React from "react";
import { Code2, KeyRound } from "lucide-react";
import { API_BASE, ensureWebhookWorkspace } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { WorkspacePicker } from "@/components/settings/WorkspacePicker";
import { ApiKeysManager } from "@/components/apikeys/ApiKeysManager";
import { DeveloperHeader } from "@/components/developer/DeveloperHeader";
import { DeveloperUsageSection } from "@/components/developer/DeveloperUsageSection";
import { IntegrationOverview } from "@/components/developer/IntegrationOverview";
import { ReferenceTools } from "@/components/developer/ReferenceTools";
import { SdkInstallSnippets } from "@/components/developer/SdkInstallSnippets";
import { WebhooksSection } from "@/components/developer/WebhooksSection";
import { useDeveloperPortal } from "@/lib/use-developer-portal";
import { useApiToken } from "@/lib/use-api-token";
import { useMyWorkspaces } from "@/lib/use-my-workspaces";
import { useWorkspacePermissions } from "@/lib/use-workspace-permissions";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

/**
 * ENTERPRISE — Developer portal (/developer). One place to integrate against the
 * Menivor API platform: manage API keys (mint/revoke), subscribe to signed
 * webhook events (create with a one-time signing secret, list, test, and inspect
 * recent deliveries), review per-key usage + quota, and grab the API reference +
 * SDK install snippets. Webhook management is gated by `workspace.settings`
 * (owner/admin) and is tenant-scoped — a caller only ever sees their own
 * workspace's subscriptions. Secrets (API keys, webhook signing secrets) are
 * shown exactly once at creation and never rendered again.
 */
export default function DeveloperPortalPage() {
  const portal = useDeveloperPortal();

  const {
    status: wsStatus,
    workspaces,
    errorMessage: wsError,
    reload: reloadWorkspaces,
  } = useMyWorkspaces();

  // A user with no workspace gets a personal one in one click, then the
  // normal webhooks section (with the one-time secret reveal) appears.
  const getApiToken = useApiToken();
  const [enabling, setEnabling] = React.useState(false);
  const [enableError, setEnableError] = React.useState("");
  const turnOnWebhooks = React.useCallback(async () => {
    setEnabling(true);
    setEnableError("");
    try {
      const token = await getApiToken();
      await ensureWebhookWorkspace({ token });
      reloadWorkspaces();
    } catch (err) {
      setEnableError(
        friendlyErrorMessage(err, "Couldn't turn on webhooks. Try again."),
      );
    } finally {
      setEnabling(false);
    }
  }, [getApiToken, reloadWorkspaces]);

  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  React.useEffect(() => {
    const first = workspaces[0];
    if (!first) {
      if (selectedId !== null) setSelectedId(null);
      return;
    }
    if (!workspaces.some((w) => w.id === selectedId)) setSelectedId(first.id);
  }, [workspaces, selectedId]);

  const perms = useWorkspacePermissions(selectedId);
  const canManageWebhooks = perms.has("workspace.settings");

  const apiBaseUrl = portal.portal?.api_base_url || API_BASE;

  return (
    <main className="min-h-dvh">
      <DeveloperHeader />

      <section className="container py-10">
        <div className="mx-auto max-w-4xl space-y-8">
          <div>
            <p className="text-sm font-medium text-muted-foreground">
              Developer
            </p>
            <h1 className="flex items-center gap-2 text-3xl font-bold tracking-tight">
              <Code2 className="size-7 text-primary" aria-hidden />
              Developer portal
            </h1>
            <p className="mt-2 max-w-2xl text-muted-foreground">
              Everything you need to integrate with the Menivor API:
              API keys, signed webhook events, usage, and SDKs.
            </p>
          </div>

          <IntegrationOverview
            status={portal.status}
            portal={portal.portal}
            errorMessage={portal.errorMessage}
          />

          <section aria-labelledby="developer-api-keys" className="space-y-4">
            <div>
              <h2
                id="developer-api-keys"
                className="text-lg font-semibold tracking-tight"
              >
                API keys
              </h2>
              <p className="text-sm text-muted-foreground">
                Create personal keys for programmatic access. Send a key as the{" "}
                <code className="rounded bg-secondary px-1 py-0.5 font-mono text-xs">
                  x-api-key
                </code>{" "}
                header. A key is shown once at creation — store it securely.
              </p>
            </div>
            <ApiKeysManager />
          </section>

          <section aria-labelledby="developer-webhooks" className="space-y-4">
            <h2 id="developer-webhooks" className="sr-only">
              Webhooks
            </h2>

            {wsStatus === "error" ? (
              <Card>
                <CardContent
                  className="py-8 text-sm text-destructive"
                  role="alert"
                >
                  {wsError}
                </CardContent>
              </Card>
            ) : wsStatus === "ready" && workspaces.length === 0 ? (
              <Card className="border-dashed">
                <CardContent className="flex flex-col items-center gap-2 py-12 text-center">
                  <span className="flex size-12 items-center justify-center rounded-full bg-primary/10">
                    <KeyRound className="size-6 text-primary" aria-hidden />
                  </span>
                  <p className="font-medium">Get signed events for your videos</p>
                  <p className="text-sm text-muted-foreground">
                    Turn on webhooks to get a signed call when a video is
                    ready or fails.
                  </p>
                  <Button
                    className="mt-2"
                    onClick={() => void turnOnWebhooks()}
                    disabled={enabling}
                  >
                    {enabling ? "Turning on..." : "Turn on webhooks"}
                  </Button>
                  {enableError ? (
                    <p className="text-sm text-destructive" role="alert">
                      {enableError}
                    </p>
                  ) : null}
                </CardContent>
              </Card>
            ) : (
              <>
                {workspaces.length > 1 && (
                  <Card>
                    <CardContent className="py-4">
                      <WorkspacePicker
                        workspaces={workspaces}
                        selectedId={selectedId}
                        onSelect={setSelectedId}
                      />
                    </CardContent>
                  </Card>
                )}

                <WebhooksSection
                  workspaceId={selectedId}
                  canManage={canManageWebhooks}
                />
              </>
            )}
          </section>

          <DeveloperUsageSection />

          <SdkInstallSnippets apiBaseUrl={apiBaseUrl} />

          <ReferenceTools />
        </div>
      </section>
    </main>
  );
}
