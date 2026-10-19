/**
 * Pending invites for people who don't have a Menivor account yet. Lists them
 * (GET /workspaces/{id}/invites), lets an owner/admin share the accept link
 * again (native share sheet) or revoke it (DELETE). New pending invites created
 * by the invite form are pushed in through `extra` so they show immediately.
 */

import { useCallback, useEffect, useState } from "react";
import { Alert, Pressable, Share, StyleSheet, Text, View } from "react-native";

import { Icon } from "@/components/ui/Icon";
import { describeError } from "@/components/me/errors";
import { Section, SectionState } from "@/components/me/Section";
import { colors } from "@/components/me/theme";
import { useResource } from "@/components/me/use-resource";
import {
  listWorkspaceInvites,
  revokeWorkspaceInvite,
  type WorkspaceInvite,
} from "@/lib/invites";

import { roleLabel } from "./roles";

interface PendingInvitesSectionProps {
  workspaceId: string;
  workspaceName: string;
  token: string | undefined;
  /** Invites created in this session, merged in ahead of the server list. */
  created: readonly WorkspaceInvite[];
}

export function shareInviteLink(invite: WorkspaceInvite, workspaceName: string): void {
  if (!invite.acceptUrl) {
    Alert.alert("No link", "This invite has no shareable link. Revoke it and invite again.");
    return;
  }
  void Share.share({
    message: `Join ${workspaceName} on Menivor: ${invite.acceptUrl}`,
    url: invite.acceptUrl,
  });
}

export function PendingInvitesSection({
  workspaceId,
  workspaceName,
  token,
  created,
}: PendingInvitesSectionProps) {
  const fetcher = useCallback(
    () => listWorkspaceInvites(workspaceId, { token }),
    [workspaceId, token],
  );
  const { status, data, error, reload, setData } = useResource<WorkspaceInvite[]>(fetcher);
  const [revokingId, setRevokingId] = useState<string | null>(null);

  // Merge freshly created invites into the list (dedup by id).
  useEffect(() => {
    if (created.length === 0) return;
    setData((prev) => {
      const existing = prev ?? [];
      const fresh = created.filter((c) => !existing.some((e) => e.id === c.id));
      return fresh.length ? [...fresh, ...existing] : existing;
    });
  }, [created, setData]);

  const onRevoke = useCallback(
    (invite: WorkspaceInvite) => {
      Alert.alert("Revoke invite?", `${invite.email}'s link will stop working.`, [
        { text: "Keep", style: "cancel" },
        {
          text: "Revoke",
          style: "destructive",
          onPress: () => {
            setRevokingId(invite.id);
            revokeWorkspaceInvite(workspaceId, invite.id, { token })
              .then(() => setData((prev) => (prev ?? []).filter((i) => i.id !== invite.id)))
              .catch((err) => Alert.alert("Couldn't revoke", describeError(err)))
              .finally(() => setRevokingId(null));
          },
        },
      ]);
    },
    [setData, token, workspaceId],
  );

  const invites = data ?? [];

  return (
    <Section title="PENDING INVITES">
      <SectionState status={status} error={error} onRetry={reload}>
        {invites.length === 0 ? (
          <Text style={styles.empty}>
            No pending invites. Inviting an email without an account creates a shareable join link.
          </Text>
        ) : (
          <View style={styles.list}>
            {invites.map((invite) => (
              <View key={invite.id} style={styles.row}>
                <View style={styles.body}>
                  <Text style={styles.email} numberOfLines={1}>
                    {invite.email}
                  </Text>
                  <Text style={styles.meta}>
                    {roleLabel(invite.role)}
                    {invite.expiresAt
                      ? ` · expires ${new Date(invite.expiresAt).toLocaleDateString()}`
                      : ""}
                  </Text>
                </View>
                <Pressable
                  onPress={() => shareInviteLink(invite, workspaceName)}
                  hitSlop={8}
                  accessibilityRole="button"
                  accessibilityLabel={`Share invite link for ${invite.email}`}
                >
                  <Icon name="share-outline" size={20} color={colors.accent} />
                </Pressable>
                <Pressable
                  onPress={() => onRevoke(invite)}
                  disabled={revokingId === invite.id}
                  hitSlop={8}
                  style={revokingId === invite.id ? styles.disabled : undefined}
                  accessibilityRole="button"
                  accessibilityLabel={`Revoke invite for ${invite.email}`}
                >
                  <Icon name="close-circle-outline" size={20} color={colors.error} />
                </Pressable>
              </View>
            ))}
          </View>
        )}
      </SectionState>
    </Section>
  );
}

const styles = StyleSheet.create({
  list: { gap: 10 },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 14,
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
  },
  body: { flex: 1, gap: 2 },
  email: { color: colors.textPrimary, fontSize: 14, fontWeight: "600" },
  meta: { color: colors.muted, fontSize: 12 },
  empty: { color: colors.muted, fontSize: 13 },
  disabled: { opacity: 0.4 },
});
