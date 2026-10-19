/**
 * The ENTERPRISE roles view for a single workspace. Shows the caller's effective
 * access (role + permissions), the member roster with each member's Enterprise
 * role, and — for admins/owners — inline role editing plus the append-only audit
 * trail.
 *
 * Every decision here is a UI affordance only: the pycasbin enforcer authorizes
 * each mutation server-side (a 403 rolls the optimistic change back). Role
 * changes are keyed by `user_id` (PATCH /me/workspaces/{id}/members/{userId}/
 * role) and gated client-side so a caller can never *offer* a role above their
 * own rank — matching the server's guardrail. TENANT ISOLATION is preserved: the
 * roster + audit only ever reflect this workspace.
 */

import { useCallback, useState } from "react";
import { Alert, Pressable, StyleSheet, Text, View } from "react-native";
import { Icon } from "@/components/ui/Icon";

import { getMyPermissions, listWorkspaceMembers, updateMemberRole } from "@/lib/api";
import {
  canManageMembers,
  canReadAudit,
  roleRank,
  type EnterpriseRole,
  type Permissions,
  type Workspace,
  type WorkspaceMember,
} from "@/lib/types";

import { describeError } from "@/components/me/errors";
import { Section, SectionState } from "@/components/me/Section";
import { colors } from "@/components/me/theme";
import { useResource } from "@/components/me/use-resource";

import { AuditView } from "./AuditView";
import { EnterpriseMemberRow } from "./EnterpriseMemberRow";
import { PermissionsCard } from "./PermissionsCard";

interface EnterpriseMembersViewProps {
  workspace: Workspace;
  token: string | undefined;
  /** Current user's id, used to detect + lock the caller's own roster row. */
  currentUserId: string | undefined;
  /** Back to the workspaces list. */
  onBack: () => void;
}

export function EnterpriseMembersView({
  workspace,
  token,
  currentUserId,
  onBack,
}: EnterpriseMembersViewProps) {
  const membersFetcher = useCallback(
    () => listWorkspaceMembers(workspace.id, { token }),
    [workspace.id, token],
  );
  const { status, data, error, reload, setData } =
    useResource<WorkspaceMember[]>(membersFetcher);

  const permsFetcher = useCallback(
    () => getMyPermissions(workspace.id, { token }),
    [workspace.id, token],
  );
  const { data: perms } = useResource<Permissions>(permsFetcher);

  const members = data ?? [];
  const callerRole = perms?.role ?? null;
  const canManage = canManageMembers(callerRole);
  const showAudit = canReadAudit(callerRole);
  const callerRank = roleRank(callerRole);

  const [busyUserId, setBusyUserId] = useState<string | null>(null);

  const isSelf = useCallback(
    (member: WorkspaceMember): boolean =>
      member.is_self === true ||
      (!!currentUserId && member.user_id === currentUserId),
    [currentUserId],
  );

  const doSetRole = useCallback(
    async (member: WorkspaceMember, role: EnterpriseRole) => {
      if (member.role === role) return;
      const previous = data;
      setBusyUserId(member.user_id);
      // Optimistically apply the new role, then confirm with the backend.
      setData((prev) =>
        (prev ?? []).map((m) =>
          m.user_id === member.user_id ? { ...m, role } : m,
        ),
      );
      try {
        const updated = await updateMemberRole(
          workspace.id,
          member.user_id,
          role,
          { token },
        );
        setData((prev) =>
          (prev ?? []).map((m) =>
            m.user_id === member.user_id ? { ...m, ...updated } : m,
          ),
        );
      } catch (err) {
        setData(() => previous);
        Alert.alert("Couldn't change role", describeError(err));
      } finally {
        setBusyUserId(null);
      }
    },
    [workspace.id, token, data, setData],
  );

  return (
    <View style={styles.container}>
      <Pressable
        style={styles.back}
        onPress={onBack}
        accessibilityRole="button"
        accessibilityLabel="Back to workspaces"
        hitSlop={6}
      >
        <Icon name="chevron-back" style={styles.backText} />
        <Text style={styles.backText}>Workspaces</Text>
      </Pressable>

      <Text style={styles.title}>{workspace.name}</Text>

      {perms ? (
        <Section title="YOUR ACCESS">
          <PermissionsCard permissions={perms} />
        </Section>
      ) : null}

      <Section title="MEMBERS & ROLES">
        <SectionState status={status} error={error} onRetry={reload}>
          {members.length === 0 ? (
            <Text style={styles.empty}>No members yet.</Text>
          ) : (
            <View style={styles.list}>
              {members.map((member) => (
                <EnterpriseMemberRow
                  key={member.user_id}
                  member={member}
                  isSelf={isSelf(member)}
                  canManage={canManage}
                  callerRank={callerRank}
                  busy={busyUserId === member.user_id}
                  onSetRole={doSetRole}
                />
              ))}
            </View>
          )}
        </SectionState>
      </Section>

      {showAudit ? <AuditView workspaceId={workspace.id} token={token} /> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { gap: 8 },
  back: { alignSelf: "flex-start", flexDirection: "row", alignItems: "center", gap: 2, paddingVertical: 4, marginBottom: 4 },
  backText: { color: colors.accent, fontSize: 14, fontWeight: "600" },
  title: {
    color: colors.textPrimary,
    fontSize: 22,
    fontWeight: "800",
    marginBottom: 12,
  },
  list: { gap: 10 },
  empty: {
    color: colors.muted,
    fontSize: 13,
    lineHeight: 18,
    paddingVertical: 8,
  },
});
