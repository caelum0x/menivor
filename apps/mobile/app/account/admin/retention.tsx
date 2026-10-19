/**
 * Platform-admin: cross-tenant retention-posture overview (GET /admin/retention).
 * Read-only — every configured workspace's data-retention window. A `null`
 * day-count reads as "keep forever". This endpoint is not paginated server-side,
 * so the whole overview loads at once with pull-to-refresh. Staff-gated.
 *
 * NAV MANIFEST:
 *   - { route: "/account/admin/retention", title: "Retention" }
 */

import * as React from "react";
import {
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { Stack } from "expo-router";

import { colors } from "@/components/me/theme";
import {
  adminListRetention,
  type RetentionPolicy,
} from "@/lib/admin";
import { isAbortError } from "@/lib/api";
import { describeError } from "@/components/me/errors";
import {
  AdminListState,
  Card,
  KeyValue,
  adminStyles,
  formatDateTime,
  retentionLabel,
} from "@/components/admin/ui";
import { useSession } from "@/src/shared/auth";

type Status = "loading" | "refreshing" | "ready" | "error";

export default function AdminRetentionScreen(): React.ReactElement {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  const [policies, setPolicies] = React.useState<readonly RetentionPolicy[]>([]);
  const [status, setStatus] = React.useState<Status>("loading");
  const [error, setError] = React.useState("");
  const ticketRef = React.useRef(0);

  const load = React.useCallback(
    (mode: "initial" | "refresh"): (() => void) => {
      const ticket = ticketRef.current + 1;
      ticketRef.current = ticket;
      const controller = new AbortController();
      setError("");
      setStatus(mode === "refresh" ? "refreshing" : "loading");
      adminListRetention({ token, signal: controller.signal })
        .then((res) => {
          if (ticket !== ticketRef.current) return;
          setPolicies([...res]);
          setStatus("ready");
        })
        .catch((err: unknown) => {
          if (isAbortError(err) || ticket !== ticketRef.current) return;
          setError(describeError(err));
          setStatus("error");
        });
      return () => controller.abort();
    },
    [token],
  );

  React.useEffect(() => {
    const cancel = load("initial");
    return cancel;
  }, [load]);

  const refresh = React.useCallback(() => {
    load("refresh");
  }, [load]);

  const ready = status === "ready";

  return (
    <ScrollView
      style={adminStyles.container}
      contentContainerStyle={adminStyles.content}
      refreshControl={
        <RefreshControl
          refreshing={status === "refreshing"}
          onRefresh={refresh}
          tintColor={colors.accent}
        />
      }
    >
      <Stack.Screen options={{ title: "Retention" }} />

      <Text style={adminStyles.intro}>
        Every configured workspace data-retention window. "Keep forever" means
        that dimension is never swept.
      </Text>

      {!ready || policies.length === 0 ? (
        <AdminListState
          loading={status === "loading"}
          error={error}
          empty={ready && policies.length === 0}
          emptyTitle="No retention policies"
          emptyHint="No workspace has configured a retention window yet."
          onRetry={refresh}
        />
      ) : (
        policies.map((policy) => (
          <Card key={policy.workspace_id}>
            <Text style={styles.workspace} numberOfLines={1}>
              {policy.workspace_id}
            </Text>
            <KeyValue
              label="Jobs retention"
              value={retentionLabel(policy.jobs_retention_days)}
            />
            <KeyValue
              label="Assets retention"
              value={retentionLabel(policy.assets_retention_days)}
            />
            <KeyValue label="Updated" value={formatDateTime(policy.updated_at)} />
          </Card>
        ))
      )}

      <View style={styles.spacer} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  workspace: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  spacer: { height: 40 },
});
