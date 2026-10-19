import type { BadgeVariant } from "@/components/ui/badge";
import { ENTERPRISE_ROLES, type WorkspaceRole } from "@/lib/types";

/** Human-readable label for an Enterprise role, with a safe fallback. */
export function roleLabel(role: WorkspaceRole | null | undefined): string {
  switch (role) {
    case "owner":
      return "Owner";
    case "admin":
      return "Admin";
    case "editor":
      return "Editor";
    case "viewer":
      return "Viewer";
    case "billing":
      return "Billing";
    case "member":
      return "Member";
    default:
      return role ? role.charAt(0).toUpperCase() + role.slice(1) : "—";
  }
}

/** Short description of what each role can do, shown in the role picker. */
export function roleDescription(role: WorkspaceRole): string {
  switch (role) {
    case "owner":
      return "Full control incl. billing";
    case "admin":
      return "Manage members, settings, audit";
    case "editor":
      return "Create & read reels";
    case "billing":
      return "Manage billing";
    case "viewer":
      return "Read-only";
    default:
      return "";
  }
}

/** Badge styling per role so the roster reads at a glance. */
export function roleBadgeVariant(role: WorkspaceRole | null | undefined): BadgeVariant {
  switch (role) {
    case "owner":
      return "success";
    case "admin":
      return "default";
    case "billing":
      return "outline";
    case "editor":
      return "secondary";
    default:
      return "secondary";
  }
}

/**
 * The Enterprise roles a manager may assign, restricted to those AT OR BELOW the
 * caller's own rank (mirrors the server's "cannot grant above your own" guard).
 * The server independently enforces this — the filter only avoids offering an
 * option the API would reject with a 403.
 */
export function assignableRolesFor(
  actorRank: number,
): readonly WorkspaceRole[] {
  return ENTERPRISE_ROLES.filter((role) => roleRankOf(role) <= actorRank);
}

/** Local rank lookup (kept in sync with `ROLE_RANK` in lib/types). */
function roleRankOf(role: WorkspaceRole): number {
  switch (role) {
    case "owner":
      return 4;
    case "admin":
      return 3;
    case "editor":
    case "billing":
      return 2;
    case "viewer":
      return 1;
    default:
      return 0;
  }
}
