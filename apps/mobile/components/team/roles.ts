/**
 * Pure, dependency-free helpers for reasoning about workspace roles on the
 * client. These mirror the server's authorization model for UI affordances
 * only — the backend independently authorizes every mutation, so these helpers
 * never grant access, they only decide what to *show*.
 */

import {
  WORKSPACE_MANAGER_ROLES,
  type WorkspaceRole,
} from "@/lib/types";

/** Human-readable label for a role value (widened `string` tolerated). */
export function roleLabel(role: WorkspaceRole | string): string {
  switch (role) {
    case "owner":
      return "Owner";
    case "admin":
      return "Admin";
    case "member":
      return "Member";
    default:
      return role
        ? role.charAt(0).toUpperCase() + role.slice(1)
        : "Member";
  }
}

/** Short one-line description of what a role can do (for pickers). */
export function roleDescription(role: WorkspaceRole | string): string {
  switch (role) {
    case "owner":
      return "Full control of the workspace and its members.";
    case "admin":
      return "Can invite, remove, and re-role members.";
    case "member":
      return "Can view the workspace and leave.";
    default:
      return "";
  }
}

/**
 * True when a caller with `role` may manage membership (invite, remove, change
 * roles). Owners and admins can; members cannot.
 */
export function canManageMembers(role: WorkspaceRole | string): boolean {
  return (WORKSPACE_MANAGER_ROLES as readonly string[]).includes(role);
}
