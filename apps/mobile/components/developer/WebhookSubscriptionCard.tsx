/**
 * One webhook subscription row: its callback URL, the events it listens for, an
 * enabled/revoked status badge, and the owner/admin actions offered on mobile —
 * send a signed test event, expand recent deliveries, and revoke.
 *
 * NOTE on "enabled": the API exposes create / list / revoke / test / deliveries
 * but no enable-disable toggle, so `enabled` is shown READ-ONLY here and Revoke is
 * the disable action (a revoked subscription stops receiving deliveries). This
 * keeps the screen honest — the client never calls an endpoint that doesn't exist.
 *
 * Every action is authorised + tenant-scoped server-side (RBAC
 * `workspace.settings`); no secret is shown after create.
 */

import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

import type { WebhookSubscription } from "@/lib/developer";

import { colors } from "@/components/me/theme";

import { WebhookDeliveries } from "./WebhookDeliveries";
import { shortDate } from "./format";

interface WebhookSubscriptionCardProps {
  subscription: WebhookSubscription;
  workspaceId: string;
  token: string | undefined;
  /** Send a signed test event; resolves when the API responds. */
  onTest: (subscriptionId: string) => Promise<void>;
  /** Revoke (with confirmation handled by the parent). */
  onRevoke: (subscriptionId: string) => Promise<void>;
}

export function WebhookSubscriptionCard({
  subscription,
  workspaceId,
  token,
  onTest,
  onRevoke,
}: WebhookSubscriptionCardProps) {
  const [testing, setTesting] = useState(false);
  const [revoking, setRevoking] = useState(false);
  const [showDeliveries, setShowDeliveries] = useState(false);

  const busy = testing || revoking;

  const doTest = useCallback(async () => {
    if (busy) return;
    setTesting(true);
    try {
      await onTest(subscription.id);
      // Reveal deliveries so the fresh test attempt is visible.
      setShowDeliveries(true);
    } finally {
      setTesting(false);
    }
  }, [busy, onTest, subscription.id]);

  const doRevoke = useCallback(async () => {
    if (busy) return;
    setRevoking(true);
    try {
      await onRevoke(subscription.id);
    } finally {
      setRevoking(false);
    }
  }, [busy, onRevoke, subscription.id]);

  return (
    <View style={styles.card}>
      <View style={styles.headerRow}>
        <Text style={styles.url} numberOfLines={2}>
          {subscription.url}
        </Text>
        <View
          style={[
            styles.badge,
            subscription.enabled ? styles.badgeOn : styles.badgeOff,
          ]}
        >
          <Text
            style={[
              styles.badgeText,
              subscription.enabled ? styles.badgeTextOn : styles.badgeTextOff,
            ]}
          >
            {subscription.enabled ? "Enabled" : "Revoked"}
          </Text>
        </View>
      </View>

      {subscription.event_types.length > 0 ? (
        <View style={styles.chips}>
          {subscription.event_types.map((eventType) => (
            <Text key={eventType} style={styles.chip}>
              {eventType}
            </Text>
          ))}
        </View>
      ) : (
        <Text style={styles.meta}>No events</Text>
      )}

      <Text style={styles.meta}>Created {shortDate(subscription.created_at)}</Text>

      <View style={styles.actions}>
        {subscription.enabled ? (
          <Pressable
            style={[styles.action, busy && styles.actionDisabled]}
            onPress={doTest}
            disabled={busy}
            accessibilityRole="button"
            accessibilityLabel="Send test event"
          >
            {testing ? (
              <ActivityIndicator color={colors.textSecondary} size="small" />
            ) : (
              <Text style={styles.actionText}>Send test</Text>
            )}
          </Pressable>
        ) : null}

        <Pressable
          style={[styles.action, busy && styles.actionDisabled]}
          onPress={() => setShowDeliveries((v) => !v)}
          disabled={busy}
          accessibilityRole="button"
          accessibilityLabel={
            showDeliveries ? "Hide deliveries" : "Show deliveries"
          }
        >
          <Text style={styles.actionText}>
            {showDeliveries ? "Hide deliveries" : "Deliveries"}
          </Text>
        </Pressable>

        {subscription.enabled ? (
          <Pressable
            style={[styles.action, styles.revoke, busy && styles.actionDisabled]}
            onPress={doRevoke}
            disabled={busy}
            accessibilityRole="button"
            accessibilityLabel="Revoke subscription"
          >
            {revoking ? (
              <ActivityIndicator color={colors.error} size="small" />
            ) : (
              <Text style={[styles.actionText, styles.revokeText]}>Revoke</Text>
            )}
          </Pressable>
        ) : null}
      </View>

      {showDeliveries ? (
        <WebhookDeliveries
          workspaceId={workspaceId}
          subscriptionId={subscription.id}
          token={token}
        />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    gap: 10,
  },
  headerRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: 10,
  },
  url: {
    flex: 1,
    color: colors.textPrimary,
    fontSize: 14,
    fontWeight: "600",
  },
  badge: {
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderWidth: 1,
  },
  badgeOn: {
    backgroundColor: "rgba(74,222,128,0.12)",
    borderColor: colors.success,
  },
  badgeOff: {
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
  },
  badgeText: { fontSize: 11, fontWeight: "700" },
  badgeTextOn: { color: colors.success },
  badgeTextOff: { color: colors.muted },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: {
    color: colors.textSecondary,
    fontSize: 12,
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 5,
    overflow: "hidden",
  },
  meta: { color: colors.muted, fontSize: 12 },
  actions: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 2 },
  action: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 14,
    paddingVertical: 9,
    minWidth: 88,
    alignItems: "center",
    justifyContent: "center",
  },
  actionDisabled: { opacity: 0.5 },
  actionText: { color: colors.textSecondary, fontWeight: "600", fontSize: 13 },
  revoke: { borderColor: colors.error },
  revokeText: { color: colors.error },
});
