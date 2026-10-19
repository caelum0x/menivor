/**
 * One member row in a workspace's members list. Presentation only — all state
 * and handlers are owned by the parent. Role-aware:
 *
 * - Every row shows the member's email + role badge.
 * - When the caller can manage members AND this row is not the caller, inline
 *   role controls (change role) and a Remove action are shown.
 * - The caller's own row is marked "You"; you never remove or re-role yourself
 *   here — use Leave (in the parent) instead.
 */

import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

import type { WorkspaceMember, WorkspaceRole } from "@/lib/types";

import { colors } from "@/components/me/theme";
import { RolePicker } from "./RolePicker";
import { roleLabel } from "./roles";

export interface MemberRowProps {
  member: WorkspaceMember;
  /** True when this row is the calling user. */
  isSelf: boolean;
  /** True when the caller may manage membership (invite/remove/re-role). */
  canManage: boolean;
  /** True while a mutation targeting this row is in flight. */
  busy: boolean;
  onSetRole: (member: WorkspaceMember, role: WorkspaceRole) => void;
  onRemove: (member: WorkspaceMember) => void;
}

export function MemberRow({
  member,
  isSelf,
  canManage,
  busy,
  onSetRole,
  onRemove,
}: Readonly<MemberRowProps>) {
  // Role controls appear only for managers acting on other members.
  const showControls = canManage && !isSelf;

  return (
    <View style={styles.card}>
      <View style={styles.headerRow}>
        <View style={styles.identity}>
          <Text style={styles.email} numberOfLines={1}>
            {member.email}
          </Text>
          {member.name ? (
            <Text style={styles.name} numberOfLines={1}>
              {member.name}
            </Text>
          ) : null}
        </View>
        {isSelf ? <Text style={styles.selfBadge}>You</Text> : null}
      </View>

      {showControls ? (
        <View style={styles.controls}>
          <RolePicker
            selected={
              member.role === "owner" || member.role === "admin"
                ? member.role
                : "member"
            }
            onSelect={(role) => onSetRole(member, role)}
            disabled={busy}
          />
          <Pressable
            style={[styles.remove, busy && styles.disabled]}
            onPress={() => onRemove(member)}
            disabled={busy}
            accessibilityRole="button"
            accessibilityLabel={`Remove ${member.email}`}
            accessibilityState={{ disabled: busy }}
            hitSlop={6}
          >
            {busy ? (
              <ActivityIndicator color={colors.error} />
            ) : (
              <Text style={styles.removeText}>Remove</Text>
            )}
          </Pressable>
        </View>
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
  identity: { flex: 1, gap: 2 },
  email: { color: colors.textPrimary, fontSize: 15, fontWeight: "600" },
  name: { color: colors.muted, fontSize: 12 },
  selfBadge: {
    color: colors.accent,
    fontSize: 12,
    fontWeight: "700",
  },
  roleBadge: {
    color: colors.textSecondary,
    fontSize: 13,
    fontWeight: "700",
  },
  controls: { gap: 12 },
  remove: {
    alignSelf: "flex-start",
    borderColor: colors.error,
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 16,
    paddingVertical: 8,
  },
  disabled: { opacity: 0.5 },
  removeText: { color: colors.error, fontSize: 14, fontWeight: "700" },
});
