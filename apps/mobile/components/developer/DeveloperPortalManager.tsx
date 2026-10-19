/**
 * The Developer screen's top-level manager (Enterprise API Platform, Epic 4).
 *
 * A read-mostly integration surface: it shows the caller-scoped portal summary
 * (API keys + this month's usage + webhook + workspace counts + integration
 * links), then lists the caller's workspaces. Selecting one opens that
 * workspace's webhook subscriptions (view + create + test + deliveries + revoke,
 * owner/admin only).
 *
 * Each block owns its own fetch + loading/error state so a failure in one never
 * blanks the others. Every read/write is authorised + tenant-scoped server-side
 * (RBAC `workspace.settings` for the webhook management routes); the client only
 * mirrors what the API returns. No secrets live here — auth flows through the
 * shared `x-api-key` token, and a subscription's signing secret is shown exactly
 * once at create and never again.
 */

import { useCallback, useMemo, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { listMyWorkspaces } from "@/lib/api";
import {
  getDeveloperPortal,
  WEBHOOK_EVENT_TYPES,
  type DeveloperPortal,
} from "@/lib/developer";
import type { Workspace } from "@/lib/types";

import { Section, SectionState } from "@/components/me/Section";
import { colors } from "@/components/me/theme";
import { useResource } from "@/components/me/use-resource";
import { WorkspaceCard } from "@/components/team/WorkspaceCard";

import { PortalSummary } from "./PortalSummary";
import { WorkspaceWebhooks } from "./WorkspaceWebhooks";

interface DeveloperPortalManagerProps {
  token: string | undefined;
  /**
   * Show the API-platform footprint summary above the webhook list. The
   * Developer & API Keys hub already renders that overview, so the webhooks
   * screen it links to turns this off.
   */
  showSummary?: boolean;
}

export function DeveloperPortalManager({
  token,
  showSummary = true,
}: DeveloperPortalManagerProps) {
  const portalFetcher = useCallback(
    () => getDeveloperPortal({ token }),
    [token],
  );
  const {
    status: portalStatus,
    data: portal,
    error: portalError,
    reload: reloadPortal,
  } = useResource<DeveloperPortal>(portalFetcher);

  const workspacesFetcher = useCallback(
    () => listMyWorkspaces({ token }),
    [token],
  );
  const {
    status: wsStatus,
    data: wsData,
    error: wsError,
    reload: reloadWorkspaces,
  } = useResource<Workspace[]>(workspacesFetcher);

  const [selectedId, setSelectedId] = useState<string | null>(null);

  const workspaces = useMemo(() => wsData ?? [], [wsData]);
  const selected = useMemo(
    () => workspaces.find((w) => w.id === selectedId) ?? null,
    [workspaces, selectedId],
  );

  // The supported event catalog — prefer the API's list, fall back to the const.
  const eventTypes = useMemo(
    () =>
      portal?.webhook_event_types && portal.webhook_event_types.length > 0
        ? portal.webhook_event_types
        : [...WEBHOOK_EVENT_TYPES],
    [portal?.webhook_event_types],
  );

  if (selected) {
    return (
      <WorkspaceWebhooks
        workspace={selected}
        token={token}
        eventTypes={eventTypes}
        onBack={() => setSelectedId(null)}
      />
    );
  }

  return (
    <View style={styles.container}>
      {showSummary ? (
        <Section title="YOUR API PLATFORM">
          <SectionState
            status={portalStatus}
            error={portalError}
            onRetry={reloadPortal}
          >
            {portal ? <PortalSummary portal={portal} /> : null}
          </SectionState>
        </Section>
      ) : null}

      <Section title="WEBHOOKS BY WORKSPACE">
        <SectionState
          status={wsStatus}
          error={wsError}
          onRetry={reloadWorkspaces}
        >
          {workspaces.length === 0 ? (
            <Text style={styles.empty}>
              No workspaces yet. Create one in Team & Workspaces to subscribe to
              webhook events.
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
