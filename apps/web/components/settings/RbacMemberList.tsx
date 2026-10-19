"use client";

import * as React from "react";
import { RefreshCw } from "lucide-react";
import type { Member, WorkspaceRole } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { RbacMemberRow } from "@/components/settings/RbacMemberRow";
import type { RbacMembersStatus } from "@/components/settings/use-rbac-members";

export interface RbacMemberListProps {
  status: RbacMembersStatus;
  members: readonly Member[];
  errorMessage: string;
  /** Signed-in caller's user id, to flag their own row. */
  currentUserId: string | null;
  /** May the caller manage members? */
  canManage: boolean;
  /** The caller's own numeric rank. */
  actorRank: number;
  /** Count of owners, for the last-owner demotion guard. */
  ownerCount: number;
  pendingIds: ReadonlySet<string>;
  rowErrors: Readonly<Record<string, string>>;
  onChangeRole: (userId: string, role: WorkspaceRole) => void;
  onRetry: () => void;
}

/** The workspace roster with role-aware controls, plus loading/empty/error states. */
export function RbacMemberList({
  status,
  members,
  errorMessage,
  currentUserId,
  canManage,
  actorRank,
  ownerCount,
  pendingIds,
  rowErrors,
  onChangeRole,
  onRetry,
}: Readonly<RbacMemberListProps>) {
  if (status === "loading") {
    return (
      <ul className="space-y-3" aria-busy>
        {[0, 1, 2].map((i) => (
          <li key={i} className="flex items-center justify-between py-2">
            <Skeleton className="h-4 w-48" />
            <Skeleton className="h-8 w-40" />
          </li>
        ))}
      </ul>
    );
  }

  if (status === "error") {
    return (
      <div className="flex flex-col items-start gap-3 rounded-lg border border-border p-4">
        <p className="text-sm text-destructive" role="alert">
          {errorMessage}
        </p>
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RefreshCw className="size-4" aria-hidden />
          Try again
        </Button>
      </div>
    );
  }

  if (members.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
        No members yet.
      </p>
    );
  }

  return (
    <ul className="rounded-lg border border-border px-3">
      {members.map((member) => (
        <RbacMemberRow
          key={member.user_id}
          member={member}
          isSelf={member.user_id === currentUserId}
          canManage={canManage}
          actorRank={actorRank}
          isLastOwner={ownerCount <= 1}
          pending={pendingIds.has(member.user_id)}
          rowError={rowErrors[member.user_id]}
          onChangeRole={onChangeRole}
        />
      ))}
    </ul>
  );
}
