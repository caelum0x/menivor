"use client";

import * as React from "react";
import Link from "next/link";
import { ShieldCheck, Users } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { SettingsHeader } from "@/components/settings/SettingsHeader";
import { WorkspacePicker } from "@/components/settings/WorkspacePicker";
import { RbacMemberList } from "@/components/settings/RbacMemberList";
import { roleLabel } from "@/components/settings/roles";
import { useRbacMembers } from "@/components/settings/use-rbac-members";
import { useCurrentUserId } from "@/lib/use-current-user";
import { useMyWorkspaces } from "@/lib/use-my-workspaces";
import { useWorkspacePermissions } from "@/lib/use-workspace-permissions";
import { canManageMembers, roleRank } from "@/lib/types";

/**
 * ENTERPRISE — Team & roles (settings/team). Manage each member's Enterprise
 * role (owner / admin / editor / billing / viewer) for a workspace the caller
 * belongs to. Role controls appear only when the caller holds `members.manage`;
 * the caller can never grant a role above their own, and the last owner can't be
 * demoted — both reflected in the UI and enforced server-side. Tenant-isolated:
 * only the selected workspace's roster is ever shown.
 */
export default function TeamSettingsPage() {
  const { status: wsStatus, workspaces, errorMessage: wsError } =
    useMyWorkspaces();
  const currentUserId = useCurrentUserId();

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
  const members = useRbacMembers(selectedId);

  const canManage = canManageMembers(perms.role);
  const actorRank = roleRank(perms.role);

  return (
    <main className="min-h-dvh">
      <SettingsHeader active="/settings/team" />

      <section className="container py-10">
        <div className="mx-auto max-w-3xl space-y-6">
          <div>
            <h1 className="flex items-center gap-2 text-3xl font-bold tracking-tight">
              <Users className="size-7 text-primary" aria-hidden />
              Team &amp; roles
            </h1>
            <p className="mt-2 text-sm text-muted-foreground">
              Assign each teammate an Enterprise role. Admins and owners can
              change roles; you can never grant a role above your own, and a
              workspace always keeps at least one owner.
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
                  <Users className="size-6 text-primary" aria-hidden />
                </span>
                <p className="font-medium">No workspaces yet</p>
                <p className="text-sm text-muted-foreground">
                  Create a workspace to invite teammates and manage roles.
                </p>
                <Button asChild variant="outline" size="sm" className="mt-2">
                  <Link href="/workspace">Go to workspaces</Link>
                </Button>
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardHeader>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <CardTitle className="flex items-center gap-2">
                      <ShieldCheck className="size-5 text-primary" aria-hidden />
                      Members
                    </CardTitle>
                    <CardDescription>
                      {perms.status === "ready" && (
                        <>
                          Your role:{" "}
                          <Badge variant="outline" className="align-middle">
                            {roleLabel(perms.role)}
                          </Badge>
                        </>
                      )}
                    </CardDescription>
                  </div>
                  <WorkspacePicker
                    workspaces={workspaces}
                    selectedId={selectedId}
                    onSelect={setSelectedId}
                    disabled={members.status === "loading"}
                  />
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                {!canManage && perms.status === "ready" && (
                  <p className="rounded-md border border-border bg-secondary/30 p-3 text-sm text-muted-foreground">
                    You have view-only access to roles in this workspace. Ask an
                    admin or owner to change roles.
                  </p>
                )}
                <RbacMemberList
                  status={members.status}
                  members={members.members}
                  errorMessage={members.errorMessage}
                  currentUserId={currentUserId}
                  canManage={canManage}
                  actorRank={actorRank}
                  ownerCount={members.ownerCount}
                  pendingIds={members.pendingIds}
                  rowErrors={members.rowErrors}
                  onChangeRole={members.changeRole}
                  onRetry={members.reload}
                />
              </CardContent>
            </Card>
          )}
        </div>
      </section>
    </main>
  );
}
