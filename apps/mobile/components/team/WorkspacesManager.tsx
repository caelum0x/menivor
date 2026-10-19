/**
 * Team Workspaces manager. Two panes driven by local selection state:
 *
 * 1. Workspaces list (GET /workspaces) + a create form (POST /workspaces).
 * 2. A selected workspace's members view (invite / re-role / remove / leave).
 *
 * This is an additive membership layer — it never touches per-user job/credit
 * ownership. The caller's identity (GET /me) is loaded once to detect the
 * caller's own membership row for role-aware controls; a failure there degrades
 * gracefully (self-detection then relies on the server's `is_self` flag).
 *
 * Auth flows through the shared api client as `x-api-key`; no secrets here.
 */

import { useCallback, useMemo, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { createWorkspace, listMyWorkspaces, me as fetchMe } from "@/lib/api";
import type { CreateWorkspaceRequest, Me, Workspace } from "@/lib/types";

import { Section, SectionState } from "@/components/me/Section";
import { colors } from "@/components/me/theme";
import { useResource } from "@/components/me/use-resource";

import { CreateWorkspaceForm } from "./CreateWorkspaceForm";
import { MembersView } from "./MembersView";
import { WorkspaceCard } from "./WorkspaceCard";

interface WorkspacesManagerProps {
  token: string | undefined;
}

export function WorkspacesManager({ token }: WorkspacesManagerProps) {
  const workspacesFetcher = useCallback(
    () => listMyWorkspaces({ token }),
    [token],
  );
  const { status, data, error, reload, setData } =
    useResource<Workspace[]>(workspacesFetcher);

  const meFetcher = useCallback(() => fetchMe({ token }), [token]);
  const { data: meData } = useResource<Me>(meFetcher);
  const currentUserId = meData?.user_id;

  const workspaces = data ?? [];
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const selected = useMemo(
    () => (data ?? []).find((w) => w.id === selectedId) ?? null,
    [data, selectedId],
  );

  const onCreate = useCallback(
    async (body: CreateWorkspaceRequest) => {
      const created = await createWorkspace(body, { token });
      // Prepend the new workspace (caller is its owner).
      setData((prev) => [created, ...(prev ?? [])]);
    },
    [token, setData],
  );

  const onLeft = useCallback(
    (workspaceId: string) => {
      // Drop the left workspace and return to the list.
      setData((prev) => (prev ?? []).filter((w) => w.id !== workspaceId));
      setSelectedId(null);
    },
    [setData],
  );

  const onBack = useCallback(() => setSelectedId(null), []);

  // Members pane for the selected workspace.
  if (selected) {
    return (
      <MembersView
        workspace={selected}
        token={token}
        currentUserId={currentUserId}
        onLeft={onLeft}
        onBack={onBack}
      />
    );
  }

  // Workspaces list pane.
  return (
    <View style={styles.container}>
      <Section title="NEW WORKSPACE">
        <CreateWorkspaceForm onCreate={onCreate} />
      </Section>

      <Section title="YOUR WORKSPACES">
        <SectionState status={status} error={error} onRetry={reload}>
          {workspaces.length === 0 ? (
            <Text style={styles.empty}>
              No workspaces yet. Create one above to invite teammates and manage
              roles.
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
