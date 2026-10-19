/**
 * Members view for a single workspace. Lists members (GET
 * /workspaces/{id}/members), and — for owners/admins — invites by email (POST),
 * changes roles (PATCH) and removes members (DELETE), each with optimistic list
 * updates and rollback on failure. Every caller can leave the workspace (POST
 * /workspaces/{id}/leave). Role-aware: management controls only render for
 * owners/admins, and you leave (never self-remove) your own membership.
 *
 * The auth token flows through the shared api client as `x-api-key`; no secrets
 * live here. This view owns its own loading + error state.
 */

import { useCallback, useState } from "react";
import { Alert, Pressable, StyleSheet, Text, View } from "react-native";
import { Icon } from "@/components/ui/Icon";

import {
  ApiError,
  inviteMember,
  leaveWorkspace,
  listMembers,
  removeMember,
  setMemberRole,
} from "@/lib/api";
import type {
  InviteMemberRequest,
  Workspace,
  WorkspaceMember,
  WorkspaceRole,
} from "@/lib/types";

import { describeError } from "@/components/me/errors";
import { Section, SectionState } from "@/components/me/Section";
import { colors } from "@/components/me/theme";
import { useResource } from "@/components/me/use-resource";

import {
  createWorkspaceInvite,
  pendingInviteFromResponse,
  type WorkspaceInvite,
} from "@/lib/invites";

import { BuyTeamCreditsButton } from "./BuyTeamCreditsButton";
import { PendingInvitesSection, shareInviteLink } from "./PendingInvitesSection";
import { InviteMemberForm } from "./InviteMemberForm";
import { MemberRow } from "./MemberRow";
import { PermissionsView } from "./PermissionsView";
import { WorkspaceCreditsSection } from "./WorkspaceCreditsSection";
import { canManageMembers } from "./roles";

interface MembersViewProps {
  workspace: Workspace;
  token: string | undefined;
  /** Current user's id, used to detect the caller's own membership row. */
  currentUserId: string | undefined;
  /** Called after the caller leaves this workspace (parent drops + navigates). */
  onLeft: (workspaceId: string) => void;
  /** Back to the workspaces list. */
  onBack: () => void;
}

