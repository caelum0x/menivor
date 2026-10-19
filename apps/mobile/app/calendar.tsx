/**
 * Publishing Calendar screen — an agenda / list-by-day view of the caller's
 * scheduled + already-published reels, grouped by DEVICE-LOCAL day (the API
 * speaks UTC; we render in the creator's timezone). Still-`pending` entries can
 * be RESCHEDULED (moved to a new future time via the reschedule sheet) or
 * canceled; tapping a row deep-links to the source job. The background
 * Celery-beat due-runner publishes schedules whose time has arrived and flips
 * them to published/failed; pull-to-refresh reflects that.
 *
 * The loaded window spans a fixed range around today (well within the backend's
 * ~92-day clamp). Cancel reuses the shared `cancelScheduled` from `lib/api.ts`;
 * calendar reads + reschedule come from `lib/calendar.ts`. Auth token comes from
 * the session and is sent as `x-api-key`. No secrets live here.
 */

import { useCallback, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  RefreshControl,
  SectionList,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { useFocusEffect, useRouter } from "expo-router";

import { ApiError, cancelScheduled } from "@/lib/api";
import {
  fetchCalendar,
  type CalendarEntry,
} from "@/lib/calendar";
import { useSession } from "@/src/shared/auth";

import { colors } from "@/components/me/theme";
import { CalendarEntryCard } from "@/components/calendar/CalendarEntryCard";
import { RescheduleSheet } from "@/components/calendar/RescheduleSheet";
import { groupByDay } from "@/components/calendar/format";
import { Icon } from "@/components/ui/Icon";

/** Days of history to show before today (recent published reels). */
const WINDOW_PAST_DAYS = 7;
/** Days into the future to show (upcoming scheduled reels). */
const WINDOW_FUTURE_DAYS = 84;

/** The [start, end] UTC ISO window to load — a fixed span around "now". */
function calendarWindow(now: Date = new Date()): { start: string; end: string } {
  const start = new Date(now);
  start.setDate(now.getDate() - WINDOW_PAST_DAYS);
  start.setHours(0, 0, 0, 0);
  const end = new Date(now);
  end.setDate(now.getDate() + WINDOW_FUTURE_DAYS);
  end.setHours(23, 59, 59, 0);
  return { start: start.toISOString(), end: end.toISOString() };
}

export default function CalendarScreen() {
  const { apiKey } = useSession();
  const router = useRouter();
  const token = apiKey ?? undefined;

  const [entries, setEntries] = useState<CalendarEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sheetEntry, setSheetEntry] = useState<CalendarEntry | null>(null);

  const load = useCallback(async () => {
    setError(null);
    const { start, end } = calendarWindow();
    try {
      const rows = await fetchCalendar(start, end, { token });
      setEntries(rows);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Failed to load the calendar.",
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

  const sections = useMemo(() => groupByDay(entries), [entries]);

  const onPressJob = useCallback(
    (jobId: string) => {
      router.push(`/job/${jobId}`);
    },
    [router],
  );

  const onReschedule = useCallback((entry: CalendarEntry) => {
    setSheetEntry(entry);
  }, []);

  const onRescheduled = useCallback((moved: CalendarEntry) => {
    // Immutably replace the moved row so the agenda re-groups it under its new
    // local day.
    setEntries((rows) => rows.map((r) => (r.id === moved.id ? moved : r)));
    setSheetEntry(null);
  }, []);

  const doCancel = useCallback(
    async (entry: CalendarEntry) => {
      setBusyId(entry.id);
      // Optimistically reflect the cancel; roll back on failure.
      const previous = entries;
      setEntries((rows) =>
        rows.map((r) =>
          r.id === entry.id ? { ...r, status: "canceled" } : r,
        ),
      );
      try {
        await cancelScheduled(entry.id, { token });
      } catch (err) {
        setEntries(previous);
        const message =
          err instanceof ApiError
            ? err.message
            : "Failed to cancel scheduled publish.";
        Alert.alert("Couldn't cancel", message);
      } finally {
        setBusyId(null);
      }
    },
    [entries, token],
  );

  const onCancel = useCallback(
    (entry: CalendarEntry) => {
      Alert.alert(
        "Cancel scheduled publish?",
        "This reel will no longer auto-publish. You can schedule it again later.",
        [
          { text: "Keep", style: "cancel" },
          {
            text: "Cancel publish",
            style: "destructive",
            onPress: () => void doCancel(entry),
          },
        ],
      );
    },
    [doCancel],
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
      <SectionList
        sections={sections}
        keyExtractor={(item) => item.id}
        contentContainerStyle={styles.content}
        stickySectionHeadersEnabled={false}
        ListHeaderComponent={
          <Pressable
            style={styles.channelsLink}
            onPress={() => router.push("/calendar/channels")}
            accessibilityRole="link"
          >
            <Text style={styles.channelsLinkText}>
              Telegram, Discord and Mastodon channels
            </Text>
            <Icon name="chevron-forward" size={16} color={colors.textSecondary} />
          </Pressable>
        }
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor={colors.accent}
          />
        }
        renderSectionHeader={({ section }) => (
          <Text style={styles.sectionHeader}>{section.title}</Text>
        )}
        ItemSeparatorComponent={() => <View style={styles.separator} />}
        renderItem={({ item }) => (
          <CalendarEntryCard
            entry={item}
            busy={busyId === item.id}
            onReschedule={onReschedule}
            onCancel={onCancel}
            onPressJob={onPressJob}
          />
        )}
        ListEmptyComponent={
          <View style={styles.center}>
            <Text style={styles.empty}>
              {error ??
                "No reels scheduled or published in this window. Open a finished reel and tap Schedule to auto-publish it later."}
            </Text>
          </View>
        }
      />

      <RescheduleSheet
        visible={sheetEntry !== null}
        entry={sheetEntry}
        token={token}
        onClose={() => setSheetEntry(null)}
        onRescheduled={onRescheduled}
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
  content: { padding: 20, paddingBottom: 40, flexGrow: 1 },
  separator: { height: 12 },
  channelsLink: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    borderColor: colors.border,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: 6,
    paddingHorizontal: 14,
    paddingVertical: 12,
  },
  channelsLinkText: { color: colors.textPrimary, fontSize: 15, fontWeight: "600" },
  sectionHeader: {
    color: colors.textSecondary,
    fontSize: 13,
    fontWeight: "700",
    textTransform: "uppercase",
    letterSpacing: 0.5,
    marginTop: 20,
    marginBottom: 10,
  },
  empty: {
    color: colors.muted,
    fontSize: 15,
    textAlign: "center",
    lineHeight: 22,
  },
});
