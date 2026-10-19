"use client";

import * as React from "react";
import { Loader2, UserMinus } from "lucide-react";
import {
  ASSIGNABLE_WORKSPACE_ROLES,
  type AssignableWorkspaceRole,
  type Member,
  type WorkspaceRole,
} from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { roleBadgeVariant, roleLabel } from "@/components/team/roles";

export interface MemberRowProps {
  member: Member;
  /** Is this row the signed-in caller? */
  isSelf: boolean;
  /** May the caller manage members (owner/admin)? */
  canManage: boolean;
  /** True while this row's role change / removal is in flight. */
  pending: boolean;
  /** Per-row error (role change / removal), if any. */
  rowError?: string;
  onChangeRole: (userId: string, role: WorkspaceRole) => void;
  onRemove: (userId: string) => void;
}

/**
 * One member row: identity + role, with role-change and remove controls shown
 * only when the caller can manage AND the target is neither the caller nor an
 * owner (owners are not demoted/removed through this UI). Purely presentational.
 */
export function MemberRow({
  member,
  isSelf,
  canManage,
  pending,
  rowError,
  onChangeRole,
  onRemove,
}: Readonly<MemberRowProps>) {
  const isOwner = member.role === "owner";
  // Owners and the caller's own row are never mutated here.
  const showControls = canManage && !isSelf && !isOwner;
  const displayName = member.name?.trim() || member.email;

  return (
    <li className="flex flex-col gap-2 border-b border-border px-1 py-3 last:border-b-0 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="truncate font-medium">{displayName}</span>
          {isSelf && (
            <Badge variant="outline" className="shrink-0">
              You
            </Badge>
          )}
        </div>
        {member.name?.trim() && (
          <span className="block truncate text-sm text-muted-foreground">
            {member.email}
          </span>
        )}
      </div>

      <div className="flex items-center gap-2">
        {showControls ? (
          <>
            <Select
              aria-label={`Role for ${displayName}`}
              className="h-8 w-32 text-sm"
              value={
                (ASSIGNABLE_WORKSPACE_ROLES as readonly string[]).includes(
                  member.role,
                )
                  ? member.role
                  : "member"
              }
              disabled={pending}
              onChange={(e) =>
                onChangeRole(
                  member.user_id,
                  e.target.value as AssignableWorkspaceRole,
                )
              }
            >
              {ASSIGNABLE_WORKSPACE_ROLES.map((r) => (
                <option key={r} value={r}>
                  {roleLabel(r)}
                </option>
              ))}
            </Select>
            <Button
              variant="ghost"
              size="icon"
              className="size-8 text-muted-foreground hover:text-destructive"
              aria-label={`Remove ${displayName}`}
              disabled={pending}
              onClick={() => onRemove(member.user_id)}
            >
              {pending ? (
                <Loader2 className="size-4 animate-spin" aria-hidden />
              ) : (
                <UserMinus className="size-4" aria-hidden />
              )}
            </Button>
          </>
        ) : (
          <Badge variant={roleBadgeVariant(member.role)}>
            {roleLabel(member.role)}
          </Badge>
        )}
      </div>

      {rowError && (
        <p className="w-full text-sm text-destructive sm:text-right" role="alert">
          {rowError}
        </p>
      )}
    </li>
  );
}
