/**
 * Recent deliveries for one webhook subscription. Loads GET
 * /me/workspaces/{id}/webhooks/{subId}/deliveries on mount (newest first) and
 * renders each attempt's status / attempts / response code / time. Read-only and
 * SECRET-FREE — the signed payload body is never returned by the API, so it is
 * never shown. Tenant-scoped server-side (a foreign subscription is a 404).
 */

import { useCallback } from "react";

import { StyleSheet, Text, View } from "react-native";

import { listWebhookDeliveries, type WebhookDelivery } from "@/lib/developer";

import { SectionState } from "@/components/me/Section";
import { colors } from "@/components/me/theme";
import { useResource } from "@/components/me/use-resource";

import { shortDateTime, statusColor, statusLabel } from "./format";

interface WebhookDeliveriesProps {
  workspaceId: string;
  subscriptionId: string;
  token: string | undefined;
}

export function WebhookDeliveries({
  workspaceId,
  subscriptionId,
  token,
}: WebhookDeliveriesProps) {
  const fetcher = useCallback(
    () => listWebhookDeliveries(workspaceId, subscriptionId, 20, { token }),
    [workspaceId, subscriptionId, token],
  );
  const { status, data, error, reload } =
    useResource<WebhookDelivery[]>(fetcher);

  const deliveries = data ?? [];

  return (
    <View style={styles.container}>
      <SectionState status={status} error={error} onRetry={reload}>
        {deliveries.length === 0 ? (
          <Text style={styles.empty}>
            No deliveries yet. Send a test event to see one here.
          </Text>
        ) : (
          <View style={styles.list}>
            {deliveries.map((delivery) => (
              <DeliveryRow key={delivery.id} delivery={delivery} />
            ))}
          </View>
        )}
      </SectionState>
    </View>
  );
}

function DeliveryRow({ delivery }: { delivery: WebhookDelivery }) {
  const code =
    typeof delivery.response_code === "number"
      ? ` · HTTP ${delivery.response_code}`
      : "";
  return (
    <View style={styles.row}>
      <View style={styles.rowMain}>
        <Text style={styles.event} numberOfLines={1}>
          {delivery.event_type || "—"}
        </Text>
        <Text style={styles.meta} numberOfLines={1}>
          {shortDateTime(delivery.last_attempt_at ?? delivery.created_at)} ·{" "}
          {delivery.attempts} attempt{delivery.attempts === 1 ? "" : "s"}
          {code}
        </Text>
      </View>
      <Text style={[styles.status, { color: statusColor(delivery.status) }]}>
        {statusLabel(delivery.status)}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { marginTop: 4 },
  list: { gap: 8 },
  row: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
    backgroundColor: colors.bg,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  rowMain: { flex: 1, gap: 2 },
  event: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  meta: { color: colors.muted, fontSize: 11 },
  status: { fontSize: 12, fontWeight: "700" },
  empty: {
    color: colors.muted,
    fontSize: 13,
    lineHeight: 18,
    paddingVertical: 6,
  },
});
