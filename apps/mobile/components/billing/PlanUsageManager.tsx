/**
 * ENTERPRISE Plan & Usage manager (Epic 3 Billing Platform). Lists the caller's
 * workspaces and, on selecting one, opens its Plan & Usage detail (current plan,
 * plan entitlements, this period's usage vs limit, and — for billing managers —
 * an upgrade CTA that opens a Stripe checkout).
 *
 * Every read/write is authorised + tenant-scoped server-side: entitlements and
 * usage are workspace-membership reads; starting a subscription is gated on
 * `billing.manage`. The client only mirrors what the API returns for the ONE
 * selected workspace — a caller can never see another tenant's plan or usage. No
 * secrets live here; auth flows through the shared api client as `x-api-key`.
 */

import { useCallback, useMemo, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { listMyWorkspaces } from "@/lib/api";
import type { Workspace } from "@/lib/types";

import { PlanUsageView } from "@/components/billing/PlanUsageView";
import { Section, SectionState } from "@/components/me/Section";
import { colors } from "@/components/me/theme";
import { useResource } from "@/components/me/use-resource";
import { WorkspaceCard } from "@/components/team/WorkspaceCard";

interface PlanUsageManagerProps {
  token: string | undefined;
}

export function PlanUsageManager({ token }: PlanUsageManagerProps) {
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
      <PlanUsageView
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
              No workspaces yet. Create one in Team & Workspaces to see its plan and
              usage.
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
