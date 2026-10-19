/**
 * Platform-admin: the cross-tenant right-to-erasure (GDPR Art. 17) queue
 * (GET /admin/erasure-requests), newest first, with pull-to-refresh and
 * pagination. Read-only here — operator-initiated erasure lives on the Users
 * screen behind confirmation. Staff-gated server-side.
 *
 * NAV MANIFEST:
 *   - { route: "/account/admin/erasure-requests", title: "Erasure Requests" }
 */

import * as React from "react";
import {
  FlatList,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { Stack } from "expo-router";

import { colors } from "@/components/me/theme";
import {
  adminListErasureRequests,
  DEFAULT_ADMIN_COMPLIANCE_LIMIT,
} from "@/lib/admin";
import type { ErasureRequest } from "@/lib/compliance";
import {
  AdminListState,
  Badge,
  Card,
  KeyValue,
  LoadMoreFooter,
  adminStyles,
  formatDateTime,
} from "@/components/admin/ui";
import { useAdminList } from "@/components/admin/use-admin-list";
import { useSession } from "@/src/shared/auth";

function toneForStatus(
  status: string,
): "neutral" | "success" | "warning" | "danger" {
  const s = status.toLowerCase();
  if (s === "completed") return "success";
  if (s === "processing") return "warning";
  if (s === "failed") return "danger";
  return "neutral";
}

export default function AdminErasureRequestsScreen(): React.ReactElement {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  const fetcher = React.useCallback(
    (
      window: { limit: number; offset: number },
      transport: { token?: string; signal: AbortSignal },
    ) => adminListErasureRequests(window, transport),
    [],
  );

  const list = useAdminList<ErasureRequest>(
    fetcher,
    token,
    DEFAULT_ADMIN_COMPLIANCE_LIMIT,
  );

  const renderItem = React.useCallback(
    ({ item }: { item: ErasureRequest }): React.ReactElement => (
      <Card>
        <View style={styles.rowBetween}>
          <Text style={styles.id} numberOfLines={1}>
            {item.scope || "user"}
          </Text>
          <Badge
            label={item.status || "requested"}
            tone={toneForStatus(item.status || "requested")}
          />
        </View>
        <KeyValue label="Request id" value={item.id} />
        <KeyValue label="User id" value={item.user_id} />
        <KeyValue label="Requested" value={formatDateTime(item.requested_at)} />
        <KeyValue label="Completed" value={formatDateTime(item.completed_at)} />
      </Card>
    ),
    [],
  );

  return (
    <View style={adminStyles.container}>
      <Stack.Screen options={{ title: "Erasure Requests" }} />
      <FlatList
        data={list.items as ErasureRequest[]}
        keyExtractor={(item) => item.id}
        renderItem={renderItem}
        contentContainerStyle={adminStyles.content}
        refreshControl={
          <RefreshControl
            refreshing={list.status === "refreshing"}
            onRefresh={list.refresh}
            tintColor={colors.accent}
          />
        }
        onEndReachedThreshold={0.4}
        onEndReached={list.loadMore}
        ListHeaderComponent={
          <Text style={adminStyles.intro}>
            Every right-to-erasure request across every tenant, newest first.
            Erasure anonymizes PII in place while preserving financial records.
          </Text>
        }
        ListEmptyComponent={
          <AdminListState
            loading={list.initialLoading}
            error={list.error}
            empty={list.status === "ready"}
            emptyTitle="No erasure requests"
            emptyHint="No right-to-erasure requests have been filed."
            onRetry={list.refresh}
          />
        }
        ListFooterComponent={
          <LoadMoreFooter
            hasMore={list.hasMore}
            loading={list.status === "loadingMore"}
            count={list.items.length}
            onLoadMore={list.loadMore}
          />
        }
      />
    </View>
  );
}

const styles = StyleSheet.create({
  rowBetween: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
  },
  id: {
    color: colors.textPrimary,
    fontSize: 16,
    fontWeight: "700",
    flexShrink: 1,
    textTransform: "capitalize",
  },
});
