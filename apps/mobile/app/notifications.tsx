/**
 * Notification center — the in-app counterpart to the external webhook. Lists
 * the caller's notifications (newest first) with pull-to-refresh and a "Mark all
 * read" action. Tapping a row marks it read (optimistically) and, when the
 * event carries a `data.job_id`, deep-links to that job.
 *
 * Auth token comes from the session and is sent as `x-api-key` by the shared api
 * client. No secrets live here. The screen owns its own loading + error state.
 */

import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { useFocusEffect, useRouter } from "expo-router";

import {
  ApiError,
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
} from "@/lib/api";
import { useSession } from "@/src/shared/auth";
import type { Notification } from "@/lib/types";

import { colors } from "@/components/me/theme";
import { NotificationItem } from "@/components/notifications/NotificationItem";
import { jobIdFromNotification } from "@/components/notifications/notification-meta";

export default function NotificationsScreen() {
  const { apiKey } = useSession();
  const router = useRouter();
  const token = apiKey ?? undefined;

  const [items, setItems] = useState<Notification[]>([]);
  const [unread, setUnread] = useState(0);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [markingAll, setMarkingAll] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const result = await listNotifications({ token });
      setItems(result.notifications);
      setUnread(result.unread_count);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Failed to load notifications.",
      );
    }
  }, [token]);

  useFocusEffect(
    useCallback(() => {
      let active = true;
      setLoading(true);
      load().finally(() => {
        if (active) setLoading(false);
      });
      return () => {
        active = false;
      };
    }, [load]),
  );

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }, [load]);

  /** Mark one read (optimistic, rolled back on failure), then deep-link. */
  const onPressItem = useCallback(
    (notification: Notification) => {
      const jobId = jobIdFromNotification(notification);

      if (!notification.read) {
        const previous = items;
        const previousUnread = unread;
        setItems((rows) =>
          rows.map((r) =>
            r.id === notification.id ? { ...r, read: true } : r,
          ),
        );
        setUnread((n) => Math.max(0, n - 1));

        markNotificationRead(notification.id, { token }).catch(() => {
          // Roll back the optimistic read on failure.
          setItems(previous);
          setUnread(previousUnread);
        });
      }

      if (jobId) {
        router.push(`/job/${jobId}`);
      }
    },
    [items, unread, token, router],
  );

  /** Mark every notification read (optimistic), reload on failure. */
  const onMarkAll = useCallback(async () => {
    if (markingAll || unread === 0) return;
    setMarkingAll(true);

    const previous = items;
    const previousUnread = unread;
    setItems((rows) => rows.map((r) => (r.read ? r : { ...r, read: true })));
    setUnread(0);

    try {
      await markAllNotificationsRead({ token });
    } catch {
      setItems(previous);
      setUnread(previousUnread);
    } finally {
      setMarkingAll(false);
    }
  }, [markingAll, unread, items, token]);

  if (loading) {
    return (
      <View style={[styles.container, styles.center]}>
        <ActivityIndicator color={colors.accent} size="large" />
      </View>
    );
  }

  const markAllDisabled = markingAll || unread === 0;

  return (
    <View style={styles.container}>
      <View style={styles.toolbar}>
        <Text style={styles.count}>
          {unread > 0 ? `${unread} unread` : "All caught up"}
        </Text>
        <Pressable
          onPress={onMarkAll}
          disabled={markAllDisabled}
          hitSlop={8}
          accessibilityRole="button"
          accessibilityLabel="Mark all notifications read"
        >
          {markingAll ? (
            <ActivityIndicator color={colors.accent} />
          ) : (
            <Text
              style={[
                styles.markAll,
                markAllDisabled ? styles.markAllDisabled : null,
              ]}
            >
              Mark all read
            </Text>
          )}
        </Pressable>
      </View>

      <FlatList
        contentContainerStyle={styles.content}
        data={items}
        keyExtractor={(item) => item.id}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor={colors.accent}
          />
        }
        renderItem={({ item }) => (
          <NotificationItem notification={item} onPress={onPressItem} />
        )}
        ListEmptyComponent={
          <View style={styles.center}>
            <Text style={styles.empty}>
              {error ??
                "No notifications yet. You'll hear from us when your reels finish."}
            </Text>
          </View>
        }
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  center: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    paddingTop: 80,
    paddingHorizontal: 32,
  },
  toolbar: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 20,
    paddingVertical: 12,
    borderBottomColor: colors.border,
    borderBottomWidth: 1,
  },
  count: { color: colors.muted, fontSize: 13, fontWeight: "600" },
  markAll: { color: colors.accent, fontSize: 14, fontWeight: "700" },
  markAllDisabled: { color: colors.muted },
  content: { padding: 20, gap: 12, flexGrow: 1 },
  empty: { color: colors.muted, fontSize: 15, textAlign: "center", lineHeight: 22 },
});
