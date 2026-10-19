import type { BadgeVariant } from "@/components/ui/badge";
import type { WorkspaceRole } from "@/lib/types";

/** Human-readable label for a role, with a safe fallback for unknown roles. */
export function roleLabel(role: WorkspaceRole): string {
  switch (role) {
    case "owner":
      return "Owner";
    case "admin":
      return "Admin";
    case "member":
      return "Member";
    default:
      // Title-case an unrecognised future role instead of showing it raw.
      return role ? role.charAt(0).toUpperCase() + role.slice(1) : "Member";
  }
}

/** Badge styling per role so the member list reads at a glance. */
export function roleBadgeVariant(role: WorkspaceRole): BadgeVariant {
  switch (role) {
    case "owner":
      return "success";
    case "admin":
      return "default";
    default:
      return "secondary";
  }
}
