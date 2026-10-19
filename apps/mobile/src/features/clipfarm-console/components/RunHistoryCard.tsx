/**
 * RunHistoryCard — presentational summary of one persisted runner pass
 * (`channel_runs` row). Renders the stored `RunResult.summary()` outcome plus a
 * timestamp. Purely presentational: the parent screen owns the data.
 */

import { StyleSheet, Text, View } from "react-native";

import { colors } from "@/components/me/theme";
import type { ChannelRunView } from "@/lib/series";

import { formatRunSummary, runOutcome } from "../logic";

export interface RunHistoryCardProps {
  run: ChannelRunView;
}

function formatWhen(iso: string | null): string {
  if (!iso) return "—";
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return iso;
  return new Date(ms).toLocaleString();
}

export function RunHistoryCard({ run }: Readonly<RunHistoryCardProps>) {
  const outcome = runOutcome(run);
  const rendered = outcome?.rendered ?? 0;
  return (
    <View style={styles.card} testID={`run-${run.id}`}>
      <View style={styles.header}>
        <Text style={styles.runId} numberOfLines={1}>
          {run.params?.run_id ?? run.id}
        </Text>
        <View style={[styles.badge, rendered > 0 && styles.badgeActive]}>
          <Text style={styles.badgeText}>{rendered} rendered</Text>
        </View>
      </View>
      <Text style={styles.summary}>
        {outcome ? formatRunSummary(outcome) : "No summary recorded."}
      </Text>
      <Text style={styles.when}>{formatWhen(run.created_at)}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.card,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 16,
    gap: 8,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
  },
  runId: {
    color: colors.textPrimary,
    fontSize: 14,
    fontWeight: "700",
    flex: 1,
  },
  badge: {
    backgroundColor: colors.cardAlt,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  badgeActive: { backgroundColor: colors.primary },
  badgeText: { color: colors.textPrimary, fontSize: 12, fontWeight: "600" },
  summary: { color: colors.textSecondary, fontSize: 13, lineHeight: 18 },
  when: { color: colors.muted, fontSize: 12 },
});
