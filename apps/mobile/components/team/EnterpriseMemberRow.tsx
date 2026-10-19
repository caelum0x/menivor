/**
 * One member row in the ENTERPRISE roster. Presentation only — all state and
 * handlers are owned by the parent. Role-aware:
 *
 * - Every row shows the member's email + Enterprise role.
 * - When the caller can manage members AND this row is not the caller, an inline
 *   {@link EnterpriseRolePicker} lets them change the role — capped at their own
 *   rank (`callerRank`) so a chip that would out-rank the caller is disabled.
 * - The caller's own row is marked "You" and is never editable here (a caller
 *   changes their own standing by leaving, on the workspace screen).
 *
 * Roles are keyed by `user_id` (the RBAC endpoints' path param), not a
 * membership row id.
 */

import { StyleSheet, Text, View } from "react-native";

import type { EnterpriseRole, WorkspaceMember } from "@/lib/types";

import { colors } from "@/components/me/theme";
import { EnterpriseRolePicker } from "./EnterpriseRolePicker";
import { roleLabel } from "./roles";

export interface EnterpriseMemberRowProps {
  member: WorkspaceMember;
  /** True when this row is the calling user. */
  isSelf: boolean;
  /** True when the caller may change roles (holds `members.manage`). */
  canManage: boolean;
  /** The caller's own rank; roles above it are shown disabled in the picker. */
  callerRank: number;
  /** True while a role change targeting this row is in flight. */
  busy: boolean;
  onSetRole: (member: WorkspaceMember, role: EnterpriseRole) => void;
}

export function EnterpriseMemberRow({
  member,
  isSelf,
  canManage,
  callerRank,
  busy,
  onSetRole,
}: Readonly<EnterpriseMemberRowProps>) {
  const showControls = canManage && !isSelf;

  return (
    <View style={styles.card}>
      <View style={styles.headerRow}>
        <Text style={styles.email} numberOfLines={1}>
          {member.email || member.user_id}
        </Text>
        {isSelf ? <Text style={styles.selfBadge}>You</Text> : null}
      </View>

      {showControls ? (
        <EnterpriseRolePicker
          selected={member.role}
          onSelect={(role) => onSetRole(member, role)}
          disabled={busy}
          maxRank={callerRank}
        />
      ) : (
        <Text style={styles.roleBadge}>{roleLabel(member.role)}</Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    gap: 12,
  },
  headerRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
  },
  email: { color: colors.textPrimary, fontSize: 15, fontWeight: "600", flex: 1 },
  selfBadge: { color: colors.accent, fontSize: 12, fontWeight: "700" },
  roleBadge: { color: colors.textSecondary, fontSize: 13, fontWeight: "700" },
});
