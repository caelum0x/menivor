"use client";

import * as React from "react";
import { LogOut, RefreshCw, Users } from "lucide-react";
import {
  canManageWorkspace,
  type AssignableWorkspaceRole,
  type Workspace,
} from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { BuyTeamCredits } from "@/components/team/BuyTeamCredits";
import { InviteMemberForm } from "@/components/team/InviteMemberForm";
import { MemberList } from "@/components/team/MemberList";
import { PendingInvites } from "@/components/team/PendingInvites";
import { useInvites } from "@/components/team/use-invites";
import { WorkspaceCredits } from "@/components/team/WorkspaceCredits";
import { roleBadgeVariant, roleLabel } from "@/components/team/roles";
import { useMembers } from "@/components/team/use-members";

export interface WorkspaceDetailProps {
  workspace: Workspace;
  /** Signed-in caller's user id, to flag their own row + gate self-actions. */
  currentUserId: string | null;
  /** Called after the caller successfully leaves this workspace. */
  onLeft: (workspaceId: string) => void;
}

/**
 * Detail pane for one workspace: header (name + caller's role), an invite form
 * and pending-invite links (owners/admins only), the member list with role-aware controls, and a Leave
 * action. Owns its own member state via {@link useMembers}; the workspace's
 * `role` (the caller's own role) drives which controls appear.
 */
export function WorkspaceDetail({
  workspace,
  currentUserId,
  onLeft,
}: Readonly<WorkspaceDetailProps>) {
  const handleLeft = React.useCallback(() => {
    onLeft(workspace.id);
  }, [onLeft, workspace.id]);

  const {
    status,
    members,
    errorMessage,
    leaving,
    leaveError,
    pendingIds,
    rowErrors,
    reload,
    changeRole,
    remove,
    leave,
  } = useMembers(workspace.id, handleLeft);

  const canManage = canManageWorkspace(workspace.role);
  const invites = useInvites(workspace.id, canManage);
  const inviteByEmail = invites.invite;

  // Existing accounts join at once (refresh the member list); everyone else
  // becomes a pending invite with a shareable link (shown by PendingInvites).
  const handleInvite = React.useCallback(
    async (email: string, role: AssignableWorkspaceRole): Promise<boolean> => {
      const outcome = await inviteByEmail(email, role);
      if (outcome?.kind === "member") reload();
      return outcome !== null;
    },
    [inviteByEmail, reload],
  );

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4 space-y-0">
        <div className="min-w-0">
          <CardTitle className="flex items-center gap-2">
            <Users className="size-5 text-primary" aria-hidden />
            <span className="truncate">{workspace.name}</span>
          </CardTitle>
          <div className="mt-2 flex items-center gap-2">
            <span className="text-sm text-muted-foreground">Your role:</span>
            <Badge variant={roleBadgeVariant(workspace.role)}>
              {roleLabel(workspace.role)}
            </Badge>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={reload}
            disabled={status === "loading"}
          >
            <RefreshCw
              className={
                status === "loading" ? "size-4 animate-spin" : "size-4"
              }
              aria-hidden
            />
            Refresh
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="text-muted-foreground hover:text-destructive"
            onClick={() => void leave()}
            disabled={leaving}
          >
            <LogOut className="size-4" aria-hidden />
            {leaving ? "Leaving…" : "Leave"}
          </Button>
        </div>
      </CardHeader>

      <CardContent className="space-y-6">
        {leaveError && (
          <p className="text-sm text-destructive" role="alert">
            {leaveError}
          </p>
        )}

        <WorkspaceCredits workspaceId={workspace.id} canManage={canManage} />

        {canManage && <BuyTeamCredits workspaceId={workspace.id} />}

        {canManage && (
          <div className="rounded-lg border border-border bg-secondary/30 p-4">
            <InviteMemberForm
              inviting={invites.inviting}
              inviteError={invites.inviteError}
              onInvite={handleInvite}
            />
          </div>
        )}

        {canManage && <PendingInvites workspaceName={workspace.name} invites={invites} />}

        <div>
          <h3 className="mb-2 text-sm font-medium text-muted-foreground">
            Members
          </h3>
          <MemberList
            status={status}
            members={members}
            errorMessage={errorMessage}
            currentUserId={currentUserId}
            canManage={canManage}
            pendingIds={pendingIds}
            rowErrors={rowErrors}
            onChangeRole={changeRole}
            onRemove={remove}
            onRetry={reload}
          />
        </div>
      </CardContent>
    </Card>
  );
}
