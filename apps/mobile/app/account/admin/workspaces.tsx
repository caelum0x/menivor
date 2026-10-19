/**
 * Platform-admin: cross-tenant workspace directory (GET /admin/workspaces),
 * newest first, with pull-to-refresh and pagination. Read-only. Staff-gated
 * server-side.
 *
 * NAV MANIFEST:
 *   - { route: "/account/admin/workspaces", title: "Workspaces" }
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
import { adminListWorkspaces } from "@/lib/api";
import {
  AdminListState,
  Card,
  KeyValue,
  LoadMoreFooter,
  adminStyles,
  formatDateTime,
} from "@/components/admin/ui";
import { useAdminList } from "@/components/admin/use-admin-list";
import { DEFAULT_ADMIN_LIMIT } from "@/lib/types";
import type { AdminWorkspace } from "@/lib/types";
import { useSession } from "@/src/shared/auth";

export default function AdminWorkspacesScreen(): React.ReactElement {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  const fetcher = React.useCallback(
    (
      window: { limit: number; offset: number },
      transport: { token?: string; signal: AbortSignal },
    ) => adminListWorkspaces(window, transport),
    [],
  );

  const list = useAdminList<AdminWorkspace>(fetcher, token, DEFAULT_ADMIN_LIMIT);

  const renderItem = React.useCallback(
    ({ item }: { item: AdminWorkspace }): React.ReactElement => (
      <Card>
        <Text style={styles.name} numberOfLines={1}>
          {item.name || "Untitled workspace"}
        </Text>
        <KeyValue label="Workspace id" value={item.id} />
        <KeyValue label="Owner id" value={item.owner_id} />
        <KeyValue label="Created" value={formatDateTime(item.created_at)} />
      </Card>
    ),
    [],
  );

  return (
    <View style={adminStyles.container}>
      <Stack.Screen options={{ title: "Workspaces" }} />
      <FlatList
        data={list.items as AdminWorkspace[]}
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
            Every workspace across every tenant, newest first.
          </Text>
        }
        ListEmptyComponent={
          <AdminListState
            loading={list.initialLoading}
            error={list.error}
            empty={list.status === "ready"}
            emptyTitle="No workspaces"
            emptyHint="No workspaces were returned for this window."
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
  name: { color: colors.textPrimary, fontSize: 16, fontWeight: "700" },
});
