/**
 * WORKSPACE DATA-RETENTION POLICY — the Team/workspace admin surface for the
 * GDPR data-retention window that, until now, was read/edit-only on the web.
 * (NOTE: this is WORKSPACE retention — how long a tenant keeps jobs/assets — and
 * is unrelated to the audience-retention labs at `/retention-lab`.)
 *
 * Lists the caller's workspaces with pull-to-refresh, then opens a per-workspace
 * editor (GET/PUT /me/workspaces/{id}/retention) with two independent windows,
 * client-side validation, a confirmation step, and read-only fallback for
 * viewers. Every authorization decision is enforced server-side (RBAC
 * `workspace.settings`); this screen only mirrors it. Auth flows through the
 * shared api client as `x-api-key`; no secrets live here.
 *
 * Nav manifest entry:
 *   { route: "/workspaces/retention", title: "Data Retention",
 *     group: "Team / Workspace admin", icon: "clock" }
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { Stack } from "expo-router";

import { listMyWorkspaces } from "@/lib/api";
import type { Workspace } from "@/lib/types";
import { useSession } from "@/src/shared/auth";

import { Section, SectionState } from "@/components/me/Section";
import { colors } from "@/components/me/theme";
import { useResource } from "@/components/me/use-resource";
import { RetentionPolicyEditor } from "@/components/team/RetentionPolicyEditor";
import { WorkspaceCard } from "@/components/team/WorkspaceCard";

export default function WorkspaceRetentionScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  const fetcher = useCallback(() => listMyWorkspaces({ token }), [token]);
  const { status, data, error, reload } = useResource<Workspace[]>(fetcher);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const workspaces = data ?? [];
  const selected = useMemo(
    () => workspaces.find((w) => w.id === selectedId) ?? null,
    [workspaces, selectedId],
  );

  const onRefresh = useCallback(() => {
    setRefreshing(true);
    reload();
  }, [reload]);

  useEffect(() => {
    if (status !== "loading") setRefreshing(false);
  }, [status]);

  return (
    <>
      <Stack.Screen
        options={{ title: "Data Retention", presentation: "card" }}
      />
      <ScrollView
        style={styles.container}
        contentContainerStyle={styles.content}
        keyboardShouldPersistTaps="handled"
        refreshControl={
          selected ? undefined : (
            <RefreshControl
              refreshing={refreshing}
              onRefresh={onRefresh}
              tintColor={colors.accent}
            />
          )
        }
      >
        {selected ? (
          <RetentionPolicyEditor
            workspace={selected}
            token={token}
            onBack={() => setSelectedId(null)}
          />
        ) : (
          <Section title="WORKSPACES">
            <SectionState status={status} error={error} onRetry={reload}>
              {workspaces.length === 0 ? (
                <View style={styles.emptyBox}>
                  <Text style={styles.emptyTitle}>No workspaces</Text>
                  <Text style={styles.emptyBody}>
                    Create a workspace on the Team screen to configure its
                    data-retention policy.
                  </Text>
                </View>
              ) : (
                <View style={styles.list}>
                  <Text style={styles.hint}>
                    Choose a workspace to view or edit how long its jobs and
                    assets are kept before the periodic anonymizing sweep.
                  </Text>
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
        )}
      </ScrollView>
    </>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 20, paddingTop: 24, paddingBottom: 48 },
  list: { gap: 12 },
  hint: {
    color: colors.textSecondary,
    fontSize: 13,
    lineHeight: 18,
    marginBottom: 2,
  },
  emptyBox: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 20,
    gap: 8,
  },
  emptyTitle: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  emptyBody: { color: colors.muted, fontSize: 13, lineHeight: 18 },
});
