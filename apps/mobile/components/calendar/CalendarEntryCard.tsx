import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { colors } from "@/components/me/theme";
import type { CalendarEntry } from "@/lib/calendar";

import {
  formatEntryTime,
  isPending,
  platformSummary,
  statusBadge,
} from "./format";

/**
 * One calendar-agenda row: the entry's local publish time + target platforms +
 * a status badge. Still-`pending` entries expose Reschedule + Cancel actions
 * (both disabled while a mutation for this row is in flight); tapping the row
 * deep-links to the source job. Purely presentational — all state/handlers are
 * owned by the parent screen.
 */
export interface CalendarEntryCardProps {
  entry: CalendarEntry;
  /** True while a reschedule OR cancel request for this row is in flight. */
  busy: boolean;
  onReschedule: (entry: CalendarEntry) => void;
  onCancel: (entry: CalendarEntry) => void;
  onPressJob: (jobId: string) => void;
}

export function CalendarEntryCard({
  entry,
  busy,
  onReschedule,
  onCancel,
  onPressJob,
}: Readonly<CalendarEntryCardProps>) {
  const badge = statusBadge(String(entry.status));
  const pending = isPending(entry);

  return (
    <View style={styles.card}>
      <View style={styles.headerRow}>
        <Text style={styles.time}>{formatEntryTime(entry.scheduled_at)}</Text>
        <Text style={[styles.badge, { color: badge.color }]}>
          {badge.label}
        </Text>
      </View>

      <Text style={styles.platforms} numberOfLines={1}>
        {platformSummary(entry)}
      </Text>

      {entry.job_id ? (
        <Pressable
          onPress={() => onPressJob(entry.job_id as string)}
          accessibilityRole="button"
          accessibilityLabel="View source job"
          hitSlop={6}
        >
          <Text style={styles.jobLink} numberOfLines={1}>
            Job {entry.job_id}
          </Text>
        </Pressable>
      ) : null}

      {pending ? (
        <View style={styles.actions}>
          <Pressable
            style={[styles.action, styles.reschedule, busy && styles.disabled]}
            onPress={() => onReschedule(entry)}
            disabled={busy}
            accessibilityRole="button"
            accessibilityLabel="Reschedule this publish"
            accessibilityState={{ disabled: busy }}
          >
            {busy ? (
              <ActivityIndicator color={colors.accent} />
            ) : (
              <Text style={styles.rescheduleText}>Reschedule</Text>
            )}
          </Pressable>
          <Pressable
            style={[styles.action, styles.cancel, busy && styles.disabled]}
            onPress={() => onCancel(entry)}
            disabled={busy}
            accessibilityRole="button"
            accessibilityLabel="Cancel this scheduled publish"
            accessibilityState={{ disabled: busy }}
          >
            <Text style={styles.cancelText}>Cancel</Text>
          </Pressable>
        </View>
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
    padding: 16,
    gap: 6,
  },
  headerRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 12,
  },
  time: {
    color: colors.textPrimary,
    fontSize: 16,
    fontWeight: "700",
  },
  badge: { fontSize: 13, fontWeight: "700" },
  platforms: { color: colors.textSecondary, fontSize: 14 },
  jobLink: { color: colors.muted, fontSize: 12 },
  actions: { flexDirection: "row", gap: 10, marginTop: 8 },
  action: {
    flex: 1,
    borderWidth: 1,
    borderRadius: 10,
    paddingVertical: 10,
    alignItems: "center",
  },
  reschedule: { borderColor: colors.accent },
  rescheduleText: { color: colors.accent, fontSize: 14, fontWeight: "700" },
  cancel: { borderColor: colors.error },
  cancelText: { color: colors.error, fontSize: 14, fontWeight: "700" },
  disabled: { opacity: 0.5 },
});
