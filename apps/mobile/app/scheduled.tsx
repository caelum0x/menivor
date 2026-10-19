/**
 * Scheduled publishes screen (canonical; legacy /publish-schedule redirects
 * here — publish-now lives at /connections/publish and scheduling a new
 * auto-publish starts from a finished reel's detail screen). Lists the caller's queued auto-publishes (soonest
 * due first) with pull-to-refresh; each still-pending row can be canceled and
 * tapping a row deep-links to the source job. The background Celery-beat
 * due-runner publishes schedules whose time has arrived and flips them to
 * published/failed; refreshing reflects that.
 *
 * Auth token comes from the session and is sent as `x-api-key` by the shared api
 * client. No secrets live here. The screen owns its own loading + error state.
 */

import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { useFocusEffect, useRouter } from "expo-router";

import { ApiError, cancelScheduled, listScheduled } from "@/lib/api";
import { useSession } from "@/src/shared/auth";
import type { ScheduledPublish } from "@/lib/types";

import { colors } from "@/components/me/theme";
import { ScheduledCard } from "@/components/schedule/ScheduledCard";

export default function ScheduledScreen() {
  const { apiKey } = useSession();
  const router = useRouter();
  const token = apiKey ?? undefined;

  const [items, setItems] = useState<ScheduledPublish[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [cancelingId, setCancelingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const rows = await listScheduled({ token });
      setItems(rows);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Failed to load scheduled publishes.",
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

  const doCancel = useCallback(
    async (schedule: ScheduledPublish) => {
      setCancelingId(schedule.id);
      // Optimistically reflect the cancel; roll back on failure.
      const previous = items;
      setItems((rows) =>
        rows.map((r) =>
          r.id === schedule.id ? { ...r, status: "canceled" } : r,
        ),
      );
      try {
        await cancelScheduled(schedule.id, { token });
      } catch (err) {
        setItems(previous);
        const message =
          err instanceof ApiError
            ? err.message
            : "Failed to cancel scheduled publish.";
        Alert.alert("Couldn't cancel", message);
      } finally {
        setCancelingId(null);
      }
    },
    [items, token],
  );

  const onCancel = useCallback(
    (schedule: ScheduledPublish) => {
      Alert.alert(
        "Cancel scheduled publish?",
        "This reel will no longer auto-publish. You can schedule it again later.",
        [
          { text: "Keep", style: "cancel" },
          {
            text: "Cancel publish",
            style: "destructive",
            onPress: () => void doCancel(schedule),
          },
        ],
      );
    },
    [doCancel],
  );

  const onPressJob = useCallback(
    (jobId: string) => {
      router.push(`/job/${jobId}`);
    },
    [router],
  );

  if (loading) {
    return (
      <View style={[styles.container, styles.center]}>
        <ActivityIndicator color={colors.accent} size="large" />
      </View>
    );
  }

  return (
    <View style={styles.container}>
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
        ListHeaderComponent={
          <View style={styles.header}>
            <View style={styles.actions}>
              <Pressable
                style={styles.action}
                onPress={() => router.push("/(tabs)/jobs")}
                accessibilityRole="button"
                accessibilityLabel="Pick a finished reel to schedule"
              >
                <Text style={styles.actionText}>Schedule a reel</Text>
              </Pressable>
              <Pressable
                style={styles.action}
                onPress={() => router.push("/connections/publish")}
                accessibilityRole="button"
                accessibilityLabel="Publish a finished reel now"
              >
                <Text style={styles.actionText}>Publish now</Text>
              </Pressable>
            </View>
            {error && items.length > 0 ? (
              <Text style={styles.error}>{error}</Text>
            ) : null}
          </View>
        }
        renderItem={({ item }) => (
          <ScheduledCard
            schedule={item}
            canceling={cancelingId === item.id}
            onCancel={onCancel}
            onPressJob={onPressJob}
          />
        )}
        ListEmptyComponent={
          <View style={styles.center}>
            <Text style={styles.empty}>
              {error ??
                "Nothing scheduled yet. Open a finished reel and tap Schedule to auto-publish it later."}
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
  content: { padding: 20, gap: 12, flexGrow: 1 },
  header: { gap: 10 },
  actions: { flexDirection: "row", gap: 10 },
  action: {
    flex: 1,
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    paddingVertical: 12,
    alignItems: "center",
  },
  actionText: { color: colors.textPrimary, fontSize: 14, fontWeight: "600" },
  error: { color: colors.error, fontSize: 13 },
  empty: {
    color: colors.muted,
    fontSize: 15,
    textAlign: "center",
    lineHeight: 22,
  },
});
