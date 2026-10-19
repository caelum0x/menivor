/**
 * The webhook-subscriptions surface for a single workspace (Enterprise API
 * Platform, Epic 4). Owner/admins (RBAC `workspace.settings`) can view the
 * workspace's subscriptions, create a new one (the HMAC signing secret is shown
 * exactly once), send a signed test event, inspect recent deliveries, and revoke.
 *
 * Every read/write is authorised + tenant-scoped server-side; the reads
 * themselves 403 for a non-admin, so we gate the whole surface on the caller's
 * effective permissions first to render a clear message instead of an error. No
 * secret is ever shown after create, and no secret lives in this component beyond
 * the transient one-time reveal.
 */

import { useCallback, useState } from "react";
import { Alert, Pressable, StyleSheet, Text, View } from "react-native";
import { Icon } from "@/components/ui/Icon";

import { getMyPermissions } from "@/lib/api";
import {
  createWebhookSubscription,
  deleteWebhookSubscription,
  listWebhookSubscriptions,
  testWebhookSubscription,
  type CreatedWebhookSubscription,
  type WebhookSubscription,
} from "@/lib/developer";
import type { Permissions, Workspace } from "@/lib/types";

import { describeError } from "@/components/me/errors";
import { Section, SectionState } from "@/components/me/Section";
import { colors } from "@/components/me/theme";
import { useResource } from "@/components/me/use-resource";

import { RevealedSecretBanner } from "./RevealedSecretBanner";
import { WebhookCreateForm } from "./WebhookCreateForm";
import { WebhookSubscriptionCard } from "./WebhookSubscriptionCard";

interface WorkspaceWebhooksProps {
  workspace: Workspace;
  token: string | undefined;
  /** The supported event catalog (from the portal summary). */
  eventTypes: readonly string[];
  onBack: () => void;
}

export function WorkspaceWebhooks({
  workspace,
  token,
  eventTypes,
  onBack,
}: WorkspaceWebhooksProps) {
  const permsFetcher = useCallback(
    () => getMyPermissions(workspace.id, { token }),
    [workspace.id, token],
  );
  const { status, data: perms, error, reload } =
    useResource<Permissions>(permsFetcher);

  const canManage = !!perms?.permissions.includes("workspace.settings");

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

      <Section title="WEBHOOK SUBSCRIPTIONS">
        <SectionState status={status} error={error} onRetry={reload}>
          {canManage ? (
            <WebhookList
              workspaceId={workspace.id}
              token={token}
              eventTypes={eventTypes}
            />
          ) : (
            <Text style={styles.empty}>
              Webhook subscriptions are managed by workspace owners and admins.
              You don’t have access to this workspace’s webhooks.
            </Text>
          )}
        </SectionState>
      </Section>
    </View>
  );
}

// ---------------------------------------------------------------------------
// The admin-only body: the create form + one-time secret reveal, then the list
// with per-row test / deliveries / revoke. Rendered only once we know the caller
// holds `workspace.settings`, so the reads below never 403.
// ---------------------------------------------------------------------------

interface WebhookListProps {
  workspaceId: string;
  token: string | undefined;
  eventTypes: readonly string[];
}

function WebhookList({ workspaceId, token, eventTypes }: WebhookListProps) {
  const fetcher = useCallback(
    () => listWebhookSubscriptions(workspaceId, { token }),
    [workspaceId, token],
  );
  const { status, data, error, reload, setData } =
    useResource<WebhookSubscription[]>(fetcher);

  // The plaintext signing secret of the most recently created subscription —
  // shown once, then dropped from memory.
  const [revealed, setRevealed] = useState<CreatedWebhookSubscription | null>(
    null,
  );

  const subscriptions = data ?? [];

  const onCreate = useCallback(
    async (url: string, chosen: string[]) => {
      const created = await createWebhookSubscription(
        workspaceId,
        { url, event_types: chosen },
        { token },
      );
      // Surface the one-time secret, and prepend the secret-free list row.
      setRevealed(created);
      const { secret: _secret, ...row } = created;
      setData((prev) => [row, ...(prev ?? [])]);
    },
    [workspaceId, token, setData],
  );

  const onTest = useCallback(
    async (subscriptionId: string) => {
      try {
        const delivery = await testWebhookSubscription(
          workspaceId,
          subscriptionId,
          { token },
        );
        Alert.alert(
          "Test event sent",
          `Status: ${delivery.status}${
            delivery.response_code ? ` (HTTP ${delivery.response_code})` : ""
          }`,
        );
      } catch (err) {
        Alert.alert("Couldn’t send test event", describeError(err));
      }
    },
    [workspaceId, token],
  );

  const doRevoke = useCallback(
    async (subscriptionId: string) => {
      const previous = data;
      // Optimistically mark it revoked, then confirm with the backend.
      setData((prev) =>
        (prev ?? []).map((s) =>
          s.id === subscriptionId ? { ...s, enabled: false } : s,
        ),
      );
      try {
        await deleteWebhookSubscription(workspaceId, subscriptionId, { token });
      } catch (err) {
        setData(() => previous);
        Alert.alert("Couldn’t revoke", describeError(err));
      }
    },
    [workspaceId, token, data, setData],
  );

  const onRevoke = useCallback(
    (subscriptionId: string) =>
      new Promise<void>((resolve) => {
        Alert.alert(
          "Revoke this subscription?",
          "Deliveries to this endpoint will stop immediately. This can’t be undone — you’d need to create a new subscription (and a new signing secret).",
          [
            { text: "Keep", style: "cancel", onPress: () => resolve() },
            {
              text: "Revoke",
              style: "destructive",
              onPress: () => {
                doRevoke(subscriptionId).finally(() => resolve());
              },
            },
          ],
          { cancelable: true, onDismiss: () => resolve() },
        );
      }),
    [doRevoke],
  );

  return (
    <View style={styles.stack}>
      {revealed ? (
        <RevealedSecretBanner
          subscription={revealed}
          onDismiss={() => setRevealed(null)}
        />
      ) : null}

      <WebhookCreateForm eventTypes={eventTypes} onCreate={onCreate} />

      <SectionState status={status} error={error} onRetry={reload}>
        {subscriptions.length === 0 ? (
          <Text style={styles.empty}>
            No webhook subscriptions yet. Create one above to receive signed
            event callbacks (job.completed, publish.*, performance.ingested).
          </Text>
        ) : (
          <View style={styles.list}>
            {subscriptions.map((subscription) => (
              <WebhookSubscriptionCard
                key={subscription.id}
                subscription={subscription}
                workspaceId={workspaceId}
                token={token}
                onTest={onTest}
                onRevoke={onRevoke}
              />
            ))}
          </View>
        )}
      </SectionState>
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
  stack: { gap: 12 },
  list: { gap: 10 },
  empty: {
    color: colors.muted,
    fontSize: 13,
    lineHeight: 18,
    paddingVertical: 8,
  },
});
