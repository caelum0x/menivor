"use client";

import * as React from "react";
import { ShieldCheck } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { SettingsHeader } from "@/components/settings/SettingsHeader";
import { WorkspacePicker } from "@/components/settings/WorkspacePicker";
import { DataExportCard } from "@/components/settings/privacy/DataExportCard";
import { ConsentTogglesCard } from "@/components/settings/privacy/ConsentTogglesCard";
import { RetentionPolicyForm } from "@/components/settings/privacy/RetentionPolicyForm";
import { DeleteAccountCard } from "@/components/settings/privacy/DeleteAccountCard";
import { useMyWorkspaces } from "@/lib/use-my-workspaces";
import { useWorkspacePermissions } from "@/lib/use-workspace-permissions";
import { useRetentionPolicy } from "@/lib/use-retention-policy";

/**
 * PRIVACY CENTER (settings/privacy). The caller's self-service data-governance
 * surface: export ALL of their own data (GDPR Art. 15/20), manage consent
 * decisions, permanently delete (anonymize) their own account (Art. 17), and —
 * for a workspace owner/admin — configure that workspace's data-retention window.
 * Every action is strictly scoped to the caller (or a `workspace.settings`-gated
 * workspace) server-side; nothing here can ever touch another user's data.
 */
export default function PrivacySettingsPage() {
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
  const canManageRetention = perms.has("workspace.settings");
  const retention = useRetentionPolicy(
    canManageRetention ? selectedId : null,
  );

  return (
    <main className="min-h-dvh">
      <SettingsHeader active="/settings/privacy" />

      <section className="container py-10">
        <div className="mx-auto max-w-3xl space-y-6">
          <div>
            <h1 className="flex items-center gap-2 text-3xl font-bold tracking-tight">
              <ShieldCheck className="size-7 text-primary" aria-hidden />
              Privacy center
            </h1>
            <p className="mt-2 text-sm text-muted-foreground">
              Export your data, manage your consent, and control retention for
              your workspaces. You can also permanently delete your account here.
            </p>
          </div>

          <DataExportCard />
          <ConsentTogglesCard />

          <div className="space-y-3">
            <div>
              <h2 className="text-lg font-semibold tracking-tight">
                Workspace data retention
              </h2>
              <p className="text-sm text-muted-foreground">
                Owners and admins can set how long a workspace keeps jobs and
                assets before they are automatically anonymized.
              </p>
            </div>

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
                <CardContent className="py-8 text-sm text-muted-foreground">
                  You don&apos;t belong to any workspaces yet. Create one to set a
                  retention policy.
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

                {perms.status === "ready" && !canManageRetention ? (
                  <Card>
                    <CardContent className="py-8 text-sm text-muted-foreground">
                      You need the workspace <strong>admin</strong> or{" "}
                      <strong>owner</strong> role to configure data retention.
                      Ask a workspace admin for access.
                    </CardContent>
                  </Card>
                ) : canManageRetention ? (
                  retention.status === "error" ? (
                    <Card>
                      <CardContent
                        className="py-8 text-sm text-destructive"
                        role="alert"
                      >
                        {retention.errorMessage}
                      </CardContent>
                    </Card>
                  ) : (
                    <RetentionPolicyForm
                      policy={retention.policy}
                      canManage={canManageRetention}
                      onSave={retention.save}
                    />
                  )
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

          <div className="space-y-3 pt-4">
            <h2 className="text-lg font-semibold tracking-tight text-destructive">
              Danger zone
            </h2>
            <DeleteAccountCard />
          </div>
        </div>
      </section>
    </main>
  );
}