export function MembersView({
  workspace,
  token,
  currentUserId,
  onLeft,
  onBack,
}: MembersViewProps) {
  const fetcher = useCallback(
    () => listMembers(workspace.id, { token }),
    [workspace.id, token],
  );
  const { status, data, error, reload, setData } =
    useResource<WorkspaceMember[]>(fetcher);

  const members = data ?? [];
  const canManage = canManageMembers(workspace.my_role);

  const [busyMemberId, setBusyMemberId] = useState<string | null>(null);
  const [leaving, setLeaving] = useState(false);
  const [createdInvites, setCreatedInvites] = useState<WorkspaceInvite[]>([]);

  const isSelf = useCallback(
    (member: WorkspaceMember): boolean =>
      member.is_self === true ||
      (!!currentUserId && member.user_id === currentUserId),
    [currentUserId],
  );

  const onInvite = useCallback(
    async (body: InviteMemberRequest) => {
      const announce = (invite: WorkspaceInvite) => {
        setCreatedInvites((prev) => [invite, ...prev.filter((i) => i.id !== invite.id)]);
        Alert.alert(
          "Invite link created",
          `${invite.email} doesn't have a Menivor account yet. Share the join link with them; it adds them to ${workspace.name} once they sign up.`,
          [
            { text: "Later", style: "cancel" },
            { text: "Share link", onPress: () => shareInviteLink(invite, workspace.name) },
          ],
        );
      };
      try {
        const created = await inviteMember(workspace.id, body, { token });
        // No account yet: the API answers 200 with a pending invite + link.
        const pending = pendingInviteFromResponse(created);
        if (pending) {
          announce(pending);
          return;
        }
        // Prepend the new member; the backend list is stable regardless.
        setData((prev) => [created, ...(prev ?? [])]);
      } catch (err) {
        // Older API builds reject unknown emails with 404: fall back to an
        // explicit pending invite with a shareable accept link.
        if (!(err instanceof ApiError) || err.status !== 404) throw err;
        announce(await createWorkspaceInvite(workspace.id, body, { token }));
      }
    },
    [workspace.id, workspace.name, token, setData],
  );

  const doSetRole = useCallback(
    async (member: WorkspaceMember, role: WorkspaceRole) => {
      if (member.role === role) return;
      const previous = data;
      setBusyMemberId(member.id);
      // Optimistically apply the new role, then confirm with the backend.
      setData((prev) =>
        (prev ?? []).map((m) => (m.id === member.id ? { ...m, role } : m)),
      );
      try {
        const updated = await setMemberRole(workspace.id, member.id, role, {
          token,
        });
        setData((prev) =>
          (prev ?? []).map((m) => (m.id === member.id ? updated : m)),
        );
      } catch (err) {
        setData(() => previous);
        Alert.alert("Couldn't change role", describeError(err));
      } finally {
        setBusyMemberId(null);
      }
    },
    [workspace.id, token, data, setData],
  );

  const doRemove = useCallback(
    async (member: WorkspaceMember) => {
      const previous = data;
      setBusyMemberId(member.id);
      // Optimistically drop the row; roll back on failure.
      setData((prev) => (prev ?? []).filter((m) => m.id !== member.id));
      try {
        await removeMember(workspace.id, member.id, { token });
      } catch (err) {
        setData(() => previous);
        Alert.alert("Couldn't remove member", describeError(err));
      } finally {
        setBusyMemberId(null);
      }
    },
    [workspace.id, token, data, setData],
  );

  const onRemove = useCallback(
    (member: WorkspaceMember) => {
      Alert.alert(
        "Remove member?",
        `${member.email} will lose access to ${workspace.name}. You can invite them again later.`,
        [
          { text: "Keep", style: "cancel" },
          {
            text: "Remove",
            style: "destructive",
            onPress: () => void doRemove(member),
          },
        ],
      );
    },
    [doRemove, workspace.name],
  );

  const doLeave = useCallback(async () => {
    setLeaving(true);
    try {
      await leaveWorkspace(workspace.id, { token });
      onLeft(workspace.id);
    } catch (err) {
      Alert.alert("Couldn't leave", describeError(err));
    } finally {
      setLeaving(false);
    }
  }, [workspace.id, token, onLeft]);

  const onLeave = useCallback(() => {
    Alert.alert(
      "Leave workspace?",
      `You'll lose access to ${workspace.name}. An owner can invite you back.`,
      [
        { text: "Stay", style: "cancel" },
        {
          text: "Leave",
          style: "destructive",
          onPress: () => void doLeave(),
        },
      ],
    );
  }, [doLeave, workspace.name]);

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

      <PermissionsView workspaceId={workspace.id} token={token} />

      <WorkspaceCreditsSection
        workspaceId={workspace.id}
        token={token}
        canGrant={canManage}
      />

      {canManage ? (
        <BuyTeamCreditsButton workspaceId={workspace.id} token={token} />
      ) : null}

      {canManage ? (
        <Section title="INVITE">
          <InviteMemberForm onInvite={onInvite} />
        </Section>
      ) : null}

      {canManage ? (
        <PendingInvitesSection
          workspaceId={workspace.id}
          workspaceName={workspace.name}
          token={token}
          created={createdInvites}
        />
      ) : null}

      <Section title="MEMBERS">
        <SectionState status={status} error={error} onRetry={reload}>
          {members.length === 0 ? (
            <Text style={styles.empty}>No members yet.</Text>
          ) : (
            <View style={styles.list}>
              {members.map((member) => (
                <MemberRow
                  key={member.id}
                  member={member}
                  isSelf={isSelf(member)}
                  canManage={canManage}
                  busy={busyMemberId === member.id}
                  onSetRole={doSetRole}
                  onRemove={onRemove}
                />
              ))}
            </View>
          )}
        </SectionState>
      </Section>

      <Pressable
        style={[styles.leave, leaving && styles.disabled]}
        onPress={onLeave}
        disabled={leaving}
        accessibilityRole="button"
        accessibilityLabel="Leave workspace"
        accessibilityState={{ disabled: leaving }}
      >
        <Text style={styles.leaveText}>
          {leaving ? "Leaving…" : "Leave workspace"}
        </Text>
      </Pressable>
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
  leave: {
    marginTop: 4,
    borderColor: colors.error,
    borderWidth: 1,
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: "center",
  },
  disabled: { opacity: 0.5 },
  leaveText: { color: colors.error, fontSize: 15, fontWeight: "700" },
});
