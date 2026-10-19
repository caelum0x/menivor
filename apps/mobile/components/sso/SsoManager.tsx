/**
 * Enterprise SSO manager. Lists the caller's workspaces and, on selecting one,
 * opens the read-mostly SSO status view for it (connection status + enable toggle
 * + security-policy summary).
 *
 * This is the mobile status surface for the Epic 2 Identity & SSO layer. Every
 * read/write is authorised + tenant-scoped server-side (RBAC `workspace.settings`);
 * the client only mirrors what the API returns. No secrets live here — auth flows
 * through the shared api client as `x-api-key`, and no certificate is ever entered
 * on mobile.
 */

import { useCallback, useMemo, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { listMyWorkspaces } from "@/lib/api";
import type { Workspace } from "@/lib/types";

import { Section, SectionState } from "@/components/me/Section";
import { colors } from "@/components/me/theme";
import { useResource } from "@/components/me/use-resource";
import { WorkspaceCard } from "@/components/team/WorkspaceCard";

import { SsoStatusView } from "./SsoStatusView";

interface SsoManagerProps {
  token: string | undefined;
}

export function SsoManager({ token }: SsoManagerProps) {
  const workspacesFetcher = useCallback(
    () => listMyWorkspaces({ token }),
    [token],
  );
  const { status, data, error, reload } =
    useResource<Workspace[]>(workspacesFetcher);

  const [selectedId, setSelectedId] = useState<string | null>(null);

  const selected = useMemo(
    () => (data ?? []).find((w) => w.id === selectedId) ?? null,
    [data, selectedId],
  );

  const workspaces = data ?? [];

  if (selected) {
    return (
      <SsoStatusView
        workspace={selected}
        token={token}
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
              No workspaces yet. Create one on the Team screen to configure
              Enterprise SSO.
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
