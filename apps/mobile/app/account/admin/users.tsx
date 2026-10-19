/**
 * Platform-admin: cross-tenant user directory (GET /admin/users) with two
 * audited write actions per row — POST /admin/impersonate (mint a short-lived,
 * scoped grant) and POST /admin/erasure/{user_id} (irreversible PII erasure) —
 * each behind an explicit confirmation dialog.
 *
 * The impersonation token is treated as a short-lived secret: it is NEVER
 * displayed or persisted; the UI only confirms that a grant was minted and shows
 * its lifetime. Erasure anonymizes the target's PII in place (never a cascade
 * delete) and cannot be undone. Every action is authorized SERVER-SIDE by the
 * `is_staff` gate; the client only renders the outcome.
 *
 * NAV MANIFEST:
 *   - { route: "/account/admin/users", title: "Users" }
 */

import * as React from "react";
import {
  Alert,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { Stack } from "expo-router";

import { colors } from "@/components/me/theme";
import { adminImpersonate, adminListUsers } from "@/lib/api";
import { adminEraseUser } from "@/lib/admin";
import { DEFAULT_ADMIN_LIMIT } from "@/lib/types";
import { describeError } from "@/components/me/errors";
import {
  AdminListState,
  Badge,
  Card,
  KeyValue,
  LoadMoreFooter,
  adminStyles,
  formatCount,
  formatDateTime,
} from "@/components/admin/ui";
import { useAdminList } from "@/components/admin/use-admin-list";
import type { AdminUser } from "@/lib/types";
import { useSession } from "@/src/shared/auth";

export default function AdminUsersScreen(): React.ReactElement {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  const fetcher = React.useCallback(
    (
      window: { limit: number; offset: number },
      transport: { token?: string; signal: AbortSignal },
    ) => adminListUsers(window, transport),
    [],
  );

  const list = useAdminList<AdminUser>(fetcher, token, DEFAULT_ADMIN_LIMIT);
  const [busyUserId, setBusyUserId] = React.useState<string | null>(null);

  const onImpersonate = React.useCallback(
    (user: AdminUser): void => {
      const who = user.email || user.display_name || user.id;
      Alert.alert(
        "Impersonate user",
        `Mint a short-lived, scoped impersonation grant for ${who}? This is recorded in the audit log.`,
        [
          { text: "Cancel", style: "cancel" },
          {
            text: "Impersonate",
            style: "default",
            onPress: () => {
              setBusyUserId(user.id);
              adminImpersonate(user.id, { token })
                .then((grant) => {
                  Alert.alert(
                    "Grant minted",
                    `A ${grant.scope || "scoped"} grant for ${who} was created and expires in ${Math.round(
                      grant.expires_in / 60,
                    )} min. The token was not stored on this device.`,
                  );
                })
                .catch((err: unknown) => {
                  Alert.alert(
                    "Could not impersonate",
                    describeError(err, "The grant could not be minted."),
                  );
                })
                .finally(() => setBusyUserId(null));
            },
          },
        ],
      );
    },
    [token],
  );

  const onErase = React.useCallback(
    (user: AdminUser): void => {
      const who = user.email || user.display_name || user.id;
      Alert.alert(
        "Erase user",
        `Permanently anonymize ${who}'s personal data? This revokes their credentials and tombstones their PII while preserving financial/audit records. This CANNOT be undone.`,
        [
          { text: "Cancel", style: "cancel" },
          {
            text: "Erase",
            style: "destructive",
            onPress: () => {
              setBusyUserId(user.id);
              adminEraseUser(user.id, { token })
                .then((result) => {
                  Alert.alert(
                    "Erasure started",
                    `Request ${result.id} is now "${result.status}". The account's data is being anonymized.`,
                  );
                  list.refresh();
                })
                .catch((err: unknown) => {
                  Alert.alert(
                    "Could not erase",
                    describeError(err, "The erasure could not be started."),
                  );
                })
                .finally(() => setBusyUserId(null));
            },
          },
        ],
      );
    },
    [token, list],
  );

  const renderItem = React.useCallback(
    ({ item }: { item: AdminUser }): React.ReactElement => {
      const busy = busyUserId === item.id;
      return (
        <Card>
          <View style={styles.rowBetween}>
            <Text style={styles.name} numberOfLines={1}>
              {item.display_name || item.email || "Unnamed user"}
            </Text>
            {item.is_staff ? <Badge label="Staff" tone="warning" /> : null}
          </View>
          <KeyValue label="Email" value={item.email || "—"} />
          <KeyValue label="User id" value={item.id} />
          <KeyValue label="Credits" value={formatCount(item.credits)} />
          <KeyValue label="Joined" value={formatDateTime(item.created_at)} />

          <View style={styles.actions}>
            <Pressable
              style={[styles.action, styles.actionGhost, busy && styles.disabled]}
              disabled={busy}
              onPress={() => onImpersonate(item)}
              accessibilityRole="button"
              accessibilityLabel={`Impersonate ${item.email || item.id}`}
            >
              <Text style={styles.actionGhostText}>
                {busy ? "Working…" : "Impersonate"}
              </Text>
            </Pressable>
            <Pressable
              style={[styles.action, styles.actionDanger, busy && styles.disabled]}
              disabled={busy}
              onPress={() => onErase(item)}
              accessibilityRole="button"
              accessibilityLabel={`Erase ${item.email || item.id}`}
            >
              <Text style={styles.actionDangerText}>Erase</Text>
            </Pressable>
          </View>
        </Card>
      );
    },
    [busyUserId, onImpersonate, onErase],
  );

  return (
    <View style={adminStyles.container}>
      <Stack.Screen options={{ title: "Users" }} />
      <FlatList
        data={list.items as AdminUser[]}
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
            Every account across every tenant, newest first. Actions are audited
            and enforced server-side.
          </Text>
        }
        ListEmptyComponent={
          <AdminListState
            loading={list.initialLoading}
            error={list.error}
            empty={list.status === "ready"}
            emptyTitle="No users"
            emptyHint="No accounts were returned for this window."
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
  name: {
    color: colors.textPrimary,
    fontSize: 16,
    fontWeight: "700",
    flexShrink: 1,
  },
  actions: { flexDirection: "row", gap: 8, marginTop: 4 },
  action: {
    flex: 1,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
    borderWidth: 1,
  },
  actionGhost: { borderColor: colors.border, backgroundColor: "transparent" },
  actionGhostText: { color: colors.textPrimary, fontSize: 13, fontWeight: "600" },
  actionDanger: { borderColor: colors.error, backgroundColor: "transparent" },
  actionDangerText: { color: colors.error, fontSize: 13, fontWeight: "600" },
  disabled: { opacity: 0.5 },
});
