"use client";

import * as React from "react";
import { Loader2 } from "lucide-react";
import { ENTERPRISE_ROLES, type Member, type WorkspaceRole } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Select } from "@/components/ui/select";
import {
  assignableRolesFor,
  roleBadgeVariant,
  roleLabel,
} from "@/components/settings/roles";

export interface RbacMemberRowProps {
  member: Member;
  /** Is this row the signed-in caller? */
  isSelf: boolean;
  /** May the caller manage members (holds `members.manage`)? */
  canManage: boolean;
  /** The caller's own numeric rank (drives which roles they may grant). */
  actorRank: number;
  /** True while `member.role === "owner"` is the ONLY owner (last-owner guard). */
  isLastOwner: boolean;
  /** True while this row's role change is in flight. */
  pending: boolean;
  /** Per-row error, if any. */
  rowError?: string;
  onChangeRole: (userId: string, role: WorkspaceRole) => void;
}

/**
 * One roster row: identity + Enterprise role. A role dropdown is shown only when
 * the caller can manage members and the target is not the caller. Options are
 * limited to roles at/below the caller's rank; demoting the last owner is
 * disabled in-UI (the server also rejects it with a 409). Purely presentational.
 */
export function RbacMemberRow({
  member,
  isSelf,
  canManage,
  actorRank,
  isLastOwner,
  pending,
  rowError,
  onChangeRole,
}: Readonly<RbacMemberRowProps>) {
  const displayName = member.name?.trim() || member.email;
  const showSelect = canManage && !isSelf;

  // Roles the caller may grant this member. Always include the member's CURRENT
  // role so the select reflects reality even if it's above the caller's rank.
  const options = React.useMemo(() => {
    const allowed = new Set<string>(assignableRolesFor(actorRank));
    allowed.add(member.role);
    return ENTERPRISE_ROLES.filter((r) => allowed.has(r));
  }, [actorRank, member.role]);

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
        {member.name?.trim() && member.email && (
          <span className="block truncate text-sm text-muted-foreground">
            {member.email}
          </span>
        )}
      </div>

      <div className="flex items-center gap-2">
        {pending && (
          <Loader2 className="size-4 animate-spin text-muted-foreground" aria-hidden />
        )}
        {showSelect ? (
          <Select
            aria-label={`Role for ${displayName ?? member.user_id}`}
            className="h-8 w-40 text-sm"
            value={member.role}
            disabled={pending}
            onChange={(e) =>
              onChangeRole(member.user_id, e.target.value as WorkspaceRole)
            }
          >
            {options.map((r) => (
              <option
                key={r}
                value={r}
                // Cannot demote the last owner (server returns 409); disable it.
                disabled={member.role === "owner" && isLastOwner && r !== "owner"}
              >
                {roleLabel(r)}
              </option>
            ))}
          </Select>
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
