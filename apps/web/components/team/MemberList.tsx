"use client";

import * as React from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";
import type { Member, WorkspaceRole } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { MemberRow } from "@/components/team/MemberRow";
import type { MembersStatus } from "@/components/team/use-members";

export interface MemberListProps {
  status: MembersStatus;
  members: readonly Member[];
  errorMessage: string;
  /** Signed-in caller's user id, to flag their own row. */
  currentUserId: string | null;
  canManage: boolean;
  pendingIds: ReadonlySet<string>;
  rowErrors: Readonly<Record<string, string>>;
  onChangeRole: (userId: string, role: WorkspaceRole) => void;
  onRemove: (userId: string) => void;
  onRetry: () => void;
}

/**
 * Member list across load/error/ready states. Delegates each row (and its
 * role-aware controls) to {@link MemberRow}. Purely presentational.
 */
export function MemberList({
  status,
  members,
  errorMessage,
  currentUserId,
  canManage,
  pendingIds,
  rowErrors,
  onChangeRole,
  onRemove,
  onRetry,
}: Readonly<MemberListProps>) {
  if (status === "loading") {
    return (
      <div className="space-y-2">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-12 w-full rounded-md" />
        ))}
      </div>
    );
  }

  if (status === "error") {
    return (
      <Card className="border-destructive/40 bg-destructive/5">
        <CardContent className="flex items-start gap-3 p-4">
          <AlertTriangle
            className="mt-0.5 size-5 shrink-0 text-destructive"
            aria-hidden
          />
          <div className="flex-1">
            <p className="text-sm text-muted-foreground">{errorMessage}</p>
            <Button
              variant="outline"
              size="sm"
              className="mt-2"
              onClick={onRetry}
            >
              <RefreshCw className="size-4" aria-hidden /> Try again
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (members.length === 0) {
    return (
      <p className="py-6 text-center text-sm text-muted-foreground">
        No members yet.
      </p>
    );
  }

  return (
    <ul>
      {members.map((member) => (
        <MemberRow
          key={member.user_id}
          member={member}
          isSelf={member.user_id === currentUserId}
          canManage={canManage}
          pending={pendingIds.has(member.user_id)}
          rowError={rowErrors[member.user_id]}
          onChangeRole={onChangeRole}
          onRemove={onRemove}
        />
      ))}
    </ul>
  );
}
