/**
 * Platform-admin: platform-wide revenue summary (GET /admin/revenue). Read-only.
 * All amounts are INTEGER minor units (cents) — never a float. Staff-gated
 * server-side; a non-staff caller sees a "platform-admin only" notice.
 *
 * NAV MANIFEST:
 *   - { route: "/account/admin/revenue", title: "Revenue" }
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
import { getRevenue, type Revenue } from "@/lib/billing";
import { isAbortError } from "@/lib/api";
import { describeError } from "@/components/me/errors";
import {
  AdminListState,
  adminStyles,
  formatCents,
  formatCount,
} from "@/components/admin/ui";
import { StatCard } from "@/components/me/StatCard";
import { useSession } from "@/src/shared/auth";

type Status = "loading" | "refreshing" | "ready" | "error";

export default function AdminRevenueScreen(): React.ReactElement {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  const [revenue, setRevenue] = React.useState<Revenue | null>(null);
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
      getRevenue({ token, signal: controller.signal })
        .then((res) => {
          if (ticket !== ticketRef.current) return;
          setRevenue(res);
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

  const stateBlock = (
    <AdminListState
      loading={status === "loading"}
      error={error}
      empty={false}
      emptyTitle=""
      onRetry={refresh}
    />
  );

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
      <Stack.Screen options={{ title: "Revenue" }} />

      <Text style={adminStyles.intro}>
        Platform-wide revenue across every tenant. All amounts are exact integer
        cents. Pull to refresh.
      </Text>

      {status === "ready" && revenue ? (
        <View style={styles.grid}>
          <StatCard
            label="Gross revenue"
            value={formatCents(revenue.revenue_cents)}
            hint="Total charged across all tenants"
            accent={colors.success}
          />
          <StatCard
            label="Net revenue"
            value={formatCents(revenue.net_cents)}
            hint="Revenue minus credit liability"
          />
          <StatCard
            label="Credits granted"
            value={formatCount(revenue.credits_granted)}
            hint="Whole credits issued"
          />
        </View>
      ) : (
        stateBlock
      )}

      <View style={styles.spacer} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 12 },
  spacer: { height: 40 },
});
