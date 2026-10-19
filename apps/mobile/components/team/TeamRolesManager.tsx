/**
 * Team Roles manager. Lists the caller's workspaces and, on selecting one, opens
 * the ENTERPRISE roles view for it (effective access, member roster + roles, and
 * — for admins/owners — inline role editing and the audit trail).
 *
 * This is the read + govern surface for the Enterprise RBAC layer; it never
 * touches per-user job/credit ownership. The caller's id (GET /me) is loaded
 * once so their own roster row can be detected + locked. Auth flows through the
 * shared api client as `x-api-key`; no secrets live here.
 */

import { useCallback, useMemo, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { listMyWorkspaces, me as fetchMe } from "@/lib/api";
import type { Me, Workspace } from "@/lib/types";

import { Section, SectionState } from "@/components/me/Section";
import { colors } from "@/components/me/theme";
import { useResource } from "@/components/me/use-resource";

import { EnterpriseMembersView } from "./EnterpriseMembersView";
import { WorkspaceCard } from "./WorkspaceCard";

interface TeamRolesManagerProps {
  token: string | undefined;
}

export function TeamRolesManager({ token }: TeamRolesManagerProps) {
  const workspacesFetcher = useCallback(
    () => listMyWorkspaces({ token }),
    [token],
  );
  const { status, data, error, reload } =
    useResource<Workspace[]>(workspacesFetcher);

  const meFetcher = useCallback(() => fetchMe({ token }), [token]);
  const { data: meData } = useResource<Me>(meFetcher);
  const currentUserId = meData?.user_id;

  const [selectedId, setSelectedId] = useState<string | null>(null);

  const selected = useMemo(
    () => (data ?? []).find((w) => w.id === selectedId) ?? null,
    [data, selectedId],
  );

  const workspaces = data ?? [];

  if (selected) {
    return (
      <EnterpriseMembersView
        workspace={selected}
        token={token}
        currentUserId={currentUserId}
        onBack={() => setSelectedId(null)}
      />
    );
  }

  return (
    <View style={styles.container}>
      <Section title="WORKSPACES">
        <SectionState status={status} error={error} onRetry={reload}>
          {workspaces.length === 0 ? (
            <Text style={styles.empty}>
              No workspaces yet. Create one on the Team screen to manage roles
              and permissions.
            </Text>
          ) : (
            <View style={styles.list}>
              {workspaces.map((workspace) => (
                <WorkspaceCard
                  key={workspace.id}
                  workspace={workspace}
                  onPress={(w) => setSelectedId(w.id)}
                />
              ))}
            </View>
          )}
        </SectionState>
      </Section>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { gap: 4 },
  list: { gap: 10 },
  empty: {
    color: colors.muted,
    fontSize: 13,
    lineHeight: 18,
    paddingVertical: 8,
  },
});
