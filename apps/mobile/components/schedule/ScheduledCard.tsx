import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { colors } from "@/components/me/theme";
import type { ScheduledPublish } from "@/lib/types";

import {
  formatScheduledAt,
  isPending,
  platformSummary,
  statusBadge,
} from "./format";

/**
 * One scheduled-publish row: platforms + local publish time + a status badge.
 * Pending rows expose a Cancel action (disabled while a cancel is in flight);
 * failed rows surface the error. Tapping the row deep-links to the source job.
 * Purely presentational — all state/handlers are owned by the parent screen.
 */
export interface ScheduledCardProps {
  schedule: ScheduledPublish;
  /** True while this row's cancel request is in flight. */
  canceling: boolean;
  onCancel: (schedule: ScheduledPublish) => void;
  onPressJob: (jobId: string) => void;
}

export function ScheduledCard({
  schedule,
  canceling,
  onCancel,
  onPressJob,
}: Readonly<ScheduledCardProps>) {
  const badge = statusBadge(String(schedule.status));
  const pending = isPending(schedule);

  return (
    <View style={styles.card}>
      <View style={styles.headerRow}>
        <Text style={styles.platforms} numberOfLines={1}>
          {platformSummary(schedule)}
        </Text>
        <Text style={[styles.badge, { color: badge.color }]}>
          {badge.label}
        </Text>
      </View>

      <Text style={styles.time}>{formatScheduledAt(schedule.scheduled_at)}</Text>

      <Pressable
        onPress={() => onPressJob(schedule.job_id)}
        accessibilityRole="button"
        accessibilityLabel="View source job"
        hitSlop={6}
      >
        <Text style={styles.jobLink} numberOfLines={1}>
          Job {schedule.job_id}
        </Text>
      </Pressable>

      {schedule.status === "failed" && schedule.error ? (
        <Text style={styles.error} numberOfLines={3}>
          {schedule.error}
        </Text>
      ) : null}

      {pending ? (
        <Pressable
          style={[styles.cancel, canceling && styles.disabled]}
          onPress={() => onCancel(schedule)}
          disabled={canceling}
          accessibilityRole="button"
          accessibilityLabel="Cancel scheduled publish"
          accessibilityState={{ disabled: canceling }}
        >
          {canceling ? (
            <ActivityIndicator color={colors.error} />
          ) : (
            <Text style={styles.cancelText}>Cancel</Text>
          )}
        </Pressable>
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
  platforms: {
    color: colors.textPrimary,
    fontSize: 15,
    fontWeight: "700",
    flex: 1,
  },
  badge: { fontSize: 13, fontWeight: "700" },
  time: { color: colors.textSecondary, fontSize: 14 },
  jobLink: { color: colors.muted, fontSize: 12 },
  error: { color: colors.error, fontSize: 13, marginTop: 2 },
  cancel: {
    marginTop: 8,
    borderColor: colors.error,
    borderWidth: 1,
    borderRadius: 10,
    paddingVertical: 10,
    alignItems: "center",
  },
  disabled: { opacity: 0.5 },
  cancelText: { color: colors.error, fontSize: 14, fontWeight: "700" },
});
