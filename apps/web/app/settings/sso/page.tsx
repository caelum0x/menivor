"use client";

import * as React from "react";
import { KeyRound, ShieldCheck } from "lucide-react";
import {
  Card,
  CardContent,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { SettingsHeader } from "@/components/settings/SettingsHeader";
import { WorkspacePicker } from "@/components/settings/WorkspacePicker";
import { SsoConnectionForm } from "@/components/settings/sso/SsoConnectionForm";
import { ScimTokensSection } from "@/components/settings/sso/ScimTokensSection";
import { SecurityPolicyForm } from "@/components/settings/sso/SecurityPolicyForm";
import {
  scimBaseUrl as buildScimBaseUrl,
  ssoAcsUrl,
  ssoMetadataUrl,
} from "@/lib/api";
import { useMyWorkspaces } from "@/lib/use-my-workspaces";
import { useWorkspacePermissions } from "@/lib/use-workspace-permissions";
import { useSsoConnection } from "@/lib/use-sso-connection";
import { useScimTokens } from "@/lib/use-scim-tokens";
import { useSecurityPolicy } from "@/lib/use-security-policy";
import { SSO_ENABLED, SSO_SALES_EMAIL } from "@/lib/sso-availability";

/**
 * ENTERPRISE — SSO & SCIM (settings/sso). Configure a workspace's identity
 * provider (SAML/OIDC), mint/rotate/revoke SCIM provisioning tokens, and set the
 * login security policy. Every control requires `workspace.settings` (owner/admin);
 * a caller without it sees a clear "not authorized" state rather than another
 * tenant's data. Secrets and certificates are write-only and never rendered back.
 * Tenant-isolated — only the selected workspace's configuration is ever shown.
 */
export default function SsoSettingsPage() {
  return SSO_ENABLED ? <SsoConfigurator /> : <SsoContactSales />;
}

/**
 * MN7a: shown while SSO is not sold yet. One action: write to sales. The
 * configuration forms below stay in the code behind the flag.
 */
function SsoContactSales() {
  const mailto = `mailto:${SSO_SALES_EMAIL}?subject=${encodeURIComponent(
    "Enterprise SSO for our team",
  )}`;
  return (
    <main className="min-h-dvh">
      <SettingsHeader active="/settings/sso" />
      <section className="container py-10">
        <div className="mx-auto max-w-3xl">
          <Card>
            <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
              <span className="flex size-12 items-center justify-center rounded-full bg-primary/10">
                <ShieldCheck className="size-6 text-primary" aria-hidden />
              </span>
              <h1 className="text-2xl font-bold tracking-tight">
                Single sign-on is on Enterprise plans
              </h1>
              <p className="max-w-md text-sm text-muted-foreground">
                SSO and SCIM are set up with each team directly. Write to us
                with your identity provider and team size and we will reply
                with the next step.
              </p>
              <Button asChild className="mt-2">
                <a href={mailto}>Contact sales</a>
              </Button>
              <p className="text-xs text-muted-foreground">{SSO_SALES_EMAIL}</p>
            </CardContent>
          </Card>
        </div>
      </section>
    </main>
  );
}

function SsoConfigurator() {
  const { status: wsStatus, workspaces, errorMessage: wsError } =
    useMyWorkspaces();

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
  const canManage = perms.has("workspace.settings");

  const sso = useSsoConnection(canManage ? selectedId : null);
  const scim = useScimTokens(canManage ? selectedId : null);
  const policy = useSecurityPolicy(canManage ? selectedId : null);

  const metadataUrl = selectedId ? ssoMetadataUrl(selectedId) : "";
  const acsUrl = selectedId ? ssoAcsUrl(selectedId) : "";
  const scimUrl = selectedId ? buildScimBaseUrl(selectedId) : "";

  return (
    <main className="min-h-dvh">
      <SettingsHeader active="/settings/sso" />

      <section className="container py-10">
        <div className="mx-auto max-w-3xl space-y-6">
          <div>
            <h1 className="flex items-center gap-2 text-3xl font-bold tracking-tight">
              <ShieldCheck className="size-7 text-primary" aria-hidden />
              SSO &amp; SCIM
            </h1>
            <p className="mt-2 text-sm text-muted-foreground">
              Connect an identity provider for single sign-on, automate member
              provisioning with SCIM, and enforce login security rules. Only
              workspace admins and owners can configure these.
            </p>
          </div>

          {wsStatus === "error" ? (
            <Card>
              <CardContent className="py-8 text-sm text-destructive" role="alert">
                {wsError}
              </CardContent>
            </Card>
          ) : wsStatus === "ready" && workspaces.length === 0 ? (
            <Card className="border-dashed">
              <CardContent className="flex flex-col items-center gap-2 py-16 text-center">
                <span className="flex size-12 items-center justify-center rounded-full bg-primary/10">
                  <KeyRound className="size-6 text-primary" aria-hidden />
                </span>
                <p className="font-medium">No workspaces yet</p>
                <p className="text-sm text-muted-foreground">
                  Create a workspace to configure enterprise SSO and SCIM.
                </p>
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

              {perms.status === "ready" && !canManage ? (
                <Card>
                  <CardContent className="py-8 text-sm text-muted-foreground">
                    You need the workspace <strong>admin</strong> or{" "}
                    <strong>owner</strong> role to configure SSO, SCIM, and
                    security policy. Ask a workspace admin for access.
                  </CardContent>
                </Card>
              ) : canManage ? (
                <div className="space-y-6">
                  <SsoConnectionForm
                    connection={sso.connection}
                    canManage={canManage}
                    acsUrl={acsUrl}
                    metadataUrl={metadataUrl}
                    onSave={sso.save}
                    onDelete={sso.remove}
                  />

                  <ScimTokensSection
                    status={scim.status}
                    tokens={scim.tokens}
                    errorMessage={scim.errorMessage}
                    forbidden={scim.errorStatus === 403}
                    canManage={canManage}
                    scimBaseUrl={scimUrl}
                    onCreate={scim.create}
                    onRevoke={scim.revoke}
                    onReload={scim.reload}
                  />

                  <SecurityPolicyForm
                    policy={policy.policy}
                    canManage={canManage}
                    onSave={policy.save}
                  />
                </div>
              ) : (
                <Card>
                  <CardContent className="py-8 text-sm text-muted-foreground">
                    Loading workspace permissions…
                  </CardContent>
                </Card>
              )}
            </>
          )}
        </div>
      </section>
    </main>
  );
}
